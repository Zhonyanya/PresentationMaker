"""HTTP-доступ к текущему документу, фоновым изменениям и статусу задания."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select

from app.auth.service import DB, CurrentUser, authenticated_csrf_guard
from app.core.errors import AppError
from app.db.models import Job, Presentation
from app.jobs.service import ACTIVE, accepted, submit
from app.presentations.schemas import GenerateRequest, RegenerateRequest, ReviseRequest

router = APIRouter(tags=["presentations"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


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


@router.post("/presentations", status_code=202, dependencies=[Depends(authenticated_csrf_guard)])
async def generate(body: GenerateRequest, user: CurrentUser, db: DB, key: Key):
    """Принимает первую генерацию, возвращая задание, а не готовый документ."""
    return await enqueue(db, user, key, body)


@router.post(
    "/presentations/{identifier}/generations",
    status_code=202,
    dependencies=[Depends(authenticated_csrf_guard)],
)
async def regenerate(
    identifier: UUID, body: RegenerateRequest, user: CurrentUser, db: DB, key: Key
):
    """Принимает полную перегенерацию; при существующем документе нужен его актуальный токен."""
    return await enqueue(db, user, key, body, identifier)


@router.post(
    "/presentations/{identifier}/revisions",
    status_code=202,
    dependencies=[Depends(authenticated_csrf_guard)],
)
async def revise(identifier: UUID, body: ReviseRequest, user: CurrentUser, db: DB, key: Key):
    """Принимает командную правку серверного снимка, не изменяя текущий документ сразу."""
    return await enqueue(db, user, key, body, identifier)


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
            .where(Presentation.id == identifier, Presentation.owner_id == user.id)
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
