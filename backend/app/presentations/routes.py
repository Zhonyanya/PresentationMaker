"""HTTP-доступ к текущему документу, фоновым изменениям и статусу задания."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select

from app.auth.service import DB, CurrentUser, authenticated_csrf_guard, rate_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, Presentation, utcnow
from app.jobs.service import ACTIVE, accepted, owned_presentation, submit
from app.presentations.schemas import GenerateRequest, RegenerateRequest, ReviseRequest

router = APIRouter(tags=["presentations"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


async def write_limits(request: Request, user: CurrentUser):
    """Ограничивает частоту генераций и правок одного пользователя до транзакции приёма.

    Квоты заданий считаются в PostgreSQL под общей блокировкой; без этого лимита
    поток запросов с новыми ключами идемпотентности нагружал бы её впустую.
    """
    await rate_limit(
        request, "write", get_settings().write_requests_per_minute, identity=str(user.id)
    )


WRITE = [Depends(authenticated_csrf_guard), Depends(write_limits)]


async def enqueue(db, user, key, body, identifier=None):
    """Фиксирует задание и пытается отправить его в очередь после commit.

    Args:
        db: Сессия БД запроса.
        user: Аутентифицированный владелец презентации.
        key: Ключ идемпотентности запроса.
        body: Проверенное тело генерации или правки.
        identifier: ID существующей презентации либо None для новой.

    Returns:
        ID презентации, ID задания и URL статуса для ответа 202.
        Сбой отправки в Redis не отменяет приём: доставку восстановит Beat.

    Raises:
        AppError: Если сервис отклонил приём задания.
    """
    job = await submit(db, user.id, key, body, identifier)
    import anyio

    from app.worker import dispatch_job

    await anyio.to_thread.run_sync(dispatch_job, job.id)
    return accepted(job)


@router.post("/presentations", status_code=202, dependencies=WRITE)
async def generate(body: GenerateRequest, user: CurrentUser, db: DB, key: Key):
    """Принимает первую генерацию, возвращая задание, а не готовый документ."""
    return await enqueue(db, user, key, body)


@router.post(
    "/presentations/{identifier}/generations",
    status_code=202,
    dependencies=WRITE,
)
async def regenerate(
    identifier: UUID, body: RegenerateRequest, user: CurrentUser, db: DB, key: Key
):
    """Принимает полную перегенерацию; при существующем документе нужен его актуальный токен."""
    return await enqueue(db, user, key, body, identifier)


@router.post(
    "/presentations/{identifier}/revisions",
    status_code=202,
    dependencies=WRITE,
)
async def revise(identifier: UUID, body: ReviseRequest, user: CurrentUser, db: DB, key: Key):
    """Принимает командную правку серверного снимка, не изменяя текущий документ сразу."""
    return await enqueue(db, user, key, body, identifier)


@router.get("/presentations")
async def presentations(user: CurrentUser, db: DB):
    """Список презентаций владельца без исходных текстов и содержимого слайдов.

    Квота ограничивает их число сотней на пользователя, поэтому ответ без пагинации.
    """
    rows = (
        await db.execute(
            select(Presentation, Job.id)
            .outerjoin(
                Job,
                (Job.presentation_id == Presentation.id) & Job.status.in_(ACTIVE),
            )
            .where(Presentation.owner_id == user.id, Presentation.deleted_at.is_(None))
            .order_by(Presentation.updated_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "presentations": [
            {
                "presentation_id": str(presentation.id),
                "title": presentation.document["title"] if presentation.document else None,
                "slide_count": presentation.slide_count,
                "updated_at": presentation.updated_at.isoformat(),
                "active": active is not None,
            }
            for presentation, active in rows
        ]
    }


@router.delete(
    "/presentations/{identifier}",
    status_code=204,
    dependencies=[Depends(authenticated_csrf_guard)],
)
async def delete_presentation(identifier: UUID, user: CurrentUser, db: DB):
    """Безвозвратно стирает исходный текст и документ; удалённая презентация даёт 404.

    Пустая строка остаётся для учёта квот заданий, иначе удаление обнуляло бы
    суточный лимит генераций. Пока идёт задание, удаление отклоняется (409).
    """
    presentation = await owned_presentation(db, user.id, identifier, lock=True)
    if await db.scalar(
        select(Job.id).where(Job.presentation_id == identifier, Job.status.in_(ACTIVE))
    ):
        raise AppError(409, "JOB_ALREADY_ACTIVE", "Дождитесь завершения задания.")
    presentation.source_text = ""
    presentation.document = presentation.document_token = presentation.slide_count = None
    presentation.deleted_at = presentation.updated_at = utcnow()
    await db.commit()


@router.get("/presentations/{identifier}")
async def current(identifier: UUID, user: CurrentUser, db: DB):
    """Возвращает текущий документ и активное задание из одного снимка БД.

    До первой успешной генерации документ, его токен и фактическое число слайдов
    равны null. Чужая или отсутствующая презентация возвращает 404.
    """
    # Два SELECT при READ COMMITTED могли бы смешать старый документ с завершённым заданием.
    row = (
        await db.execute(
            select(Presentation, Job)
            .outerjoin(
                Job,
                (Job.presentation_id == Presentation.id) & Job.status.in_(ACTIVE),
            )
            .where(
                Presentation.id == identifier,
                Presentation.owner_id == user.id,
                Presentation.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise AppError(404, "NOT_FOUND", "Презентация не найдена.")
    presentation, active = row
    return {
        "presentation_id": str(presentation.id),
        "document": presentation.document,
        "document_token": presentation.document_token,
        "requested_slide_count": presentation.requested_slide_count,
        "slide_count": presentation.slide_count,
        "active_job": accepted(active) if active else None,
    }


@router.get("/jobs/{identifier}")
async def status(identifier: UUID, user: CurrentUser, db: DB):
    """Возвращает статус задания владельца без входного снимка и архивного результата.

    output_document_token успешного задания может уже отличаться от токена
    текущей презентации. Чужое или отсутствующее задание возвращает 404.
    """
    job = await db.scalar(select(Job).where(Job.id == identifier, Job.owner_id == user.id))
    if job is None:
        raise AppError(404, "NOT_FOUND", "Задание не найдено.")
    return {
        "job_id": str(job.id),
        "presentation_id": str(job.presentation_id),
        "status": job.status,
        "phase": job.phase,
        "output_document_token": job.output_document_token,
        "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
    }
