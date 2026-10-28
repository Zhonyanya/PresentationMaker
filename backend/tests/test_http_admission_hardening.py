"""HTTP admission и безопасная readiness без подключения к БД/Redis."""

import asyncio
import inspect
import os
import sys
import threading
import time
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient

from app import main
from app.core import readiness
from app.core.config import get_settings
from app.core.readiness import ModuleReadiness
from app.main import BodyLimitMiddleware

SCOPE = {"type": "http", "http_version": "1.1"}


async def request(middleware, messages=None):
    remaining = iter(messages or [{"type": "http.request", "body": b"data"}])
    responses = []

    async def receive():
        return next(remaining)

    async def send(message):
        responses.append(message)

    await middleware(SCOPE, receive, send)
    return responses


@pytest.mark.parametrize("outcome", ["return", "error", "cancel"])
@pytest.mark.parametrize("consume", [False, True])
def test_admission_is_held_until_application_finishes(outcome, consume):
    async def check():
        entered, release, finished = anyio.Event(), anyio.Event(), anyio.Event()
        calls = []
        first_scope = None

        async def app(scope, receive, send):
            calls.append(scope)
            if len(calls) != 1:
                return
            if consume:
                assert (await receive())["body"] == b"data"
                assert inspect.getclosurevars(receive).nonlocals["body"] is None
            entered.set()
            await release.wait()
            if outcome == "error":
                raise RuntimeError("application failed")

        middleware = BodyLimitMiddleware(app, 10, max_readers=1)

        async def first():
            nonlocal first_scope
            try:
                with anyio.CancelScope() as first_scope:
                    await request(middleware)
            except RuntimeError:
                assert outcome == "error"
            finally:
                finished.set()

        async with anyio.create_task_group() as group:
            group.start_soon(first)
            await entered.wait()
            assert middleware.readers.borrowed_tokens == 1
            result = await request(middleware)
            assert result[0]["status"] == 503
            assert len(calls) == 1
            if outcome == "cancel":
                first_scope.cancel()
            else:
                release.set()
            await finished.wait()
            assert middleware.readers.borrowed_tokens == 0
            await request(middleware)
            assert len(calls) == 2
            assert middleware.readers.borrowed_tokens == 0

    anyio.run(check)


@pytest.mark.parametrize("failure", ["disconnect", "oversize", "timeout", "receive", "send"])
def test_admission_is_released_on_body_and_rejection_failures(failure):
    async def check():
        calls = []

        async def app(*args):
            calls.append(True)

        async def receive():
            if failure == "disconnect":
                return {"type": "http.disconnect"}
            if failure == "timeout":
                await anyio.sleep_forever()
            if failure == "receive":
                raise RuntimeError("receive failed")
            return {"type": "http.request", "body": b"x" * 11}

        responses = []

        async def send(message):
            if failure == "send":
                raise RuntimeError("send failed")
            responses.append(message)

        middleware = BodyLimitMiddleware(app, 10, timeout=0.02, max_readers=1)
        if failure in {"receive", "send"}:
            with pytest.raises(RuntimeError):
                await middleware(SCOPE, receive, send)
        else:
            await middleware(SCOPE, receive, send)
        assert not calls
        if failure in {"oversize", "timeout"}:
            assert responses[0]["status"] == (413 if failure == "oversize" else 408)
        assert middleware.readers.borrowed_tokens == 0
        await request(middleware)
        assert calls == [True]

    anyio.run(check)


def install_module(tmp_path, monkeypatch, source):
    name = "pm_readiness_probe_fixture"
    (tmp_path / f"{name}.py").write_text(source)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), os.getenv("PYTHONPATH", "")]))
    return name


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def generate(**inputs):\n    raise RuntimeError('must not be called')\n", True),
        ("async def generate(**inputs):\n    raise RuntimeError('must not be called')\n", True),
        ("generate = 'not callable'\n", False),
    ],
)
def test_readiness_checks_generate_without_importing_or_invoking_in_api(
    tmp_path, monkeypatch, source, expected
):
    name = install_module(tmp_path, monkeypatch, source)
    assert anyio.run(ModuleReadiness(name).is_ready) is expected
    assert name not in sys.modules


def test_installed_module_without_generate_is_not_ready():
    assert anyio.run(ModuleReadiness("json").is_ready) is False


@pytest.mark.parametrize("result", [False, True])
def test_readiness_polling_is_single_flight_and_caches_both_results(monkeypatch, result):
    async def check():
        probe = ModuleReadiness("unused")
        started = anyio.Event()
        release = threading.Event()
        calls = []

        def blocking_probe():
            calls.append(True)
            anyio.from_thread.run_sync(started.set)
            assert release.wait(timeout=5)
            return result

        monkeypatch.setattr(probe, "_probe", blocking_probe)

        async def first():
            assert await probe.is_ready() is result

        async with anyio.create_task_group() as group:
            group.start_soon(first)
            await started.wait()
            try:
                for _ in range(30):
                    assert await probe.is_ready() is False
                assert calls == [True]
            finally:
                release.set()
        for _ in range(30):
            assert await probe.is_ready() is result
        assert calls == [True]
        probe._expires = 0
        assert await probe.is_ready() is result
        assert calls == [True, True]

    anyio.run(check)


def test_probe_timeout_reaps_process_and_caches_failure(tmp_path, monkeypatch):
    name = install_module(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")
    popen = readiness.subprocess.Popen
    children = []

    def recording_popen(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(readiness.subprocess, "Popen", recording_popen)
    probe = ModuleReadiness(name, timeout=0.1)
    started = time.monotonic()
    assert anyio.run(probe.is_ready) is False
    assert time.monotonic() - started < 5
    assert children[0].poll() is not None
    assert anyio.run(probe.is_ready) is False
    assert len(children) == 1


def test_cancelled_poll_does_not_release_single_flight_before_probe_finishes(monkeypatch):
    async def check():
        probe = ModuleReadiness("unused")
        started, finished = anyio.Event(), anyio.Event()
        release = threading.Event()
        calls = []

        def blocking_probe():
            calls.append(True)
            anyio.from_thread.run_sync(started.set)
            try:
                assert release.wait(timeout=5)
                return True
            finally:
                anyio.from_thread.run_sync(finished.set)

        monkeypatch.setattr(probe, "_probe", blocking_probe)
        task = asyncio.create_task(probe.is_ready())
        await started.wait()
        try:
            # Даже прямая asyncio-отмена не должна отпускать lock рабочего потока.
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert probe._lock.locked()
            for _ in range(30):
                assert await probe.is_ready() is False
            assert calls == [True]
        finally:
            release.set()
            await finished.wait()
        with anyio.fail_after(5):
            while probe._lock.locked():
                await anyio.sleep(0)
        assert await probe.is_ready() is True
        assert calls == [True]

    anyio.run(check)


def test_probe_spawn_failure_is_cached_without_private_errors(monkeypatch, caplog):
    probe = ModuleReadiness("unused")
    calls = []

    def failed_probe():
        calls.append(True)
        raise OSError("private-ml-spawn-secret")

    monkeypatch.setattr(probe, "_probe", failed_probe)
    assert anyio.run(probe.is_ready) is False
    assert anyio.run(probe.is_ready) is False
    assert calls == [True]
    assert "private-ml-spawn-secret" not in caplog.text


def test_probe_discards_private_import_output_and_exceptions(tmp_path, monkeypatch, capfd, caplog):
    secret = "private-ml-import-secret"
    name = install_module(
        tmp_path,
        monkeypatch,
        f"import os\nos.write(1, b'{secret}' * 100000)\n"
        f"os.write(2, b'{secret}' * 100000)\nraise RuntimeError('{secret}')\n",
    )
    assert anyio.run(ModuleReadiness(name).is_ready) is False
    captured = capfd.readouterr()
    assert secret not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("compatible", [False, True])
def test_ready_http_checks_module_interface_without_live_services(
    tmp_path, monkeypatch, compatible
):
    name = "json"
    if compatible:
        name = install_module(tmp_path, monkeypatch, "async def generate(**inputs):\n    pass\n")
    settings = get_settings().model_copy(update={"ml_adapter": "module", "ml_module": name})
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def execute(self, statement):
            pass

    async def ping():
        return True

    monkeypatch.setattr(main, "async_sessions", lambda: Session)
    app = main.create_app()
    app.app.app.state.redis = SimpleNamespace(ping=ping)
    # Не запускаем lifespan: зависимости полностью локальные, без Redis/engine.
    client = TestClient(app)
    try:
        response = client.get("/api/v1/health/ready", headers={"Origin": "http://localhost:5173"})
    finally:
        client.close()
    assert response.status_code == (200 if compatible else 503)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    if not compatible:
        assert response.json()["error"]["code"] == "NOT_READY"
    assert name == "json" or name not in sys.modules
