import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from conftest import generate, headers, register
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select, text
from test_api import execute, read
from test_security import production_settings

from app import worker
from app.auth.service import password_hash
from app.core.config import get_settings
from app.db.models import Job, Presentation, Session, utcnow
from app.main import create_app


@pytest.mark.parametrize(
    ("setting", "status"),
    [
        ("max_daily_jobs_per_user", 429),
        ("max_daily_jobs", 503),
        ("max_jobs_per_user", 429),
        ("max_jobs", 503),
        ("max_presentations_per_user", 429),
        ("max_presentations", 503),
    ],
)
def test_cumulative_limits_include_completed_work_and_preserve_replay(
    client, database, monkeypatch, setting, status
):
    _, token = register(client)
    monkeypatch.setattr(get_settings(), setting, 1)
    accepted = generate(client, token, "budget-first").json()
    assert execute(client, accepted)["status"] == "succeeded"
    replay = generate(client, token, "budget-first")
    assert replay.status_code == 202 and replay.json() == accepted
    rejected = generate(client, token, "budget-second")
    assert rejected.status_code == status
    assert rejected.json()["error"]["code"] in {"USER_JOB_LIMIT", "SERVICE_JOB_LIMIT"}
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(Presentation)) == 1


def test_daily_service_budget_cannot_be_reset_with_another_account(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_daily_jobs", 1)
    _, token = register(client, "budget_first")
    accepted = generate(client, token).json()
    assert execute(client, accepted)["status"] == "succeeded"
    _, second_token = register(client, "budget_second")
    assert generate(client, second_token).status_code == 503


def test_rolling_budget_recovers_after_24_hours(client, database, monkeypatch):
    _, token = register(client)
    monkeypatch.setattr(get_settings(), "max_daily_jobs_per_user", 1)
    first = generate(client, token).json()
    execute(client, first)
    with database() as db, db.begin():
        db.get(Job, UUID(first["job_id"])).created_at = utcnow() - timedelta(hours=25)
    assert generate(client, token, "next-day").status_code == 202


def test_failed_work_also_consumes_budget(client, monkeypatch):
    _, token = register(client)
    monkeypatch.setattr(get_settings(), "max_daily_jobs_per_user", 1)
    accepted = generate(client, token).json()
    monkeypatch.setenv("PM_FIXTURE_FAILURE", "true")
    assert execute(client, accepted)["status"] == "failed"
    assert generate(client, token, "after-failure").status_code == 429


def test_concurrent_admission_does_not_overshoot_daily_budget(client, database, monkeypatch):
    _, token = register(client)
    monkeypatch.setattr(get_settings(), "max_daily_jobs_per_user", 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: generate(client, token, f"budget-{n}"), range(4)))
    assert sorted(r.status_code for r in results) == [202, 429, 429, 429]
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_terminal_revision_erases_snapshot_but_keeps_document_and_idempotency(client, database):
    _, token = register(client)
    accepted = generate(client, token).json()
    execute(client, accepted)
    current = read(client, accepted)
    path = f"/api/v1/presentations/{accepted['presentation_id']}/revisions"
    body = {"instruction": "Сократи", "base_document_token": current["document_token"]}
    revision = client.post(path, json=body, headers=headers(token, "private-revision")).json()
    assert execute(client, revision)["status"] == "succeeded"
    with database() as db:
        saved = db.get(Job, UUID(revision["job_id"]))
        assert saved.input_snapshot == {}
        assert saved.request_hash and saved.idempotency_key == "private-revision"
    assert read(client, accepted)["document"] is not None
    replay = client.post(path, json=body, headers=headers(token, "private-revision"))
    assert replay.status_code == 202 and replay.json() == revision


def test_failed_job_erases_snapshot(client, database, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    monkeypatch.setenv("PM_FIXTURE_FAILURE", "true")
    execute(client, accepted)
    with database() as db:
        assert db.get(Job, UUID(accepted["job_id"])).input_snapshot == {}


def test_maintenance_scrubs_legacy_terminal_jobs_without_touching_active_data(client, database):
    _, token = register(client)
    first = generate(client, token, "legacy").json()
    execute(client, first)
    active = generate(client, token, "active").json()
    with database() as db, db.begin():
        db.get(Job, UUID(first["job_id"])).input_snapshot = {"text": "legacy private content"}
    worker.maintenance.run()
    with database() as db:
        assert db.get(Job, UUID(first["job_id"])).input_snapshot == {}
        assert db.get(Job, UUID(active["job_id"])).input_snapshot["text"]
    assert read(client, first)["document"]


def test_account_rate_limit_is_shared_across_ip_addresses_and_login_case(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "account_auth_requests_per_window", 1)
    login = "unknown_" + uuid4().hex[:12]
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login", json={"login": login, "password": "wrong password long"},
        headers=headers(token),
    )
    assert response.status_code == 401
    with TestClient(create_app(), client=("198.51.100.99", 12345)) as other:
        token = other.get("/api/v1/auth/csrf").json()["csrf_token"]
        rejected = other.post(
            "/api/v1/auth/login",
            json={"login": login.upper(), "password": "wrong password long"},
            headers=headers(token),
        )
    assert rejected.status_code == 429


def test_ip_auth_limit_is_still_enforced(database, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_requests_per_minute", 1)
    # Уникальный адрес изолирует IP-счётчик этого теста от остальных.
    address = f"2001:db8:{uuid4().hex[:4]}:{uuid4().hex[:4]}::1"
    with TestClient(create_app(), client=(address, 12345)) as other:
        token = other.get("/api/v1/auth/csrf").json()["csrf_token"]
        responses = [
            other.post(
                "/api/v1/auth/login",
                json={"login": f"ip_unknown_{n}", "password": "wrong password long"},
                headers=headers(token),
            )
            for n in range(2)
        ]
    assert [response.status_code for response in responses] == [401, 429]


def test_auth_rate_limit_fails_closed_without_redis(client, monkeypatch):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]

    async def unavailable(*args, **kwargs):
        raise RedisConnectionError("synthetic Redis outage")

    def unexpected_verify(*args):
        pytest.fail("Password verification bypassed the unavailable rate limiter")

    monkeypatch.setattr(Redis, "eval", unavailable)
    monkeypatch.setattr(password_hash, "verify_and_update", unexpected_verify)
    response = client.post(
        "/api/v1/auth/login", json={"login": "unknown", "password": "wrong password long"},
        headers=headers(token),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_hashing_holds_no_database_connection_and_overload_fails_fast(
    client, database, monkeypatch
):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    running = 0

    def delayed_verify(*args):
        nonlocal running
        with lock:
            running += 1
            if running == 2:
                entered.set()
        release.wait(timeout=5)
        return False, None

    monkeypatch.setattr(password_hash, "verify_and_update", delayed_verify)

    def attempt():
        return client.post(
            "/api/v1/auth/login", json={"login": "unknown", "password": "wrong password long"},
            headers=headers(token),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        try:
            assert entered.wait(timeout=3)
            with database() as db:
                held = db.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state = 'idle in transaction'"
                ))
            assert held == 0
            assert attempt().status_code == 429
        finally:
            release.set()
        assert all(future.result().status_code == 401 for future in futures)


def test_registration_can_be_closed_without_changing_login_contract(client, monkeypatch):
    _, token = register(client)
    client.post("/api/v1/auth/logout", headers=headers(token))
    monkeypatch.setattr(get_settings(), "registration_enabled", False)
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    body = {"login": "tester", "password": "correct horse battery staple"}
    denied = client.post("/api/v1/auth/register", json=body, headers=headers(token))
    assert denied.status_code == 403
    response = client.post("/api/v1/auth/login", json=body, headers=headers(token))
    assert response.status_code == 200
    assert set(response.json()) == {"user", "csrf_token"}
    assert "HttpOnly" in response.headers["set-cookie"]


def test_non_ascii_csrf_is_rejected_instead_of_raising_server_error(client):
    register(client)
    response = client.post(
        "/api/v1/auth/logout",
        headers=[(b"origin", b"http://localhost:5173"), (b"x-csrf-token", b"\xff")],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"


def test_maximum_user_count_is_enforced(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_users", 1)
    register(client, "first")
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"login": "second", "password": "correct horse battery staple"},
        headers=headers(token),
    )
    assert response.status_code == 429


@pytest.mark.parametrize("separate_api", [False, True])
def test_production_cookie_host_and_security_headers(database, monkeypatch, separate_api):
    settings = get_settings()
    production = production_settings()
    # Сохраняем изолированные тестовые зависимости; политика учётных данных проверена выше.
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allowed_origins", production.allowed_origins)
    if separate_api:
        monkeypatch.setattr(settings, "allowed_hosts", ["api.example.test"])
    hostname = "api.example.test" if separate_api else "app.example.test"
    with TestClient(create_app(), base_url=f"https://{hostname}") as http:
        response = http.get("/api/v1/auth/csrf")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "__Host-session=" in cookie
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert "Domain=" not in cookie
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert response.headers["cache-control"] == "no-store"
        assert http.get("/api/v1/health/live", headers={"Host": "evil.test"}).status_code == 400
        token = response.json()["csrf_token"]
        denied = http.post(
            "/api/v1/auth/register",
            json={"login": "closed", "password": "correct horse battery staple"},
            headers={"Origin": "https://app.example.test", "X-CSRF-Token": token},
        )
        assert denied.status_code == 403
    with database() as db:
        assert db.scalar(select(Session.user_id)) is None
