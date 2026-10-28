from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from conftest import generate, register
from test_api import read

from app import worker
from app.core.errors import AppError
from app.db.models import Job, Presentation, utcnow
from app.worker import dispatch_job


@pytest.fixture
def queued_job(client):
    _, token = register(client)
    response = generate(client, token)
    assert response.status_code == 202, response.text
    return response.json()


@pytest.mark.parametrize(
    ("state", "expected"),
    [("queued", False), ("running", True), ("stale_attempt", False), ("expired", False)],
)
def test_heartbeat_only_updates_live_owned_attempt(
    database, queued_job, monkeypatch, state, expected
):
    identifier = UUID(queued_job["job_id"])
    now = utcnow()
    old_heartbeat = now - timedelta(seconds=30)
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status = "queued" if state == "queued" else "running"
        job.attempt_token = "current"
        job.heartbeat_at = old_heartbeat
        job.deadline_at = now + timedelta(seconds=-1 if state == "expired" else 100)
    monkeypatch.setattr(worker, "utcnow", lambda: now)
    attempt = "old" if state == "stale_attempt" else "current"
    assert worker.heartbeat(identifier, attempt) is expected
    with database() as db:
        assert db.get(Job, identifier).heartbeat_at == (now if expected else old_heartbeat)
    assert not worker.heartbeat(uuid4(), "current")


@pytest.mark.parametrize("stale", [False, True])
def test_failure_cannot_overwrite_another_attempt(database, queued_job, stale):
    identifier = UUID(queued_job["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.attempt_token = "running", "current"
    worker.fail_job(identifier, "old" if stale else "current", "GENERATION_FAILED", "Safe error")
    with database() as db:
        job = db.get(Job, identifier)
        assert job.status == ("running" if stale else "failed")
        assert bool(job.input_snapshot) is stale
        assert (job.finished_at is None) is stale
        assert job.phase == ("waiting" if stale else "done")
        assert job.error_code == (None if stale else "GENERATION_FAILED")


def test_failure_after_deadline_is_timeout(database, queued_job):
    identifier = UUID(queued_job["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.attempt_token = "running", "current"
        job.deadline_at = utcnow() - timedelta(seconds=1)
    worker.fail_job(identifier, "current", "GENERATION_FAILED", "Other error")
    with database() as db:
        job = db.get(Job, identifier)
        assert (job.status, job.phase, job.error_code) == ("timed_out", "done", "JOB_TIMED_OUT")
        assert job.finished_at is not None and job.input_snapshot == {}


@pytest.mark.parametrize("state", ["ready", "recent", "retry", "running", "expired", "missing"])
def test_dispatch_checks_state_deadline_and_retry_window(database, queued_job, monkeypatch, state):
    identifier = UUID(queued_job["job_id"])
    now = utcnow()
    previous_dispatch = None
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        if state == "running":
            job.status = "running"
        if state == "expired":
            job.deadline_at = now - timedelta(seconds=1)
        if state in {"recent", "retry"}:
            previous_dispatch = now - timedelta(
                seconds=1 if state == "recent" else worker.settings.dispatch_retry_seconds + 1
            )
            job.dispatched_at = previous_dispatch
    publish = Mock()
    monkeypatch.setattr(worker.execute_job, "apply_async", publish)
    monkeypatch.setattr(worker, "utcnow", lambda: now)
    dispatch_job(uuid4() if state == "missing" else identifier)
    if state in {"ready", "retry"}:
        publish.assert_called_once_with(args=[str(identifier)], retry=False)
    else:
        publish.assert_not_called()
    with database() as db:
        assert db.get(Job, identifier).dispatched_at == (
            now if state in {"ready", "retry"} else previous_dispatch
        )


@pytest.mark.parametrize("state", ["expired", "running", "succeeded", "missing"])
def test_ineligible_delivery_never_invokes_ml(client, database, queued_job, monkeypatch, state):
    identifier = UUID(queued_job["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        if state == "expired":
            job.deadline_at = utcnow() - timedelta(seconds=1)
        elif state != "missing":
            job.status = state
    ml = Mock(side_effect=AssertionError("Ineligible delivery invoked ML"))
    monkeypatch.setattr(worker, "call_ml", ml)
    worker.execute_job.run(str(uuid4()) if state == "missing" else str(identifier))
    ml.assert_not_called()
    if state == "expired":
        with database() as db:
            job = db.get(Job, identifier)
            assert (job.status, job.error_code, job.phase) == ("timed_out", "JOB_TIMED_OUT", "done")
            assert job.input_snapshot == {} and job.finished_at is not None
        assert read(client, queued_job)["document"] is None


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (TimeoutError(), "timed_out", "JOB_TIMED_OUT"),
        (SoftTimeLimitExceeded(), "timed_out", "JOB_TIMED_OUT"),
        (AppError(503, "ML_UNAVAILABLE", "Safe message"), "failed", "ML_UNAVAILABLE"),
        (ValueError("private output"), "failed", "INVALID_ML_RESPONSE"),
        (TypeError("private output"), "failed", "INVALID_ML_RESPONSE"),
        (KeyError("private output"), "failed", "INVALID_ML_RESPONSE"),
        (RuntimeError("private output"), "failed", "GENERATION_FAILED"),
    ],
)
def test_execution_errors_clear_snapshot_and_do_not_publish(
    client, database, queued_job, monkeypatch, caplog, error, status, code
):
    monkeypatch.setattr(worker, "call_ml", Mock(side_effect=error))
    worker.execute_job.run(queued_job["job_id"])
    result = client.get(queued_job["status_url"])
    assert result.json()["status"] == status
    assert result.json()["error"]["code"] == code
    assert "private output" not in result.text + caplog.text
    assert result.json()["output_document_token"] is None
    with database() as db:
        job = db.get(Job, UUID(queued_job["job_id"]))
        assert job.phase == "done" and job.finished_at is not None
        assert job.input_snapshot == {}
    assert read(client, queued_job)["document"] is None


def test_result_conflict_preserves_current_document(client, database, queued_job, document):
    identifier = UUID(queued_job["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.attempt_token = "running", "current"
        presentation = db.get(Presentation, job.presentation_id)
        presentation.document, presentation.document_token = document, "newer-document"
        presentation.slide_count = len(document["slides"])
    before = read(client, queued_job)
    assert not worker.publish_result(identifier, "current", {**document, "title": "Stale output"})
    after = read(client, queued_job)
    assert after["document"] == before["document"]
    assert after["document_token"] == "newer-document"
    assert after["requested_slide_count"] == before["requested_slide_count"]
    assert after["active_job"] is None
    with database() as db:
        job = db.get(Job, identifier)
        assert (job.status, job.error_code, job.phase) == ("failed", "DOCUMENT_CONFLICT", "done")
        assert job.input_snapshot == {} and job.output_document_token is None


def test_replaced_attempt_discards_ml_result(database, queued_job, document, monkeypatch):
    identifier = UUID(queued_job["job_id"])

    def replace_attempt(*args):
        with database() as db, db.begin():
            db.get(Job, identifier).attempt_token = "replacement"
        return document

    monkeypatch.setattr(worker, "call_ml", replace_attempt)
    publish = Mock()
    monkeypatch.setattr(worker, "publish_result", publish)
    worker.execute_job.run(str(identifier))
    publish.assert_not_called()
    with database() as db:
        job = db.get(Job, identifier)
        assert (job.status, job.attempt_token, job.phase) == ("running", "replacement", "ml")
        assert job.input_snapshot
