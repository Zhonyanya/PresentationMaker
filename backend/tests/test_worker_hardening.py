import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest
from conftest import generate, register
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, StatementError

from app import worker
from app.core.process import exchange
from app.db.engine import connection_options
from app.db.models import Job, Presentation, utcnow
from app.presentations.schemas import GenerateRequest, ReviseRequest, normalize_document


@pytest.fixture
def supervised():
    processes = []
    descriptors = []

    def start(command, seconds=5):
        reader, writer = os.pipe()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.core.supervisor",
                    (utcnow() + timedelta(seconds=seconds)).isoformat(),
                    str(reader),
                    *command,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(reader,),
            )
        except BaseException:
            os.close(writer)
            raise
        finally:
            os.close(reader)
        processes.append(process)
        descriptors.append(writer)

        def disconnect():
            if writer in descriptors:
                descriptors.remove(writer)
                os.close(writer)

        return process, disconnect

    yield start
    for descriptor in descriptors:
        os.close(descriptor)
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()


def read_line(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(5), "Subprocess did not start"
        return process.stdout.readline()


def running(pid):
    try:
        with open(f"/proc/{pid}/stat") as state:
            return state.read().split(") ", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def test_external_watchdog_stops_native_computation(supervised):
    process, _ = supervised(
        [
            sys.executable,
            "-c",
            "import hashlib; hashlib.pbkdf2_hmac('sha256', b'input', b'salt', 200000000)",
        ],
        seconds=0.4,
    )
    started = time.monotonic()
    assert process.wait(timeout=3) == -signal.SIGKILL
    assert time.monotonic() - started < 2


def test_lifeline_closure_stops_whole_process_group(supervised):
    process, disconnect = supervised(
        [
            sys.executable,
            "-c",
            "import os,time; print(os.getpid(),flush=True); time.sleep(60)",
        ]
    )
    child = int(read_line(process))
    disconnect()
    assert process.wait(timeout=2) == -signal.SIGKILL
    deadline = time.monotonic() + 2
    while running(child) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not running(child)


def test_watchdog_survives_actual_parent_sigkill():
    parent_code = """
import os, subprocess, sys, time
from datetime import UTC, datetime, timedelta
reader, writer = os.pipe()
process = subprocess.Popen(
    [sys.executable, '-m', 'app.core.supervisor',
     (datetime.now(UTC)+timedelta(seconds=60)).isoformat(), str(reader),
     sys.executable, '-c', 'import os,time; print(os.getpid(),flush=True); time.sleep(60)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    start_new_session=True, pass_fds=(reader,))
os.close(reader)
print(process.pid, int(process.stdout.readline()), flush=True)
time.sleep(60)
"""
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    group = child = None
    try:
        group, child = map(int, read_line(parent).split())
        parent.kill()
        parent.wait(timeout=2)
        deadline = time.monotonic() + 2
        while (running(group) or running(child)) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not running(group) and not running(child)
    finally:
        parent.kill()
        parent.wait(timeout=2)
        parent.stdout.close()
        if group is not None:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_blocked_heartbeat_cannot_pause_transport_deadline():
    release = threading.Event()
    entered = threading.Event()

    def slow_heartbeat():
        entered.set()
        release.wait(timeout=5)
        return True

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            exchange(
                process,
                b"{}",
                max_bytes=128,
                deadline=utcnow() + timedelta(seconds=0.2),
                heartbeat_seconds=0.01,
                heartbeat=slow_heartbeat,
            )
        assert entered.is_set()
        assert time.monotonic() - started < 1
    finally:
        release.set()
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        process.stdin.close()
        process.stdout.close()


def test_database_engines_hide_parameters_and_bound_waits():
    options = connection_options()
    assert options["hide_parameters"] is True
    assert options["pool_timeout"] <= 2
    assert options["connect_args"]["connect_timeout"] <= 2
    assert "statement_timeout=" in options["connect_args"]["options"]
    assert "lock_timeout=" in options["connect_args"]["options"]


@pytest.mark.parametrize("field", ["text", "title"])
def test_generation_rejects_nul_before_database(field):
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(
            {"text": "x" * 100, "slideCount": 3, field: "x" * 100 + "\x00"}
        )


def test_revision_rejects_nul_instruction():
    with pytest.raises(ValidationError):
        ReviseRequest(instruction="Change\x00", base_document_token="current")


@pytest.mark.parametrize("field", ["id", "title", "notes"])
def test_document_rejects_nul_before_database(document, field):
    document["slides"][0][field] = "invalid\x00"
    with pytest.raises(ValidationError):
        normalize_document(document, generation=True, max_bytes=8_000_000)


def test_double_database_failure_does_not_leak_celery_exception_context(
    client, database, monkeypatch, caplog, document
):
    _, token = register(client)
    accepted = generate(client, token).json()
    secret = "PRIVATE_REPORT_MUST_NOT_REACH_CELERY"
    monkeypatch.setattr(worker, "call_ml", lambda *args: document)
    monkeypatch.setattr(
        worker,
        "publish_result",
        Mock(
            side_effect=StatementError(
                "write failed",
                "UPDATE presentations SET document=:document",
                {"document": secret},
                RuntimeError("database unavailable"),
            )
        ),
    )
    monkeypatch.setattr(worker, "fail_job", Mock(side_effect=RuntimeError(secret)))
    result = worker.execute_job.apply(args=[accepted["job_id"]], throw=False)
    assert result.failed()
    assert isinstance(result.result, worker.TaskStateUnavailable)
    assert result.result.__context__ is None
    assert secret not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert "task_failed" in caplog.text
    with database() as db:
        assert db.get(Job, UUID(accepted["job_id"])).status == "running"


def test_claim_failure_and_maintenance_failure_do_not_escape_to_celery(monkeypatch, caplog):
    secret = "PRIVATE_DATABASE_EXCEPTION"
    monkeypatch.setattr(worker, "sync_sessions", Mock(side_effect=RuntimeError(secret)))
    assert worker.execute_job.apply(args=[str(UUID(int=1))], throw=False).failed()
    assert worker.maintenance.apply(throw=False).failed()
    assert secret not in caplog.text
    assert "task_failed" in caplog.text


def test_phase_transition_cannot_overwrite_terminal_state(client, database):
    _, token = register(client)
    accepted = generate(client, token).json()
    identifier = UUID(accepted["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.phase, job.attempt_token = "timed_out", "done", "attempt"
    assert not worker.advance_phase(identifier, "attempt", "validation")
    with database() as db:
        job = db.get(Job, identifier)
        assert (job.status, job.phase) == ("timed_out", "done")


def test_maintenance_has_separate_route():
    route = worker.celery.amqp.router.route({}, "pm.maintenance")
    generation = worker.celery.amqp.router.route({}, "pm.execute_job")
    assert route["queue"].name == "pm.maintenance"
    assert generation["queue"].name != route["queue"].name


def test_nul_source_returns_validation_error_instead_of_database_error(client):
    _, token = register(client)
    response = generate(client, token, text="x" * 100 + "\x00")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_heartbeat_lock_wait_is_bounded_by_remaining_budget(client, database):
    _, token = register(client)
    identifier = UUID(generate(client, token).json()["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.attempt_token = "running", "attempt"
    with database() as blocker, blocker.begin():
        blocker.scalar(select(Job).where(Job.id == identifier).with_for_update())
        started = time.monotonic()
        with pytest.raises(DBAPIError):
            worker.heartbeat(identifier, "attempt", utcnow() + timedelta(seconds=0.15))
        assert time.monotonic() - started < 1


def test_expired_publication_rolls_back_document_after_flush(
    client, database, document, monkeypatch
):
    _, token = register(client)
    accepted = generate(client, token).json()
    identifier = UUID(accepted["job_id"])
    now = utcnow()
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.attempt_token = "running", "attempt"
        job.deadline_at = now + timedelta(seconds=10)
    ticks = iter([now, now, now, now, now + timedelta(seconds=11)])
    monkeypatch.setattr(worker, "utcnow", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        worker.publish_result(identifier, "attempt", document)
    with database() as db:
        job = db.get(Job, identifier)
        presentation = db.get(Presentation, job.presentation_id)
        assert presentation.document is None and presentation.document_token is None
        assert job.status == "running" and job.input_snapshot
