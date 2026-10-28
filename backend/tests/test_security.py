import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import anyio
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.process import exchange
from app.main import BodyLimitMiddleware
from app.presentations.schemas import normalize_document


def production_settings(**changes):
    values = {
        "environment": "production",
        "ml_adapter": "module",
        "allowed_origins": ["https://app.example.test"],
        "database_url": "postgresql+psycopg://pm_service:a-long-test-password@localhost/pm",
        "redis_url": "redis://:a-long-test-password@localhost:6379/0",
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_production_registration_and_cookie_defaults():
    settings = production_settings()
    assert not settings.registration_open
    assert settings.secure_cookie
    assert settings.cookie_name == "__Host-session"
    assert production_settings(registration_enabled=True).registration_open
    assert Settings(environment="test", ml_adapter="fixture").registration_open


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "postgresql+psycopg://postgres:postgres@localhost/pm"},
        {"database_url": "postgresql+psycopg://pm_service@localhost/pm"},
        {"database_url": "postgresql+psycopg://pm_service:password@localhost/pm"},
        {"database_url": "postgresql+psycopg://pm_service:a-long-test-password@db.example/pm"},
        {"redis_url": "redis://localhost:6379/0"},
        {"redis_url": "redis://:password@localhost:6379/0"},
        {"redis_url": "redis://:%70assword@localhost:6379/0"},
        {"redis_url": "redis://:a-long-test-password@redis.example:6379/0"},
        {"redis_url": "rediss://:a-long-test-password@redis.example/0?ssl_cert_reqs=none"},
        {"redis_url": "rediss://:a-long-test-password@redis.example/0?ssl_check_hostname=false"},
        {"allowed_origins": ["https://app.example.test/path"]},
        {"allowed_origins": ["https://user@app.example.test"]},
        {"allowed_origins": ["https://app.example.test?query=1"]},
        {"allowed_origins": ["https://app.example.test:bad"]},
        {"allowed_origins": ["https://*.example.test"]},
        {"allowed_hosts": ["*"]},
        {"allowed_hosts": ["api.example.test:8000"]},
        {"allowed_hosts": ["user@api.example.test"]},
    ],
)
def test_production_rejects_unsafe_settings(changes):
    with pytest.raises((ValidationError, ValueError)):
        production_settings(**changes)


def test_remote_production_dependencies_require_tls():
    settings = production_settings(
        database_url=(
            "postgresql+psycopg://pm_service:a-long-test-password@db.example/pm?sslmode=verify-full"
        ),
        redis_url="rediss://:a-long-test-password@redis.example:6379/0",
    )
    assert settings.environment == "production"


async def invoke_body(middleware, messages, *, slow=False):
    responses = []
    chunks = iter(messages)

    async def receive():
        if slow:
            await anyio.sleep(1)
        return next(chunks)

    async def send(message):
        responses.append(message)

    await middleware({"type": "http", "http_version": "1.1"}, receive, send)
    return responses


@pytest.mark.parametrize("chunks", [[b"x" * 10], [b"x" * 4, b"x" * 6]])
def test_body_limit_accepts_exact_boundary(chunks):
    async def check():
        observed = []

        async def app(scope, receive, send):
            observed.append(await receive())

        middleware = BodyLimitMiddleware(app, 10)
        await invoke_body(
            middleware,
            [
                {"type": "http.request", "body": chunk, "more_body": n < len(chunks) - 1}
                for n, chunk in enumerate(chunks)
            ],
        )
        assert observed == [{"type": "http.request", "body": b"x" * 10, "more_body": False}]

    anyio.run(check)


def test_body_limit_rejects_oversize_without_invoking_application():
    async def check():
        async def app(*args):
            pytest.fail("Oversized body reached the application")

        messages = await invoke_body(
            BodyLimitMiddleware(app, 10),
            [{"type": "http.request", "body": b"x" * 11, "more_body": True}],
        )
        assert messages[0]["status"] == 413
        payload = json.loads(messages[1]["body"])
        assert payload["error"]["code"] == "REQUEST_TOO_LARGE"
        assert dict(messages[0]["headers"])[b"connection"] == b"close"

    anyio.run(check)


def test_slow_body_times_out_and_releases_reader_slot():
    async def check():
        reached = []

        async def app(*args):
            reached.append(True)

        middleware = BodyLimitMiddleware(app, 10, timeout=0.03, max_readers=1)
        result = await invoke_body(middleware, [], slow=True)
        assert result[0]["status"] == 408
        assert not reached
        await invoke_body(middleware, [{"type": "http.request", "body": b"ok"}])
        assert reached == [True]

    anyio.run(check)


def test_concurrent_body_readers_have_bounded_admission():
    async def check():
        waiting = anyio.Event()

        async def app(*args):
            pass

        async def blocked_receive():
            waiting.set()
            await anyio.sleep_forever()

        async def send(*args):
            pass

        middleware = BodyLimitMiddleware(app, 10, max_readers=1)
        async with anyio.create_task_group() as group:
            group.start_soon(middleware, {"type": "http"}, blocked_receive, send)
            await waiting.wait()
            result = await invoke_body(middleware, [])
            assert result[0]["status"] == 503
            group.cancel_scope.cancel()
        assert middleware.readers.borrowed_tokens == 0

    anyio.run(check)


@pytest.fixture
def child():
    processes = []

    def start(code):
        process = subprocess.Popen(
            [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        processes.append(process)
        return process

    yield start
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.stdin.close()
        process.stdout.close()
        process.wait(timeout=5)


def test_subprocess_output_is_rejected_before_exit(child):
    process = child("import os,time; os.write(1,b'x'*65536); time.sleep(10)")
    started = time.monotonic()
    with pytest.raises(ValueError, match="Excessive"):
        exchange(
            process, b"{}", max_bytes=128, deadline=datetime.now(UTC) + timedelta(seconds=5),
            heartbeat_seconds=1, heartbeat=lambda: True,
        )
    assert time.monotonic() - started < 2
    assert process.poll() is None


def test_subprocess_duplex_transport_handles_large_input_and_utf8(child):
    process = child("import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)")
    payload = ("Привет" * 20000).encode()
    result = exchange(
        process, payload, max_bytes=len(payload),
        deadline=datetime.now(UTC) + timedelta(seconds=5),
        heartbeat_seconds=1, heartbeat=lambda: True,
    )
    assert result == payload and process.returncode == 0


def test_subprocess_deadline_applies_to_blocked_input(child):
    process = child("import time; time.sleep(10)")
    with pytest.raises(TimeoutError):
        exchange(
            process, b"x" * 200000, max_bytes=128,
            deadline=datetime.now(UTC) + timedelta(seconds=0.08),
            heartbeat_seconds=1, heartbeat=lambda: True,
        )


def test_subprocess_stops_when_attempt_is_no_longer_active(child):
    process = child("import time; time.sleep(10)")
    with pytest.raises(TimeoutError):
        exchange(
            process, b"{}", max_bytes=128,
            deadline=datetime.now(UTC) + timedelta(seconds=5),
            heartbeat_seconds=0.02, heartbeat=lambda: False,
        )


def test_document_size_rejects_large_object_before_encoding(document, monkeypatch):
    document["title"] = "x" * 1001

    def unexpected_encode(*args, **kwargs):
        pytest.fail("Oversized string reached JSON encoder")

    monkeypatch.setattr(json.JSONEncoder, "iterencode", unexpected_encode)
    with pytest.raises(ValueError, match="too large"):
        normalize_document(document, generation=True, max_bytes=1000)


def test_document_streamed_size_matches_previous_byte_limit(document):
    size = len(json.dumps(document, ensure_ascii=False).encode())
    normalize_document(document, generation=True, max_bytes=size)
    with pytest.raises(ValueError, match="too large"):
        normalize_document(document, generation=True, max_bytes=size - 1)
