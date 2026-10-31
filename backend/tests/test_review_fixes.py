"""Регрессии для находок аудита безопасности: блокировка входа, 500 на суррогатах,
лимит записи, перегрузка БД, кеш readiness и устойчивость обмена с ML-процессом."""

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.auth import service
from app.auth.service import Credentials, account_auth_limits
from app.core.errors import AppError
from app.core.process import exchange
from app.main import create_app
from app.presentations import routes
from app.presentations.schemas import RegenerateRequest, ReviseRequest


class CountingRedis:
    """Имитирует атомарный INCR+EXPIRE скрипта rate_limit."""

    def __init__(self):
        self.counts = {}

    async def eval(self, _script, _keys, key, _seconds):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def fake_request(redis, host):
    state = SimpleNamespace(redis=redis)
    return SimpleNamespace(app=SimpleNamespace(state=state), client=SimpleNamespace(host=host))


def test_failed_logins_from_one_address_do_not_lock_owner_elsewhere(monkeypatch):
    monkeypatch.setattr(service.get_settings(), "account_auth_requests_per_window", 3)
    redis = CountingRedis()
    victim = Credentials(login="Victim", password="x" * 15)

    async def check():
        for _ in range(3):
            await account_auth_limits(fake_request(redis, "203.0.113.7"), victim)
        with pytest.raises(AppError) as blocked:
            await account_auth_limits(fake_request(redis, "203.0.113.7"), victim)
        assert blocked.value.status == 429
        # Владелец входит с другого адреса — посторонний не исчерпал его лимит
        await account_auth_limits(fake_request(redis, "198.51.100.1"), victim)

    anyio.run(check)


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (RegenerateRequest, {"text": "т" * 150, "slideCount": 5, "base_document_token": "\ud800"}),
        (RegenerateRequest, {"text": "т" * 150, "slideCount": 5, "base_document_token": "x" * 129}),
        (RegenerateRequest, {"text": "т" * 150, "slideCount": 5, "base_document_token": ""}),
        (ReviseRequest, {"instruction": "\udc00", "base_document_token": "token"}),
        (ReviseRequest, {"instruction": "Сократи", "base_document_token": "\ud800"}),
    ],
)
def test_unencodable_or_oversized_fields_are_validation_errors(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


def test_write_requests_are_limited_per_user(monkeypatch):
    monkeypatch.setattr(routes.get_settings(), "write_requests_per_minute", 2)
    redis = CountingRedis()
    user = SimpleNamespace(id="11111111-1111-4111-8111-111111111111")
    other = SimpleNamespace(id="22222222-2222-4222-8222-222222222222")
    request = fake_request(redis, "127.0.0.1")

    async def check():
        await routes.write_limits(request, user)
        await routes.write_limits(request, user)
        with pytest.raises(AppError) as limited:
            await routes.write_limits(request, user)
        assert limited.value.status == 429
        await routes.write_limits(request, other)

    anyio.run(check)


def test_database_overload_is_503_with_retry_after():
    client = TestClient(create_app())
    # FastAPI находится внутри оболочек CORS и ограничения тела запроса.
    app = client.app.app.app

    @app.get("/test-busy")
    async def busy():
        raise OperationalError("SELECT private", {}, Exception("statement timeout"))

    response = client.get("/test-busy")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_BUSY"
    assert response.headers["retry-after"] == "5"
    assert "private" not in response.text


def test_readiness_is_cached_between_probes(monkeypatch):
    calls = []

    class Session:
        async def __aenter__(self):
            calls.append("db")
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, _query):
            return None

    async def ping():
        return True

    from app import main

    monkeypatch.setattr(main, "async_sessions", lambda: Session)
    client = TestClient(create_app())
    client.app.app.app.state.redis = SimpleNamespace(ping=ping)
    assert client.get("/api/v1/health/ready").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 200
    assert calls == ["db"]


def python(code):
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        start_new_session=True,
    )


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()


def test_transient_heartbeat_error_is_tolerated_within_grace():
    process = python("import sys, time; sys.stdin.read(); time.sleep(0.6); print('{}')")
    failures = iter([OperationalError("x", {}, Exception("timeout"))])

    def heartbeat():
        error = next(failures, None)
        if error:
            raise error
        return True

    try:
        output = exchange(
            process,
            b"{}",
            max_bytes=1000,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
            heartbeat_seconds=0.1,
            heartbeat=heartbeat,
            heartbeat_grace=5,
        )
    finally:
        kill_group(process)
    assert output.strip() == b"{}"


def test_heartbeat_error_without_grace_still_aborts():
    process = python("import sys, time; sys.stdin.read(); time.sleep(5)")

    def heartbeat():
        raise OperationalError("x", {}, Exception("timeout"))

    try:
        with pytest.raises(OperationalError):
            exchange(
                process,
                b"{}",
                max_bytes=1000,
                deadline=datetime.now(UTC) + timedelta(seconds=10),
                heartbeat_seconds=0.1,
                heartbeat=heartbeat,
            )
    finally:
        kill_group(process)


def test_finished_process_is_not_held_open_by_orphan_child():
    # Потомок наследует stdout и живёт дольше родителя: EOF не наступит до его выхода
    process = python(
        "import subprocess, sys; sys.stdin.read(); sys.stdout.write('done'); sys.stdout.flush(); "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
    )
    started = time.monotonic()
    try:
        output = exchange(
            process,
            b"{}",
            max_bytes=1000,
            deadline=datetime.now(UTC) + timedelta(seconds=20),
            heartbeat_seconds=10,
            heartbeat=lambda: True,
        )
    finally:
        kill_group(process)
    assert output == b"done"
    assert time.monotonic() - started < 5
