"""Аутентификация, серверные сессии и защита изменяющих запросов от CSRF."""

import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, StringConstraints
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.engine import database
from app.db.models import Session, User, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[AsyncSession, Depends(database)]
password_hash = PasswordHash.recommended()
# Фиктивный Argon2id-хеш создаётся один раз на процесс, а не на каждый неизвестный логин.
DUMMY_HASH = password_hash.hash(secrets.token_urlsafe(32))


class Credentials(BaseModel):
    """Данные входа без обрезания или нормализации пароля."""

    model_config = ConfigDict(strict=True, extra="forbid")
    login: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")]
    password: Annotated[str, StringConstraints(min_length=15, max_length=128)]


def digest(token: str) -> str:
    """Возвращает SHA-256 токена или идентификатора для хранения без исходного значения."""
    return hashlib.sha256(token.encode()).hexdigest()


async def rate_limit(
    request: Request, scope: str, limit: int, *, identity: str | None = None, seconds: int = 60
):
    """Атомарно учитывает запрос в окне Redis, общем для процессов API.

    Args:
        request: Запрос с подключением Redis и адресом клиента.
        scope: Независимая область счётчика.
        limit: Допустимое число запросов за окно.
        identity: Идентификатор счётчика; при None используется IP клиента.
        seconds: Длительность окна от первого запроса в секундах.

    Raises:
        AppError: При превышении лимита (429) или недоступности Redis (503).
    """
    # X-Forwarded-For от клиента недоверенный; доверенные прокси настраиваются в Uvicorn.
    address = request.client.host if request.client else "unknown"
    key = f"pm:rate:{scope}:{digest(address if identity is None else identity)}"
    try:
        count = await request.app.state.redis.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
            1,
            key,
            seconds,
        )
    except RedisError as exc:
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "Сервис временно недоступен.") from exc
    if count > limit:
        raise AppError(429, "RATE_LIMITED", "Слишком много запросов. Повторите позже.")


async def auth_limits(request: Request):
    """Ограничивает вход и регистрацию до открытия сессии БД.

    Заведомо отсутствующая сессия по-прежнему даёт 403 без Redis и SQL.
    Случайная cookie не позволяет обойти ранние лимиты IP и сервиса.
    """
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token or len(token) > 128:
        await csrf_guard(request, None)
    await rate_limit(request, "auth", settings.auth_requests_per_minute)
    await rate_limit(
        request, "auth-global", settings.global_auth_requests_per_minute, identity="service"
    )


async def account_auth_limits(request: Request, body: Credentials) -> Credentials:
    """Ограничивает подбор пароля к одному логину с одного адреса до SQL-поиска сессии.

    Счётчик привязан к паре «логин + IP»: если считать только по логину, любой
    посторонний мог бы десятком запросов заблокировать вход владельцу аккаунта.
    Распределённый подбор сдерживают общие лимиты по IP и сервису.
    """
    settings = get_settings()
    address = request.client.host if request.client else "unknown"
    await rate_limit(
        request,
        "auth-account",
        settings.account_auth_requests_per_window,
        identity=f"{body.login.lower()}\n{address}",
        seconds=settings.account_auth_window_seconds,
    )
    return body


AuthCredentials = Annotated[Credentials, Depends(account_auth_limits)]


async def csrf_limits(request: Request):
    """Ограничивает выдачу CSRF-токенов до SQL-поиска или создания сессии."""
    await rate_limit(request, "csrf", get_settings().csrf_requests_per_minute)


@asynccontextmanager
async def password_slot(request: Request, db: AsyncSession):
    """Освобождает соединение БД и резервирует слот дорогой проверки пароля.

    Args:
        request: Запрос с ограничителем параллелизма текущего процесса API.
        db: Сессия БД после чтения сессии пользователя; её транзакция фиксируется.

    Yields:
        None: Слот занят до выхода из контекста и освобождается даже при ошибке.

    Raises:
        AppError: Если свободных слотов нет (429); ожидание в очереди не создаётся.
    """
    await db.commit()
    limiter = request.app.state.password_limiter
    try:
        limiter.acquire_nowait()
    except anyio.WouldBlock as exc:
        raise AppError(429, "RATE_LIMITED", "Сервис входа занят. Повторите позже.") from exc
    try:
        yield
    finally:
        limiter.release()


async def current_session(request: Request, db: DB) -> Session | None:
    """Проверяет cookie и сроки сессии, обновляя активность не чаще раза в пять минут.

    Args:
        request: Запрос с сессионной cookie выбранного окружения.
        db: Сессия БД; транзакция чтения завершается до возврата найденной записи.

    Returns:
        Действующая предварительная или пользовательская сессия, иначе None.
    """
    token = request.cookies.get(get_settings().cookie_name)
    if not token or len(token) > 128:
        return None
    row = await db.scalar(select(Session).where(Session.token_hash == digest(token)))
    now = utcnow()
    settings = get_settings()
    if (
        row is None
        or row.expires_at <= now
        or row.last_seen_at <= now - timedelta(hours=settings.session_idle_hours)
    ):
        await db.commit()
        return None
    if row.last_seen_at < now - timedelta(minutes=5):
        row.last_seen_at = now
    await db.commit()
    return row


SessionDep = Annotated[Session | None, Depends(current_session)]


async def csrf_guard(request: Request, session: SessionDep) -> Session:
    """Проверяет точный Origin и synchronizer-токен серверной сессии.

    Args:
        request: Запрос с заголовками Origin и X-CSRF-Token.
        session: Текущая сессия; для входа и регистрации допустима предварительная.

    Returns:
        Сессия, прошедшая обе проверки.

    Raises:
        AppError: При недоверенном Origin, отсутствии сессии или неверном токене (403).
    """
    origin = request.headers.get("origin")
    if origin not in get_settings().allowed_origins:
        raise AppError(403, "ORIGIN_REJECTED", "Недоверенный источник запроса.")
    token = request.headers.get("x-csrf-token", "")
    if session is None or not token.isascii() or not hmac.compare_digest(token, session.csrf_token):
        raise AppError(403, "CSRF_REJECTED", "Обновите сессию и повторите запрос.")
    return session


CsrfSession = Annotated[Session, Depends(csrf_guard)]


async def user_required(session: SessionDep, db: DB) -> User:
    """Возвращает пользователя сессии либо отклоняет анонимный доступ с кодом 401."""
    if session is None or session.user_id is None:
        raise AppError(401, "AUTH_REQUIRED", "Войдите в аккаунт.")
    user = await db.get(User, session.user_id)
    if not user:
        raise AppError(401, "AUTH_REQUIRED", "Войдите в аккаунт.")
    return user


CurrentUser = Annotated[User, Depends(user_required)]


async def authenticated_csrf_guard(user: CurrentUser, session: CsrfSession) -> Session:
    """Проверяет вход до CSRF: истёкшая или отозванная сессия должна давать 401.

    Порядок зависимостей существенен: действующая пользовательская сессия затем
    проходит обычные проверки Origin и CSRF, ошибки которых возвращают 403.
    """
    return session


AuthenticatedCsrfSession = Annotated[Session, Depends(authenticated_csrf_guard)]


def public_user(user: User):
    return {"id": str(user.id), "login": user.login}


async def new_session(db: AsyncSession, response: Response, user_id=None) -> Session:
    """Создаёт сессию и устанавливает cookie, не фиксируя транзакцию.

    Args:
        db: Сессия БД для добавления записи; commit выполняет вызывающий код.
        response: Ответ для установки HttpOnly-cookie и запрета кеширования.
        user_id: ID пользователя; None создаёт короткую предварительную сессию.

    Returns:
        Запись сессии с CSRF-токеном. Исходный сессионный токен передаётся
        только в cookie; в БД сохраняется его хеш.
    """
    settings = get_settings()
    now = utcnow()
    ttl = (
        timedelta(days=settings.session_days)
        if user_id
        else timedelta(minutes=settings.pre_session_minutes)
    )
    token = secrets.token_urlsafe(32)
    row = Session(
        token_hash=digest(token),
        user_id=user_id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + ttl,
    )
    db.add(row)
    await db.flush()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.secure_cookie,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return row


@router.get("/csrf", dependencies=[Depends(csrf_limits)])
async def csrf(request: Request, response: Response, db: DB, session: SessionDep):
    """Выдаёт CSRF-токен, при необходимости создавая предварительную сессию."""
    if session is None:
        session = await new_session(db, response)
        await db.commit()
    return {"csrf_token": session.csrf_token}


async def rotate_session(db: AsyncSession, response: Response, old: Session, user: User):
    """Однократно заменяет прежнюю сессию после успешного входа или регистрации.

    Args:
        db: Сессия БД; изменения пользователя и ротация фиксируются вместе.
        response: Ответ для установки новой сессионной cookie.
        old: Предварительная или пользовательская сессия, которую нужно отозвать.
        user: Пользователь новой сессии.

    Returns:
        Публичные данные пользователя и новый CSRF-токен без токена входа.

    Raises:
        AppError: Если прежняя сессия уже удалена, в том числе параллельным запросом (403).
    """
    removed = await db.execute(delete(Session).where(Session.id == old.id).returning(Session.id))
    if removed.scalar_one_or_none() is None:
        raise AppError(403, "CSRF_REJECTED", "Обновите сессию и повторите запрос.")
    row = await new_session(db, response, user.id)
    await db.commit()
    return {"user": public_user(user), "csrf_token": row.csrf_token}


@router.post("/register", status_code=201, dependencies=[Depends(auth_limits)])
async def register(
    body: AuthCredentials, request: Request, response: Response, db: DB, old: CsrfSession
):
    """Регистрирует пользователя с учётом допуска и квот, затем заменяет сессию.

    Argon2id вычисляется в потоке без удержания соединения БД. Проверка общей
    квоты аккаунтов и создание пользователя сериализованы между процессами API.
    """
    settings = get_settings()
    if not settings.registration_open:
        raise AppError(403, "HTTP_ERROR", "Самостоятельная регистрация отключена.")
    async with password_slot(request, db):
        await rate_limit(
            request,
            "register-global",
            settings.registrations_per_day,
            identity="service",
            seconds=86400,
        )
        hashed = await anyio.to_thread.run_sync(
            password_hash.hash, body.password, limiter=request.app.state.password_thread_limiter
        )
        await db.execute(text("SELECT pg_advisory_xact_lock(81273002)"))
        if await db.scalar(select(func.count()).select_from(User)) >= settings.max_users:
            raise AppError(429, "RATE_LIMITED", "Регистрация временно недоступна.")
        user = User(login=body.login, login_normalized=body.login.lower(), password_hash=hashed)
        db.add(user)
        try:
            await db.flush()
            return await rotate_session(db, response, old, user)
        except IntegrityError as exc:
            await db.rollback()
            raise AppError(409, "LOGIN_UNAVAILABLE", "Этот логин недоступен.") from exc


@router.post("/login", dependencies=[Depends(auth_limits)])
async def login(
    body: AuthCredentials, request: Request, response: Response, db: DB, old: CsrfSession
):
    """Проверяет пароль вне цикла событий, обновляет хеш и заменяет сессию.

    Неизвестный логин проходит проверку фиктивного хеша и получает ту же ошибку,
    что и неверный пароль; изменение хеша за время проверки также отклоняет вход.
    """
    async with password_slot(request, db):
        saved = (
            await db.execute(
                select(User.id, User.password_hash).where(
                    User.login_normalized == body.login.lower()
                )
            )
        ).one_or_none()
        await db.commit()
        valid, updated = await anyio.to_thread.run_sync(
            password_hash.verify_and_update,
            body.password,
            saved.password_hash if saved else DUMMY_HASH,
            limiter=request.app.state.password_thread_limiter,
        )
        if not saved or not valid:
            raise AppError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.")
        user = await db.get(User, saved.id, populate_existing=True)
        if user is None or user.password_hash != saved.password_hash:
            raise AppError(401, "INVALID_CREDENTIALS", "Неверный логин или пароль.")
        if updated:
            user.password_hash = updated
        return await rotate_session(db, response, old, user)


@router.post("/logout", status_code=204)
async def logout(response: Response, db: DB, session: AuthenticatedCsrfSession):
    """Отзывает только текущую сессию и удаляет cookie, не отменяя задания пользователя."""
    await db.execute(delete(Session).where(Session.id == session.id))
    await db.commit()
    response.delete_cookie(
        get_settings().cookie_name,
        path="/",
        secure=get_settings().secure_cookie,
        httponly=True,
        samesite="lax",
    )


@router.get("/me")
async def me(user: CurrentUser):
    return {"user": public_user(user)}
