from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import anyio
import pytest
from conftest import generate, headers, register
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from test_api import execute, read

from app import worker
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job, Presentation, Session, User, utcnow
from app.jobs.service import submit
from app.presentations.schemas import GenerateRequest


@pytest.mark.parametrize("key", ["", " ", "a b", "\t", "line\nbreak", "\x7f", "ключ", "a" * 129])
def test_invalid_idempotency_key_is_rejected_before_database_access(key):
    db = Mock()
    body = GenerateRequest(text="x" * 100, slideCount=3)
    with pytest.raises(AppError) as exc:
        anyio.run(submit, db, uuid4(), key, body)
    assert (exc.value.status, exc.value.code) == (422, "INVALID_IDEMPOTENCY_KEY")
    assert not db.mock_calls


@pytest.mark.parametrize("route", ["generations", "revisions"])
def test_foreign_presentations_cannot_be_modified(client, database, route):
    _, token = register(client, "first")
    accepted = generate(client, token).json()
    execute(client, accepted)
    before = read(client, accepted)
    _, other_token = register(client, "second")
    body = (
        {"text": "New report " * 20, "slideCount": 5}
        if route == "generations"
        else {"instruction": "Change", "base_document_token": before["document_token"]}
    )
    response = client.post(
        f"/api/v1/presentations/{accepted['presentation_id']}/{route}",
        json=body, headers=headers(other_token, "foreign-write"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        saved = db.get(Presentation, UUID(accepted["presentation_id"]))
        assert saved.document == before["document"]


def test_idempotency_key_is_scoped_to_user(client):
    _, first_token = register(client, "first")
    first = generate(client, first_token, "shared-key")
    _, second_token = register(client, "second")
    second = generate(client, second_token, "shared-key")
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] != second.json()["job_id"]
    assert first.json()["presentation_id"] != second.json()["presentation_id"]


@pytest.mark.parametrize("change", ["operation", "target"])
def test_idempotency_key_cannot_be_reused_for_other_operation_or_target(client, database, change):
    _, token = register(client)
    first = generate(client, token, "first").json()
    execute(client, first)
    if change == "operation":
        path = f"/api/v1/presentations/{first['presentation_id']}/revisions"
        body = {
            "instruction": "Change", "base_document_token": read(client, first)["document_token"]
        }
        key = "first"
        expected_count = 1
    else:
        second = generate(client, token, "second").json()
        execute(client, second)
        path = f"/api/v1/presentations/{second['presentation_id']}/generations"
        body = {"text": "Доклад " * 30, "slideCount": 8}
        # Меняется только целевая презентация: операция и тело запроса те же.
        key = "first"
        expected_count = 2
    response = client.post(path, json=body, headers=headers(token, key))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == expected_count


def test_revision_before_first_document_and_stale_regeneration_create_no_job(client, database):
    _, token = register(client)
    accepted = generate(client, token).json()
    with database() as db, db.begin():
        job = db.get(Job, UUID(accepted["job_id"]))
        job.status, job.phase, job.input_snapshot = "failed", "done", {}
    path = f"/api/v1/presentations/{accepted['presentation_id']}"
    response = client.post(
        path + "/revisions", json={"instruction": "Change", "base_document_token": "unknown"},
        headers=headers(token, "not-ready"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_READY"
    response = client.post(
        path + "/generations",
        json={"text": "New report " * 20, "slideCount": 5, "base_document_token": "stale"},
        headers=headers(token, "stale"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_CONFLICT"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_global_active_limit_includes_other_users(client, database, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_active_jobs", 1)
    _, token = register(client, "first")
    assert generate(client, token).status_code == 202
    _, other_token = register(client, "second")
    response = generate(client, other_token)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_JOB_LIMIT"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(Presentation)) == 1


def test_logout_does_not_cancel_accepted_job(client, database, monkeypatch, document):
    _, token = register(client)
    accepted = generate(client, token).json()
    assert client.post("/api/v1/auth/logout", headers=headers(token)).status_code == 204
    monkeypatch.setattr(worker, "call_ml", lambda *args: document)
    worker.execute_job.run(accepted["job_id"])
    assert client.get(accepted["status_url"]).status_code == 401
    with database() as db:
        assert db.get(Job, UUID(accepted["job_id"])).status == "succeeded"


def test_absolute_session_expiry_and_maintenance_cleanup(client, database):
    register(client)
    now = utcnow()
    with database() as db, db.begin():
        session = db.scalar(select(Session).where(Session.user_id.is_not(None)))
        session.expires_at = now - timedelta(seconds=1)
        session.last_seen_at = now
    assert client.get("/api/v1/auth/me").status_code == 401
    client.get("/api/v1/auth/csrf")
    with database() as db, db.begin():
        db.add(Session(
            token_hash="unused-test-token", csrf_token="unused", created_at=now,
            expires_at=now + timedelta(days=1), last_seen_at=now - timedelta(hours=25),
        ))
    worker.maintenance.run()
    with database() as db:
        remaining = list(db.scalars(select(Session)))
        assert len(remaining) == 1 and remaining[0].user_id is None
        assert remaining[0].expires_at > now
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_duplicate_registration_is_case_insensitive_and_keeps_session(client, database):
    user, token = register(client, "Example")
    cookie = client.cookies.get("pm-dev-session")
    response = client.post(
        "/api/v1/auth/register",
        json={"login": "EXAMPLE", "password": "another sufficiently long password"},
        headers=headers(token),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOGIN_UNAVAILABLE"
    assert client.cookies.get("pm-dev-session") == cookie
    assert client.get("/api/v1/auth/me").json()["user"] == user
    with database() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_existing_csrf_session_is_reused_and_old_csrf_cannot_logout_rotated_session(client):
    old_token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    cookie = client.cookies.get("pm-dev-session")
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == old_token
    assert client.cookies.get("pm-dev-session") == cookie
    _, token = register(client)
    response = client.post("/api/v1/auth/logout", headers=headers(old_token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers(token)).status_code == 204


@pytest.mark.parametrize("dependency", ["healthy", "redis", "ml"])
def test_health_readiness_and_liveness(client, monkeypatch, dependency):
    if dependency == "redis":
        async def unavailable(*args, **kwargs):
            raise RedisConnectionError("private dependency URL")

        monkeypatch.setattr(Redis, "ping", unavailable)
    elif dependency == "ml":
        monkeypatch.setattr(get_settings(), "ml_adapter", "module")
        monkeypatch.setattr(get_settings(), "ml_module", "_pm_nonexistent_test_ml_module")
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    response = client.get("/api/v1/health/ready")
    assert response.status_code == (200 if dependency == "healthy" else 503)
    if dependency == "healthy":
        assert response.json() == {"status": "ok", "ml_adapter": "fixture"}
    else:
        assert response.json()["error"]["code"] == "NOT_READY"
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert "private" not in response.text
