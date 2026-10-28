"""Приём заданий со снимком входа, квотами и защитой от повторных изменений."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, Presentation, utcnow
from app.presentations.schemas import GenerateRequest, ReviseRequest

ACTIVE = ("queued", "running")


async def owned_presentation(db: AsyncSession, owner: UUID, identifier: UUID, *, lock=False):
    """Загружает презентацию владельца, не раскрывая существование чужих объектов.

    Args:
        db: Сессия текущей транзакции.
        owner: ID пользователя, которому должна принадлежать презентация.
        identifier: ID презентации.
        lock: Нужно ли удерживать блокировку строки до завершения транзакции.

    Returns:
        Презентация указанного владельца.

    Raises:
        AppError: Если презентации нет или она принадлежит другому пользователю (404).
    """
    query = select(Presentation).where(
        Presentation.id == identifier, Presentation.owner_id == owner
    )
    if lock:
        query = query.with_for_update()
    presentation = await db.scalar(query)
    if presentation is None:
        raise AppError(404, "NOT_FOUND", "Презентация не найдена.")
    return presentation


def accepted(job: Job):
    """Формирует ссылки принятого задания без документа и приватного входного снимка."""
    return {
        "presentation_id": str(job.presentation_id),
        "job_id": str(job.id),
        "status_url": f"/api/v1/jobs/{job.id}",
    }


async def submit(db: AsyncSession, owner: UUID, key: str, body, identifier: UUID | None = None):
    """Фиксирует новое задание либо возвращает ранее принятое по тому же ключу.

    Совпадающий повтор распознаётся до проверок занятости, актуальности и квот.
    Приём сериализован между процессами API; вызов ML и отправка в Redis здесь
    не выполняются. Новая презентация и её первое задание создаются атомарно.

    Args:
        db: Сессия БД; успешный приём или повтор завершается commit.
        owner: ID аутентифицированного владельца.
        key: Ключ идемпотентности, уникальный в пределах владельца.
        body: Проверенный GenerateRequest, RegenerateRequest или ReviseRequest.
        identifier: ID существующей презентации; None для первой генерации.

    Returns:
        Новое либо ранее принятое задание со снимком входа и общим сроком выполнения.

    Raises:
        AppError: При неверном ключе или целях (422), отсутствии доступа (404),
            конфликте ключа, текущего документа или активного задания (409),
            превышении пользовательских (429) либо общих (503) квот.
    """
    if not key or len(key) > 128 or not key.isascii() or not all(33 <= ord(c) <= 126 for c in key):
        raise AppError(
            422, "INVALID_IDEMPOTENCY_KEY", "Нужен Idempotency-Key (1–128 ASCII-символов)."
        )
    operation = "revise" if isinstance(body, ReviseRequest) else "generate"
    payload = body.model_dump(exclude_none=True)
    canonical = {
        "operation": operation,
        "target": str(identifier) if identifier else None,
        "body": payload,
    }
    request_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    await db.execute(text("SELECT pg_advisory_xact_lock(81273001)"))
    previous = await db.scalar(select(Job).where(Job.owner_id == owner, Job.idempotency_key == key))
    if previous:
        if previous.request_hash != request_hash:
            raise AppError(409, "IDEMPOTENCY_CONFLICT", "Ключ уже использован для другого запроса.")
        await db.commit()
        return previous
    presentation = None
    if identifier:
        presentation = await owned_presentation(db, owner, identifier, lock=True)
        if await db.scalar(
            select(Job.id).where(Job.presentation_id == identifier, Job.status.in_(ACTIVE))
        ):
            raise AppError(409, "JOB_ALREADY_ACTIVE", "Презентация уже обрабатывается.")
        if isinstance(body, ReviseRequest) and presentation.document is None:
            raise AppError(409, "DOCUMENT_NOT_READY", "Сначала создайте презентацию.")
        if presentation.document_token != getattr(body, "base_document_token", None):
            raise AppError(409, "DOCUMENT_CONFLICT", "Презентация обновилась. Загрузите текущую.")
    settings = get_settings()
    user_count = await db.scalar(
        select(func.count()).select_from(Job).where(Job.owner_id == owner, Job.status.in_(ACTIVE))
    )
    if user_count >= settings.max_active_per_user:
        raise AppError(429, "USER_JOB_LIMIT", "Дождитесь завершения текущих задач.")
    total = await db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE)))
    if total >= settings.max_active_jobs:
        raise AppError(503, "SERVICE_JOB_LIMIT", "Очередь заполнена. Попробуйте позже.")
    # Ошибки и таймауты расходуют бюджет приёма; идемпотентные повторы выше — нет.
    since = utcnow() - timedelta(days=1)
    daily_user = await db.scalar(
        select(func.count()).select_from(Job).where(Job.owner_id == owner, Job.created_at >= since)
    )
    user_jobs = await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == owner))
    if daily_user >= settings.max_daily_jobs_per_user or user_jobs >= settings.max_jobs_per_user:
        raise AppError(429, "USER_JOB_LIMIT", "Достигнут лимит заданий пользователя.")
    daily_total = await db.scalar(
        select(func.count()).select_from(Job).where(Job.created_at >= since)
    )
    total_jobs = await db.scalar(select(func.count()).select_from(Job))
    if daily_total >= settings.max_daily_jobs or total_jobs >= settings.max_jobs:
        raise AppError(503, "SERVICE_JOB_LIMIT", "Достигнут лимит заданий сервиса.")
    if presentation is None:
        user_presentations = await db.scalar(
            select(func.count()).select_from(Presentation).where(Presentation.owner_id == owner)
        )
        if user_presentations >= settings.max_presentations_per_user:
            raise AppError(429, "USER_JOB_LIMIT", "Достигнут лимит презентаций пользователя.")
        total_presentations = await db.scalar(select(func.count()).select_from(Presentation))
        if total_presentations >= settings.max_presentations:
            raise AppError(503, "SERVICE_JOB_LIMIT", "Достигнут лимит презентаций сервиса.")
    if isinstance(body, ReviseRequest):
        if presentation is None or presentation.document is None:
            raise AppError(409, "DOCUMENT_NOT_READY", "Сначала создайте презентацию.")
        targets = body.target_slide_numbers
        if targets and max(targets) > presentation.slide_count:
            raise AppError(422, "INVALID_TARGET_SLIDES", "Номер слайда вне текущей презентации.")
        snapshot = {
            "document": presentation.document,
            "text": presentation.source_text,
            "slideCount": presentation.requested_slide_count,
            "instruction": body.instruction,
            "target_slide_numbers": targets,
            "target_slide_ids": [presentation.document["slides"][n - 1]["id"] for n in targets]
            if targets
            else None,
        }
    else:
        snapshot = GenerateRequest.model_validate(payload).model_dump(exclude_none=True)
    if presentation is None:
        presentation = Presentation(
            owner_id=owner, source_text=body.text, requested_slide_count=body.slideCount
        )
        db.add(presentation)
        await db.flush()
    job = Job(
        owner_id=owner,
        presentation_id=presentation.id,
        kind=operation,
        base_document_token=presentation.document_token,
        input_snapshot=snapshot,
        idempotency_key=key,
        request_hash=request_hash,
        deadline_at=utcnow() + timedelta(seconds=settings.job_deadline_seconds),
    )
    db.add(job)
    await db.commit()
    return job
