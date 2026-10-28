import copy
from uuid import UUID

import pytest
from conftest import generate, headers, register
from sqlalchemy import event
from test_api import execute, read

from app.db.engine import async_sessions
from app.db.models import Job, utcnow
from app.worker import publish_result


@pytest.mark.parametrize("regeneration", [False, True])
def test_current_keeps_document_and_active_job_in_one_snapshot(
    client, database, document, regeneration
):
    _, token = register(client)
    accepted = generate(client, token).json()
    if regeneration:
        assert execute(client, accepted)["status"] == "succeeded"
    before = read(client, accepted)
    if regeneration:
        accepted = client.post(
            f"/api/v1/presentations/{accepted['presentation_id']}/generations",
            json={
                "text": "Новый исходный доклад " * 20,
                "slideCount": 12,
                "base_document_token": before["document_token"],
            },
            headers=headers(token, "regeneration"),
        ).json()
    identifier = UUID(accepted["job_id"])
    with database() as db, db.begin():
        job = db.get(Job, identifier)
        job.status, job.phase, job.attempt_token = "running", "ml", "current-read"
        job.started_at = job.heartbeat_at = utcnow()
    output = copy.deepcopy(document)
    output["title"] = "Новый результат"
    published = []

    def finish_after_document_read(connection, cursor, statement, parameters, context, many):
        if "FROM presentations" in statement and not published:
            # Снимок SELECT уже получен, но ответ ещё не собран. Второй SELECT
            # при READ COMMITTED увидел бы уже завершённое задание.
            published.append(publish_result(identifier, "current-read", output))

    engine = async_sessions().kw["bind"].sync_engine
    event.listen(engine, "after_cursor_execute", finish_after_document_read)
    try:
        observed = read(client, accepted)
    finally:
        event.remove(engine, "after_cursor_execute", finish_after_document_read)

    assert published == [True]
    assert observed["document"] == before["document"]
    assert observed["document_token"] == before["document_token"]
    assert observed["requested_slide_count"] == before["requested_slide_count"]
    assert observed["slide_count"] == before["slide_count"]
    assert observed["active_job"] == accepted

    after = read(client, accepted)
    assert after["document"] == output
    assert after["document_token"] != before["document_token"]
    assert after["requested_slide_count"] == (12 if regeneration else 8)
    assert after["slide_count"] == len(output["slides"])
    assert after["active_job"] is None
