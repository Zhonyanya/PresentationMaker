"""Раздельные фабрики сессий БД для асинхронного API и синхронного воркера."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


def connection_options():
    """Ограничивает сетевые/SQL-ожидания и не раскрывает параметры в исключениях."""
    return {
        "pool_pre_ping": True,
        "pool_timeout": 2,
        "hide_parameters": True,
        "connect_args": {
            "connect_timeout": 2,
            "tcp_user_timeout": 5000,
            "options": "-c statement_timeout=5000 -c lock_timeout=2000",
        },
    }


@lru_cache
def async_sessions():
    """Лениво создаёт фабрику API; ORM-объекты не истекают после commit."""
    engine = create_async_engine(get_settings().database_url, pool_size=5, **connection_options())
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def sync_sessions():
    """Лениво создаёт фабрику воркера с отдельным пулом соединений.

    Вызывать только в дочернем процессе Celery: engine и его соединения нельзя
    создавать в родителе и наследовать через fork.
    """
    engine = create_engine(get_settings().database_url, pool_size=2, **connection_options())
    return sessionmaker(engine, expire_on_commit=False)


async def database():
    """Предоставляет сессию запроса без автоматического commit.

    Yields:
        AsyncSession: Сессия, закрываемая после запроса; незавершённая транзакция
        откатывается при закрытии. Фиксацией управляют предметные сервисы.
    """
    async with async_sessions()() as session:
        yield session
