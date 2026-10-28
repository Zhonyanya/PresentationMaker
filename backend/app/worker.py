"""Доставка заданий, выполнение без открытой транзакции и атомарная публикация JSON."""

import json
import logging
import os
import secrets
import signal
import subprocess
import sys
from datetime import timedelta
from functools import wraps
from uuid import UUID

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select, text, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.process import exchange
from app.db.engine import sync_sessions
from app.db.models import Job, Presentation, Session, utcnow
from app.jobs.service import ACTIVE
from app.presentations.schemas import normalize_document, validate_revision

logger = logging.getLogger(__name__)
settings = get_settings()
celery = Celery("presentation_maker", broker=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=False,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=2,
    broker_transport_options={
        "visibility_timeout": settings.job_deadline_seconds + 300,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
    },
    task_publish_retry=False,
    task_routes={"pm.maintenance": {"queue": "pm.maintenance"}},
    task_soft_time_limit=settings.job_deadline_seconds + 10,
    task_time_limit=settings.job_deadline_seconds + 30,
    beat_schedule={"recover-jobs": {"task": "pm.maintenance", "schedule": 15.0}},
    timezone="UTC",
)


class TaskStateUnavailable(RuntimeError):
    """Безопасная ошибка доставки без приватного контекста исходного исключения."""


def private_task_errors(function):
    """Не передаёт Celery цепочки исключений с SQL/приватными параметрами.

    Источник статуса — PostgreSQL, не Celery result backend. Если записать
    ошибку в БД невозможно, queued/running восстановит отдельный maintenance.
    """

    @wraps(function)
    def protected(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            logger.error("task_failed task=%s error_type=%s", function.__name__, type(exc).__name__)
        # Поднимаем за пределами except: даже __context__ не ссылается на
        # исходную ошибку SQL. throws у задачи исключает traceback в логах Celery.
        raise TaskStateUnavailable(
            "Task state could not be persisted; inspect safe service logs"
        ) from None

    return protected


def dispatch_job(identifier: UUID):
    """Пытается отправить только ID принятого задания в Celery.

    Время отправки фиксируется до обращения к брокеру. Ошибка публикации
    оставляет queued-запись для повторной доставки через Beat; повторное
    сообщение не даёт права повторно выполнить уже захваченное задание.

    Args:
        identifier: ID задания в PostgreSQL.
    """
    try:
        with sync_sessions()() as db, db.begin():
            job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
            if job is None or job.status != "queued" or job.deadline_at <= utcnow():
                return
            if job.dispatched_at and job.dispatched_at > utcnow() - timedelta(
                seconds=settings.dispatch_retry_seconds
            ):
                return
            job.dispatched_at = utcnow()
        execute_job.apply_async(args=[str(identifier)], retry=False)
    except Exception as exc:
        # Текст исключения может содержать URL брокера и секреты; пишем только тип.
        logger.warning(
            "job_dispatch_failed job_id=%s error_type=%s", identifier, type(exc).__name__
        )


def fail_job(identifier, attempt, code, message, *, timed_out=False):
    """Завершает только действующую попытку, не меняя текущий документ.

    Истёкший deadline имеет приоритет над переданной ошибкой. Входной снимок
    очищается только при фактическом завершении действующей попытки.

    Args:
        identifier: ID задания.
        attempt: Токен попытки, которой разрешено изменить статус.
        code: Безопасный машинный код ошибки.
        message: Публичное сообщение без приватного содержимого.
        timed_out: Нужно ли завершить задание как timed_out вместо failed.
    """
    with sync_sessions()() as db, db.begin():
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if job and job.status == "running" and job.attempt_token == attempt:
            if job.deadline_at <= utcnow():
                timed_out, code, message = True, "JOB_TIMED_OUT", "Истёк срок выполнения задания."
            job.status = "timed_out" if timed_out else "failed"
            job.error_code, job.error_message = code, message
            job.finished_at = utcnow()
            job.phase = "done"
            job.input_snapshot = {}


def heartbeat(identifier, attempt, deadline=None):
    """Подтверждает активность только незавершённой попытки в пределах deadline.

    Args:
        identifier: ID задания.
        attempt: Токен выполняющей попытки.

    Returns:
        True, если активность обновлена; False, если право на выполнение утрачено.
    """
    with sync_sessions()() as db, db.begin():
        if deadline is not None:
            remaining = (deadline - utcnow()).total_seconds()
            if remaining <= 0:
                return False
            timeout = str(max(1, min(2000, int(remaining * 1000))))
            db.execute(
                text(
                    "SELECT set_config('statement_timeout', :timeout, true), "
                    "set_config('lock_timeout', :timeout, true)"
                ),
                {"timeout": timeout},
            )
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if not job or job.status != "running" or job.attempt_token != attempt:
            return False
        if job.deadline_at <= utcnow():
            return False
        job.heartbeat_at = utcnow()
        return True


def limit_transaction(db, deadline):
    """Ограничивает оставшимся бюджетом SQL и commit публикации результата."""
    remaining = (deadline - utcnow()).total_seconds()
    if remaining <= 0:
        raise TimeoutError
    timeout = str(max(1, min(5000, int(remaining * 1000))))
    db.execute(
        text(
            "SELECT set_config('statement_timeout', :timeout, true), "
            "set_config('lock_timeout', :timeout, true)"
        ),
        {"timeout": timeout},
    )


def call_ml(identifier, attempt, kind, snapshot, deadline):
    """Однократно вызывает ML в отдельном процессе с ограниченным обменом.

    Соединение БД на время вычисления не удерживается; heartbeat использует
    короткие отдельные транзакции. Процессная группа завершается при любом
    исходе. Изоляция процесса не является песочницей для исполняемого кода.

    Args:
        identifier: ID задания, передаваемый модулю для согласования идемпотентности.
        attempt: Токен попытки для подтверждения активности.
        kind: Операция generate или revise.
        snapshot: Зафиксированные сервисом входные данные без состояния браузера.
        deadline: Общий абсолютный срок задания в UTC, включая время в очереди.

    Returns:
        Документ из протокольного ответа; проверку его схемы выполняет вызывающий код.

    Raises:
        TimeoutError: При истечении срока или потере права на выполнение.
        AppError: При ошибке процесса или известной ошибке ML с безопасным сообщением.
        ValueError: При чрезмерном выводе, неверном JSON или неизвестном коде ошибки.
        TypeError: При неверном типе данных протокола.
        KeyError: При отсутствии обязательных полей протокольного ответа.
    """
    inputs = dict(snapshot, job_id=str(identifier), deadline=deadline.isoformat())
    payload = json.dumps({"kind": kind, "inputs": inputs}, ensure_ascii=False).encode()
    parent_read, parent_write = os.pipe()
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.core.supervisor",
                deadline.isoformat(),
                str(parent_read),
                sys.executable,
                "-m",
                "app.ml.runner",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(parent_read,),
        )
    except BaseException:
        os.close(parent_write)
        raise
    finally:
        os.close(parent_read)
    try:
        stdout = exchange(
            process,
            payload,
            max_bytes=settings.max_ml_bytes + 1024,
            deadline=deadline,
            heartbeat_seconds=settings.heartbeat_seconds,
            heartbeat=lambda: heartbeat(identifier, attempt, deadline),
        )
        if process.returncode != 0:
            if deadline <= utcnow():
                raise TimeoutError
            raise AppError(502, "GENERATION_FAILED", "ML-процесс завершился с ошибкой.")
        reply = json.loads(stdout)
        if "error" in reply:
            messages = {
                "ML_UNAVAILABLE": "ML-модуль недоступен.",
                "ML_CAPABILITY_UNAVAILABLE": "ML не поддерживает эту операцию.",
                "INVALID_ML_RESPONSE": "ML вернул документ неверного формата.",
                "GENERATION_FAILED": "Ошибка выполнения ML.",
            }
            code = reply["error"]["code"]
            if code not in messages:
                raise ValueError("Unknown subprocess error")
            raise AppError(502, code, messages[code])
        return reply["document"]
    finally:
        os.close(parent_write)
        # Завершаем всю группу, включая дочерние процессы, не отделившиеся от неё.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # После чрезмерного ответа не дочитываем недоверенный stdout при очистке.
        process.stdin.close()
        process.stdout.close()
        process.wait()


def advance_phase(identifier, attempt, phase):
    """Меняет фазу только у живой попытки, не перезаписывая терминальное состояние."""
    with sync_sessions()() as db, db.begin():
        result = db.execute(
            update(Job)
            .where(
                Job.id == identifier,
                Job.status == "running",
                Job.attempt_token == attempt,
                Job.deadline_at > utcnow(),
            )
            .values(phase=phase)
        )
        return result.rowcount == 1


def publish_result(identifier, attempt, document):
    """Атомарно заменяет текущий документ и завершает действующую попытку.

    Args:
        identifier: ID задания.
        attempt: Токен попытки, результат которой публикуется.
        document: Полный документ, уже прошедший нормализацию и проверку области правки.

    Returns:
        True при успешной замене JSON, токена, исходного текста и обоих счётчиков.
        False для недействующей попытки, истёкшего срока или изменившейся базы;
        в двух последних случаях действующая попытка завершается ошибкой,
        а прежний документ сохраняется.
    """
    with sync_sessions()() as db, db.begin():
        # Избегаем взаимоблокировки, сохраняя порядок блокировок API: презентация, затем задание.
        presentation_id = db.scalar(select(Job.presentation_id).where(Job.id == identifier))
        presentation = db.scalar(
            select(Presentation).where(Presentation.id == presentation_id).with_for_update()
        )
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if job is None or job.status != "running" or job.attempt_token != attempt:
            return False
        if job.deadline_at <= utcnow():
            job.status, job.error_code = "timed_out", "JOB_TIMED_OUT"
            job.error_message = "Истёк срок выполнения задания."
            job.finished_at, job.phase = utcnow(), "done"
            job.input_snapshot = {}
            return False
        if presentation.document_token != job.base_document_token:
            job.status, job.error_code = "failed", "DOCUMENT_CONFLICT"
            job.error_message = "Текущий документ уже изменился."
            job.finished_at, job.phase = utcnow(), "done"
            job.input_snapshot = {}
            return False
        limit_transaction(db, job.deadline_at)
        presentation.document = document
        presentation.document_token = secrets.token_urlsafe(32)
        presentation.source_text = job.input_snapshot["text"]
        presentation.requested_slide_count = job.input_snapshot["slideCount"]
        presentation.slide_count = len(document["slides"])
        presentation.updated_at = utcnow()
        job.output_document_token = presentation.document_token
        job.status, job.phase, job.finished_at = "succeeded", "done", utcnow()
        job.input_snapshot = {}
        db.flush()
        # Сериализация/запись большого JSON тоже расходует бюджет. При истечении
        # откатываем всю замену, а не оставляем новый документ с ошибкой задания.
        if job.deadline_at <= utcnow():
            raise TimeoutError
        return True


@celery.task(name="pm.execute_job", throws=(TaskStateUnavailable,))
@private_task_errors
def execute_job(identifier: str):
    """Захватывает queued-задание, проверяет результат и публикует его один раз.

    Дубликаты доставки уже захваченного или завершённого задания игнорируются.
    Во время вызова ML транзакция БД не открыта. Ошибка не подменяется фикстурой
    и не запускает автоматический повтор платного вызова.

    Args:
        identifier: Строковый UUID задания; это единственный аргумент сообщения Celery.
    """
    identifier = UUID(identifier)
    with sync_sessions()() as db, db.begin():
        job = db.scalar(select(Job).where(Job.id == identifier).with_for_update())
        if not job or job.status != "queued":
            return
        if job.deadline_at <= utcnow():
            job.status, job.phase, job.finished_at = "timed_out", "done", utcnow()
            job.error_code, job.error_message = "JOB_TIMED_OUT", "Истёк срок выполнения задания."
            job.input_snapshot = {}
            return
        attempt = secrets.token_urlsafe(32)
        job.status, job.phase, job.attempt_token = "running", "ml", attempt
        job.started_at = job.heartbeat_at = utcnow()
        snapshot, kind, deadline = job.input_snapshot, job.kind, job.deadline_at
    try:
        result = call_ml(identifier, attempt, kind, snapshot, deadline)
        if not advance_phase(identifier, attempt, "validation"):
            fail_job(
                identifier,
                attempt,
                "JOB_TIMED_OUT",
                "Истёк срок выполнения задания.",
                timed_out=True,
            )
            return
        document = normalize_document(
            result, generation=kind == "generate", max_bytes=settings.max_ml_bytes
        )
        if kind == "revise":
            validate_revision(snapshot["document"], document, snapshot.get("target_slide_ids"))
        if not advance_phase(identifier, attempt, "saving"):
            fail_job(
                identifier,
                attempt,
                "JOB_TIMED_OUT",
                "Истёк срок выполнения задания.",
                timed_out=True,
            )
            return
        publish_result(identifier, attempt, document)
    except (TimeoutError, SoftTimeLimitExceeded):
        fail_job(
            identifier, attempt, "JOB_TIMED_OUT", "Истёк срок выполнения задания.", timed_out=True
        )
    except AppError as exc:
        fail_job(identifier, attempt, exc.code, exc.message)
    except (ValueError, TypeError, KeyError):
        fail_job(
            identifier, attempt, "INVALID_ML_RESPONSE", "ML вернул документ неверного формата."
        )
    except Exception as exc:
        logger.error("job_failed job_id=%s error_type=%s", identifier, type(exc).__name__)
        fail_job(identifier, attempt, "GENERATION_FAILED", "Не удалось выполнить задание.")


@celery.task(name="pm.maintenance", throws=(TaskStateUnavailable,))
@private_task_errors
def maintenance():
    """Восстанавливает доставку queued-заданий и завершает просроченные или потерянные.

    Потерянные running-задания не ставятся на повторный вызов ML. После завершения
    транзакции повторно публикуются только queued. В том же проходе удаляются
    истёкшие сессии и очищаются до 200 оставшихся снимков завершённых заданий;
    документы и метаданные для статуса и идемпотентности сохраняются.
    """
    now = utcnow()
    with sync_sessions()() as db, db.begin():
        active = db.scalars(
            select(Job).where(Job.status.in_(ACTIVE)).with_for_update(skip_locked=True)
        )
        dispatch = []
        for job in active:
            expired = job.deadline_at <= now
            lost = job.status == "running" and job.heartbeat_at < now - timedelta(
                seconds=settings.worker_lost_seconds
            )
            if expired or lost:
                job.status = "timed_out" if expired else "failed"
                job.phase, job.finished_at = "done", now
                job.error_code = "JOB_TIMED_OUT" if expired else "WORKER_LOST"
                job.error_message = (
                    "Истёк срок выполнения задания."
                    if expired
                    else ("Воркер недоступен. Повторный запуск возможен только явно.")
                )
                job.input_snapshot = {}
            elif job.status == "queued":
                dispatch.append(job.id)
        db.execute(
            delete(Session).where(
                (Session.expires_at <= now)
                | (Session.last_seen_at <= now - timedelta(hours=settings.session_idle_hours))
            )
        )
        # Старые версии могли оставить приватные снимки уже завершённых заданий.
        stale = db.scalars(
            select(Job)
            .where(Job.status.not_in(ACTIVE), Job.input_snapshot != {})
            .limit(200)
            .with_for_update(skip_locked=True)
        )
        for job in stale:
            job.input_snapshot = {}
    for identifier in dispatch:
        dispatch_job(identifier)
