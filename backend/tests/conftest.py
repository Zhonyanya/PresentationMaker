"""Общие фикстуры API с явным допуском только к отдельным тестовым зависимостям."""

import os
from pathlib import Path

import pytest

os.environ["PM_ENVIRONMENT"] = "test"
os.environ["PM_ML_ADAPTER"] = "fixture"
os.environ["PM_AUTH_REQUESTS_PER_MINUTE"] = "1000"
os.environ["PM_CSRF_REQUESTS_PER_MINUTE"] = "1000"
os.environ["PM_GLOBAL_AUTH_REQUESTS_PER_MINUTE"] = "10000"
os.environ["PM_ACCOUNT_AUTH_REQUESTS_PER_WINDOW"] = "1000"
os.environ["PM_REGISTRATIONS_PER_DAY"] = "1000"
if os.getenv("PM_TEST_DATABASE_URL"):
    os.environ["PM_DATABASE_URL"] = os.environ["PM_TEST_DATABASE_URL"]
if os.getenv("PM_TEST_REDIS_URL"):
    os.environ["PM_REDIS_URL"] = os.environ["PM_TEST_REDIS_URL"]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def document():
    import json

    return json.loads((ROOT / "backend/app/ml/fixtures/all-layouts.json").read_text())


@pytest.fixture(scope="session")
def migrated_database():
    """Применяет миграции только при явных тестовых URL PostgreSQL и Redis.

    Без обоих URL интеграционные тесты пропускаются. Имя БД обязано оканчиваться
    на _test: зависимая фикстура очищает её таблицы перед каждым тестом.
    """
    if not os.getenv("PM_TEST_DATABASE_URL") or not os.getenv("PM_TEST_REDIS_URL"):
        pytest.skip("Set PM_TEST_DATABASE_URL and PM_TEST_REDIS_URL for PostgreSQL/Redis tests")
    from sqlalchemy.engine import make_url

    if not make_url(os.environ["PM_TEST_DATABASE_URL"]).database.endswith("_test"):
        pytest.fail("Test database name must end with _test")
    from alembic.config import Config

    from alembic import command

    command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")


@pytest.fixture
def database(migrated_database):
    """Очищает проверенную тестовую БД и возвращает синхронную фабрику сессий."""
    from sqlalchemy import text

    from app.db.engine import sync_sessions

    factory = sync_sessions()
    with factory() as db, db.begin():
        db.execute(text("TRUNCATE jobs, presentations, sessions, users CASCADE"))
    return factory


@pytest.fixture
def client(database, monkeypatch):
    """Запускает API без отправки заданий в Celery.

    Yields:
        TestClient: HTTP-клиент с действующим жизненным циклом API; тесты
        сами управляют выполнением заданий и освобождением ресурсов.
    """
    from fastapi.testclient import TestClient

    from app import worker
    from app.main import create_app

    monkeypatch.setattr(worker, "dispatch_job", lambda identifier: None)
    with TestClient(create_app()) as http:
        yield http


def register(client, login="tester"):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"login": login, "password": "correct horse battery staple"},
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": token},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"], response.json()["csrf_token"]


def headers(csrf, key="test-job"):
    return {"Origin": "http://localhost:5173", "X-CSRF-Token": csrf, "Idempotency-Key": key}


def generate(client, csrf, key="test-job", **updates):
    return client.post(
        "/api/v1/presentations",
        json={"text": "Доклад " * 30, "slideCount": 8, **updates},
        headers=headers(csrf, key),
    )
