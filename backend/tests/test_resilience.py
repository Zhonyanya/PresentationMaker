import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from conftest import generate, headers, register
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_api import execute, read

from app import worker
from app.db.models import Job, Presentation, utcnow


def test_concurrent_first_generation_same_key(client, database):
    _, token = register(client)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: generate(client, token), range(4)))
    assert all(r.status_code == 202 for r in results)
    assert len({r.json()["job_id"] for r in results}) == 1
    with database() as db:
        assert len(list(db.scalars(select(Job)))) == 1
        assert len(list(db.scalars(select(Presentation)))) == 1


def test_concurrent_distinct_revisions(client):
    _, token = register(client)
    accepted = generate(client, token).json()
    execute(client, accepted)
    current = read(client, accepted)
    path = f"/api/v1/presentations/{accepted['presentation_id']}/revisions"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda n: client.post(
                    path,
                    json={
                        "instruction": "Правка",
                        "base_document_token": current["document_token"],
                    },
                    headers=headers(token, f"rev-{n}"),
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [202, 409]


@pytest.mark.parametrize("invalid", ["layout", "scope", "identity", "excessive"])
def test_invalid_revision_preserves_document_and_metadata(client, database, monkeypatch, invalid):
    _, token = register(client)
    accepted = generate(client, token).json()
    execute(client, accepted)
    before = read(client, accepted)
    path = f"/api/v1/presentations/{accepted['presentation_id']}/revisions"
    revised = client.post(
        path,
        json={
            "instruction": "Правка",
            "base_document_token": before["document_token"],
            "target_slide_numbers": [3],
        },
        headers=headers(token, "invalid"),
    ).json()
    output = copy.deepcopy(before["document"])
    if invalid == "layout":
        output["slides"][2]["layout"] = "html"
    elif invalid == "scope":
        output["slides"][1]["title"] = "Не выбранный слайд"
    elif invalid == "identity":
        output["slides"][2]["id"] = output["slides"][1]["id"]
    else:
        output["title"] = "x" * 8_000_001
    monkeypatch.setattr(worker, "call_ml", lambda *args: output)
    assert execute(client, revised)["error"]["code"] == "INVALID_ML_RESPONSE"
    after = read(client, accepted)
    assert before["document"] == after["document"]
    assert before["document_token"] == after["document_token"]
    assert before["requested_slide_count"] == after["requested_slide_count"]


@pytest.mark.parametrize("targeted", [False, True])
@pytest.mark.parametrize("change", ["rename", "move", "insert", "delete"])
def test_revision_identity_failure_preserves_entire_current_state(
    client, database, monkeypatch, targeted, change
):
    _, token = register(client)
    accepted = generate(client, token).json()
    assert execute(client, accepted)["status"] == "succeeded"
    before = read(client, accepted)
    identifier = UUID(accepted["presentation_id"])
    with database() as db:
        presentation = db.get(Presentation, identifier)
        source_text, updated_at = presentation.source_text, presentation.updated_at
    body = {"instruction": "Исправь опечатку", "base_document_token": before["document_token"]}
    if targeted:
        body["target_slide_numbers"] = [3]
    response = client.post(
        f"/api/v1/presentations/{identifier}/revisions",
        json=body,
        headers=headers(token, "identity-check"),
    )
    assert response.status_code == 202
    revision = response.json()
    output = copy.deepcopy(before["document"])
    slides = output["slides"]
    if change == "rename":
        slides[2]["id"] = "replacement-id"
    elif change == "move":
        slides.insert(4, slides.pop(2))
    elif change == "insert":
        slides.append({**slides[2], "id": "new-slide"})
    else:
        slides.pop(2)
    # Проверяем защиту самого воркера, даже если дочерний ML-процесс её обошёл.
    monkeypatch.setattr(worker, "call_ml", lambda *args: output)
    status = execute(client, revision)
    assert status["status"] == "failed"
    assert status["error"]["code"] == "INVALID_ML_RESPONSE"
    assert status["output_document_token"] is None
    assert read(client, accepted) == before
    with database() as db:
        presentation = db.get(Presentation, identifier)
        assert presentation.source_text == source_text
        assert presentation.updated_at == updated_at


def test_full_regeneration_can_replace_slide_ids(client, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    assert execute(client, accepted)["status"] == "succeeded"
    before = read(client, accepted)
    response = client.post(
        f"/api/v1/presentations/{accepted['presentation_id']}/generations",
        json={
            "text": "Новый доклад " * 20,
            "slideCount": 10,
            "base_document_token": before["document_token"],
        },
        headers=headers(token, "replace-document"),
    )
    assert response.status_code == 202
    output = copy.deepcopy(before["document"])
    for index, slide in enumerate(output["slides"]):
        slide["id"] = f"regenerated-{index}"
    monkeypatch.setattr(worker, "call_ml", lambda *args: output)
    assert execute(client, response.json())["status"] == "succeeded"
    after = read(client, accepted)
    assert after["document"] == output
    assert after["document_token"] != before["document_token"]
    assert after["requested_slide_count"] == 10


def test_regeneration_failure_keeps_source_and_requested_count(client, database, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    execute(client, accepted)
    current = read(client, accepted)
    path = f"/api/v1/presentations/{accepted['presentation_id']}/generations"
    accepted2 = client.post(
        path,
        json={
            "text": "Новый текст " * 20,
            "slideCount": 15,
            "base_document_token": current["document_token"],
        },
        headers=headers(token, "regenerate"),
    ).json()
    monkeypatch.setenv("PM_FIXTURE_FAILURE", "true")
    assert execute(client, accepted2)["status"] == "failed"
    assert read(client, accepted)["requested_slide_count"] == 8
    with database() as db:
        presentation = db.get(Presentation, UUID(accepted["presentation_id"]))
        assert presentation.source_text == ("Доклад " * 30).strip()


def test_failed_initial_generation_retry_without_base_token(client, database, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    monkeypatch.setenv("PM_FIXTURE_FAILURE", "true")
    assert execute(client, accepted)["status"] == "failed"
    monkeypatch.delenv("PM_FIXTURE_FAILURE")
    path = f"/api/v1/presentations/{accepted['presentation_id']}/generations"
    response = client.post(
        path, json={"text": "Доклад " * 30, "slideCount": 12}, headers=headers(token, "retry")
    )
    assert response.status_code == 202
    assert execute(client, response.json())["status"] == "succeeded"
    assert read(client, accepted)["requested_slide_count"] == 12


def test_entire_ml_process_deadline(client, database, monkeypatch):
    _, token = register(client)
    accepted = generate(client, token).json()
    with database() as db, db.begin():
        db.get(Job, UUID(accepted["job_id"])).deadline_at = utcnow() + timedelta(seconds=1)
    monkeypatch.setenv("PM_FIXTURE_DELAY", "5")
    assert execute(client, accepted)["status"] == "timed_out"
    assert read(client, accepted)["document"] is None


def test_database_null_consistency_constraint(client, database, document):
    _, token = register(client)
    accepted = generate(client, token).json()
    with pytest.raises(IntegrityError), database() as db, db.begin():
        row = db.get(Presentation, UUID(accepted["presentation_id"]))
        row.document, row.document_token = document, "token"
        row.slide_count = None
        db.flush()


def test_quota_rejects_before_creating_job(client, database):
    _, token = register(client)
    assert generate(client, token, "one").status_code == 202
    assert generate(client, token, "two").status_code == 202
    assert generate(client, token, "three").status_code == 429
    with database() as db:
        assert len(list(db.scalars(select(Job)))) == 2


def test_wrong_attempt_cannot_publish(client, database, document):
    _, token = register(client)
    accepted = generate(client, token).json()
    with database() as db, db.begin():
        job = db.get(Job, UUID(accepted["job_id"]))
        job.status, job.attempt_token, job.heartbeat_at = "running", "new-attempt", utcnow()
    assert not worker.publish_result(UUID(accepted["job_id"]), "old-attempt", document)
    assert read(client, accepted)["document"] is None
