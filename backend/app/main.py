"""Сборка ASGI-приложения, безопасные HTTP-ошибки и ограничения входящих запросов."""

import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth.service import router as auth_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.readiness import ModuleReadiness
from app.db.engine import async_sessions
from app.presentations.routes import router as presentation_router

logger = logging.getLogger(__name__)
READY_CACHE_SECONDS = 2


def error_response(request: Request, status: int, code: str, message: str):
    """Формирует общий формат ошибки с request_id и запретом кеширования.

    Args:
        request: Запрос с необязательным request_id в состоянии.
        status: HTTP-статус ошибки.
        code: Стабильный машинный код.
        message: Безопасное сообщение без приватного ввода или текста внутренних исключений.

    Returns:
        JSONResponse с объектом error и request_id на верхнем уровне.
    """
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message},
            "request_id": getattr(request.state, "request_id", None),
        },
        headers={"Cache-Control": "no-store"},
    )


def create_app():
    """Собирает API и защитные оболочки с отдельными ресурсами жизненного цикла.

    Returns:
        ASGI-приложение с внешним CORS, проверкой Host в production и ограничением
        тела запроса перед маршрутизацией FastAPI.
    """
    settings = get_settings()
    ml_readiness = ModuleReadiness(settings.ml_module)

    @asynccontextmanager
    async def lifespan(app):
        """Создаёт Redis и ограничители API, освобождая соединения при остановке."""
        app.state.redis = Redis.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        app.state.password_limiter = anyio.CapacityLimiter(settings.password_concurrency)
        app.state.password_thread_limiter = anyio.CapacityLimiter(settings.password_concurrency)
        yield
        await app.state.redis.aclose()
        factory = async_sessions()
        await factory.kw["bind"].dispose()

    # Схема API в production не публикуется: она не нужна пользователям и упрощает разведку
    docs = settings.environment != "production"
    app = FastAPI(
        title="PresentationMaker API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.ready_checked = (0.0, None)

    @app.middleware("http")
    async def metadata(request: Request, call_next):
        """Добавляет request_id и защитные заголовки, не записывая приватный ввод в логи."""
        request.state.request_id = secrets.token_hex(12)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed request_id=%s error_type=%s",
                request.state.request_id,
                type(exc).__name__,
            )
            response = error_response(request, 500, "INTERNAL_ERROR", "Внутренняя ошибка сервера.")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        if settings.secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        logger.info(
            "request request_id=%s method=%s status=%s elapsed=%.3f",
            request.state.request_id,
            request.method,
            response.status_code,
            time.monotonic() - started,
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Стандартные ошибки Pydantic содержат приватный ввод; не возвращаем их клиенту.
        return error_response(
            request, 422, "VALIDATION_ERROR", "Проверьте поля и ограничения запроса."
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_busy(request, exc):
        # Таймауты запросов и блокировок, исчерпание пула — временная перегрузка, а не дефект
        logger.warning(
            "database_busy request_id=%s error_type=%s",
            request.state.request_id,
            type(exc).__name__,
        )
        response = error_response(
            request, 503, "SERVICE_BUSY", "Сервис перегружен. Повторите через несколько секунд."
        )
        response.headers["Retry-After"] = "5"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(
            request, exc.status_code, "HTTP_ERROR", "Запрос не может быть выполнен."
        )

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(presentation_router, prefix="/api/v1")

    @app.get("/api/v1/health/live")
    async def live():
        """Подтверждает работу HTTP-процесса независимо от внешних зависимостей."""
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    async def ready(request: Request):
        """Проверяет БД, Redis и интерфейс ML без запуска генерации в API-процессе.

        Результат кешируется на READY_CACHE_SECONDS: адрес доступен без входа, и поток
        запросов к нему иначе превращался бы в поток запросов к БД.
        """
        checked_at, result = request.app.state.ready_checked
        if time.monotonic() - checked_at < READY_CACHE_SECONDS and result is not None:
            if result is False:
                raise AppError(503, "NOT_READY", "Обязательные зависимости недоступны.")
            return result
        try:
            result = await check_ready(request)
        except AppError:
            request.app.state.ready_checked = (time.monotonic(), False)
            raise
        request.app.state.ready_checked = (time.monotonic(), result)
        return result

    async def check_ready(request: Request):
        try:
            async with async_sessions()() as db:
                await db.execute(text("SELECT 1 FROM users LIMIT 1"))
                await db.execute(text("SELECT 1 FROM jobs LIMIT 1"))
            await request.app.state.redis.ping()
            if settings.ml_adapter == "module" and not await ml_readiness.is_ready():
                raise AppError(503, "NOT_READY", "Обязательные зависимости недоступны.")
        except Exception as exc:
            raise AppError(503, "NOT_READY", "Обязательные зависимости недоступны.") from exc
        return {"status": "ok", "ml_adapter": settings.ml_adapter}

    # Внешний CORS добавляет заголовки и к ошибкам, возникшим до маршрутизации.
    wrapped = BodyLimitMiddleware(
        app,
        settings.max_http_bytes,
        timeout=settings.http_body_timeout_seconds,
        max_readers=settings.max_http_body_readers,
    )
    if settings.environment == "production":
        hosts = settings.allowed_hosts or [
            urlsplit(origin).hostname for origin in settings.allowed_origins
        ]
        wrapped = TrustedHostMiddleware(wrapped, allowed_hosts=hosts, www_redirect=False)
    return CORSMiddleware(
        wrapped,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )


class BodyLimitMiddleware:
    """Ограничивает объём и время чтения, удерживая admission до конца запроса.

    Args:
        app: Вложенное ASGI-приложение.
        limit: Максимальный размер тела в байтах независимо от Content-Length.
        timeout: Общий срок чтения тела в секундах, а не таймаут отдельного фрагмента.
        max_readers: Максимальное число принятых HTTP-запросов в этом процессе.
    """

    def __init__(self, app, limit, *, timeout=30, max_readers=100):
        self.app, self.limit = app, limit
        self.timeout = timeout
        self.readers = anyio.CapacityLimiter(max_readers)

    async def __call__(self, scope, receive, send):
        """Буферизует допустимое HTTP-тело и передаёт его вложенному приложению.

        Нехватка слотов, превышение размера и срока дают 503, 413 и 408
        соответственно. Не-HTTP-события передаются без ограничений этой оболочки.
        """
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def reject(status, code, message):
            request_id = secrets.token_hex(12)
            headers = {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Request-ID": request_id,
            }
            if scope.get("http_version") in {"1.0", "1.1"}:
                headers["Connection"] = "close"
            response = JSONResponse(
                status_code=status,
                content={"error": {"code": code, "message": message}, "request_id": request_id},
                headers=headers,
            )
            await response(scope, receive, send)

        try:
            self.readers.acquire_nowait()
        except anyio.WouldBlock:
            return await reject(503, "HTTP_ERROR", "Сервис занят. Повторите позже.")
        body = bytearray()
        too_large = False
        try:
            try:
                with anyio.fail_after(self.timeout):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > self.limit:
                            too_large = True
                            break
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                body = message = chunk = None
                return await reject(408, "HTTP_ERROR", "Истёк срок загрузки запроса.")
            # Не удерживаем последний входящий фрагмент во время обработки/отказа.
            message = chunk = None
            if too_large:
                body = None
                return await reject(413, "REQUEST_TOO_LARGE", "Слишком большой запрос.")

            async def replay():
                """Передаёт тело однократно, сразу освобождая принадлежащий нам буфер."""
                nonlocal body
                if body is not None:
                    message = {"type": "http.request", "body": bytes(body), "more_body": False}
                    body = None
                    return message
                return await receive()

            await self.app(scope, replay, send)
        finally:
            body = message = chunk = None
            self.readers.release()


app = create_app()
