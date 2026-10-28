"""Admission auth без внешних PostgreSQL/Redis и обходы production DSN."""

from collections import Counter
from contextlib import ExitStack
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.auth import service
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import utcnow

BODY = {"login": "unknown_account", "password": "wrong password long enough"}
HEADERS = {"Origin": "http://localhost:5173", "X-CSRF-Token": "wrong-token"}


class MemoryRedis:
    def __init__(self, events):
        self.counts = Counter()
        self.events = events
        self.unavailable = False

    async def eval(self, script, numkeys, key, seconds):
        self.events.append(("redis", key))
        if self.unavailable:
            raise RedisConnectionError("synthetic outage")
        self.counts[key] += 1
        return self.counts[key]


@pytest.fixture
def admission_app(monkeypatch):
    settings = Settings(
        _env_file=None,
        environment="test",
        ml_adapter="fixture",
        auth_requests_per_minute=100,
        global_auth_requests_per_minute=100,
        account_auth_requests_per_window=100,
        csrf_requests_per_minute=100,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    events = []
    redis = MemoryRedis(events)
    now = utcnow()
    row = SimpleNamespace(
        csrf_token="known-token",
        user_id=None,
        expires_at=now + timedelta(hours=1),
        last_seen_at=now,
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), commit=AsyncMock())

    async def database():
        events.append(("database", None))
        yield db

    app = FastAPI()
    app.state.redis = redis
    app.state.password_limiter = SimpleNamespace(acquire_nowait=lambda: None, release=lambda: None)
    app.state.password_thread_limiter = None
    app.dependency_overrides[service.database] = database
    app.include_router(service.router, prefix="/api/v1")

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code}})

    with ExitStack() as stack:

        def client(address="198.51.100.1"):
            http = stack.enter_context(TestClient(app, client=(address, 12345)))
            http.cookies.set(settings.cookie_name, "random-session-cookie")
            return http

        yield SimpleNamespace(client=client, settings=settings, db=db, redis=redis, events=events)


def request(http, route, **kwargs):
    if route == "csrf":
        return http.get("/api/v1/auth/csrf")
    return http.post(f"/api/v1/auth/{route}", json=kwargs.get("body", BODY), headers=HEADERS)


@pytest.mark.parametrize(
    ("route", "setting", "scope"),
    [
        ("csrf", "csrf_requests_per_minute", "csrf"),
        ("login", "auth_requests_per_minute", "auth"),
        ("register", "auth_requests_per_minute", "auth"),
        ("login", "global_auth_requests_per_minute", "auth-global"),
        ("register", "global_auth_requests_per_minute", "auth-global"),
        ("login", "account_auth_requests_per_window", "auth-account"),
        ("register", "account_auth_requests_per_window", "auth-account"),
    ],
)
def test_limits_run_once_and_reject_random_cookie_before_database(
    admission_app, route, setting, scope
):
    state = admission_app
    setattr(state.settings, setting, 1)
    http = state.client()
    first = request(http, route)
    assert first.status_code == (200 if route == "csrf" else 403)
    assert state.events[0][0] == "redis"
    database_index = state.events.index(("database", None))
    assert all(event[0] == "redis" for event in state.events[:database_index])
    assert all(count == 1 for count in state.redis.counts.values())
    state.db.scalar.reset_mock()
    state.db.commit.reset_mock()
    state.events.clear()

    rejected = request(http, route)
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "RATE_LIMITED"
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()
    assert all(event[0] == "redis" for event in state.events)
    assert sum(count == 2 for count in state.redis.counts.values()) >= 1
    assert any(f":{scope}:" in key and count == 2 for key, count in state.redis.counts.items())


@pytest.mark.parametrize("route", ["csrf", "login", "register"])
def test_redis_outage_rejects_before_database(admission_app, route):
    state = admission_app
    state.redis.unavailable = True
    response = request(state.client(), route)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()
    assert all(event[0] == "redis" for event in state.events)


def test_account_limit_is_shared_between_routes_addresses_and_login_case(admission_app):
    state = admission_app
    state.settings.account_auth_requests_per_window = 1
    assert request(state.client(), "login").status_code == 403
    state.db.scalar.reset_mock()
    state.db.commit.reset_mock()
    response = request(
        state.client("198.51.100.2"),
        "register",
        body={**BODY, "login": BODY["login"].upper()},
    )
    assert response.status_code == 429
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()


def test_login_handler_does_not_count_admitted_request_again(admission_app, monkeypatch):
    state = admission_app
    state.settings.auth_requests_per_minute = 1
    state.settings.global_auth_requests_per_minute = 1
    state.settings.account_auth_requests_per_window = 1
    state.db.execute = AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: None))
    monkeypatch.setattr(service.password_hash, "verify_and_update", lambda *args: (False, None))
    http = state.client()
    response = http.post(
        "/api/v1/auth/login",
        json=BODY,
        headers={**HEADERS, "X-CSRF-Token": "known-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert len(state.redis.counts) == 3
    assert all(count == 1 for count in state.redis.counts.values())
    state.db.scalar.reset_mock()
    state.db.commit.reset_mock()
    assert request(http, "login").status_code == 429
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()


@pytest.mark.parametrize("route", ["login", "register"])
def test_invalid_credentials_cannot_bypass_early_ip_limit(admission_app, route):
    state = admission_app
    state.settings.auth_requests_per_minute = 1
    http = state.client()
    assert request(http, route).status_code == 403
    state.db.scalar.reset_mock()
    state.db.commit.reset_mock()
    assert request(http, route, body={"invalid": "credentials"}).status_code == 429
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()


@pytest.mark.parametrize("route", ["login", "register", "logout"])
def test_missing_session_preserves_403_vs_protected_401_without_dependencies(admission_app, route):
    state = admission_app
    http = state.client()
    http.cookies.clear()
    response = request(http, route)
    assert response.status_code == (401 if route == "logout" else 403)
    assert response.json()["error"]["code"] == (
        "AUTH_REQUIRED" if route == "logout" else "CSRF_REJECTED"
    )
    assert not state.redis.counts
    state.db.scalar.assert_not_awaited()
    state.db.commit.assert_not_awaited()


@pytest.mark.parametrize("route", ["login", "register"])
@pytest.mark.parametrize("invalid", ["origin", "csrf"])
def test_admitted_auth_still_checks_origin_and_csrf(admission_app, route, invalid):
    headers = {**HEADERS, "X-CSRF-Token": "known-token"}
    if invalid == "origin":
        headers["Origin"] = "https://evil.example"
    else:
        headers["X-CSRF-Token"] = "wrong-token"
    response = admission_app.client().post(f"/api/v1/auth/{route}", json=BODY, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == (
        "ORIGIN_REJECTED" if invalid == "origin" else "CSRF_REJECTED"
    )


def production_settings(query):
    return Settings(
        _env_file=None,
        environment="production",
        ml_adapter="module",
        allowed_origins=["https://app.example.test"],
        database_url=(
            "postgresql+psycopg://pm_service:dedicated-long-secret@db.example/pm?" + query
        ),
        redis_url="redis://:dedicated-long-secret@localhost:6379/0",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("user", "postgres"),
        ("password", "postgres"),
        ("dbname", "postgres"),
        ("dbname", "postgresql://postgres:postgres@localhost/postgres"),
        ("host", "localhost"),
        ("hostaddr", "127.0.0.1"),
        ("port", "5433"),
        ("service", "unsafe"),
        ("servicefile", "/tmp/unsafe.conf"),
        ("passfile", "/tmp/unsafe.pgpass"),
        ("options", "-c role=postgres"),
        ("unknown_future_option", "unsafe"),
    ],
)
def test_production_rejects_overriding_database_query(key, value):
    query = urlencode({"sslmode": "verify-full", key: value})
    with pytest.raises(ValidationError, match="dedicated database credentials"):
        production_settings(query)


def test_production_rejects_combined_and_encoded_credential_override():
    for query in (
        "sslmode=verify-full&user=postgres&password=postgres",
        "sslmode=verify-full&%75ser=postgres&%70assword=postgres",
        "sslmode=verify-full&sslmode=disable",
        "sslmode=verify-full&application_name=one&application_name=two",
    ):
        with pytest.raises(ValidationError):
            production_settings(query)


def test_production_allows_non_overriding_tls_and_connection_tuning():
    query = urlencode(
        {
            "sslmode": "verify-full",
            "sslrootcert": "/etc/ssl/certs/postgres.pem",
            "sslcert": "/etc/ssl/client.pem",
            "sslkey": "/etc/ssl/client.key",
            "connect_timeout": "5",
            "application_name": "presentation-maker",
            "keepalives": "1",
            "keepalives_idle": "30",
            "channel_binding": "require",
        }
    )
    assert production_settings(query).environment == "production"
