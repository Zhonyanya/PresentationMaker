from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from conftest import headers, register
from pydantic import ValidationError

import presentation_ml
from app.db.models import Job, Presentation
from app.presentations.schemas import GenerateRequest

SOURCE = {
    "blocks": [
        {"id": "docx-1", "kind": "text", "text": "Условия допуска указаны в приложении."},
        {
            "id": "docx-2", "kind": "table", "number": "18",
            "rows": [
                ["Группа", "Количество участников", None],
                [None, "2022", "2023"],
                ["Школы", "20", "35"],
            ],
        },
    ],
}


def test_generate_accepts_structured_input_without_requiring_a_second_copy_of_text():
    request = GenerateRequest.model_validate({"source": SOURCE, "slideCount": 6})
    assert request.source.blocks[1].rows[2] == ("Школы", "20", "35")


def test_generate_sends_full_prose_alongside_table_facts(monkeypatch):
    captured = {}
    text = "Архив доступен только по предварительной записи."
    source = {"blocks": [*SOURCE["blocks"], {"id": "tail", "kind": "text", "text": text}]}
    monkeypatch.setenv("PM_ML_PROMPT_VERSION", "v4")

    def respond(**request):
        captured.update(request["payload"])
        intent = {
            "goal": "Описать участие", "takeaway": "Условия указаны в приложении.",
            "visual_intent": "Краткая сводка", "evidence_ids": [],
        }
        return {
            "title": "Учебный отчёт",
            "plan": [intent, {**intent, "evidence_ids": ["fact-1"]}, intent],
            "slides": [
                {"layout": "title", "title": "Учебный отчёт"},
                {"layout": "text", "title": "Школы", "body": "2022 — 20; 2023 — 35"},
                {"layout": "closing", "title": "Учебный отчёт"},
            ],
        }

    monkeypatch.setattr(presentation_ml, "request_document", respond)
    result = presentation_ml._generate(
        text=text, source=source, slideCount=6, job_id="test",
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert captured["text"].endswith(text)
    (fact,) = captured["source_facts"]
    assert fact["source"] == {"block_id": "docx-2", "table_number": "18", "row": 3}
    assert fact["source_row"] == ["Школы", "20", "35"]
    (evidence,) = result.plan.slides[1].intents[0].evidence
    assert (evidence.id, evidence.block_id, evidence.row) == ("fact-1", "docx-2", 3)


def test_generate_comparisons_uses_requested_slide_budget(monkeypatch):
    table = SOURCE["blocks"][1]
    source = {"blocks": [{**table, "rows": [
        *table["rows"][:2], *[[f"Группа {n}", "20", "35"] for n in range(5)],
    ]}]}

    def respond(**request):
        assert "up to 4" in request["system"]
        assert request["schema"]["properties"]["comparisons"]["maxItems"] == 4
        candidates = request["payload"]["source_facts"]
        assert len(candidates) == 5
        return {"comparisons": [
            {"fact_id": row["id"], "group": row["subject"], "metric": row["target"],
             **row["qualifiers"]}
            for row in candidates[:4]
        ]}

    monkeypatch.setattr(presentation_ml, "request_document", respond)
    result = presentation_ml.generate(
        text="", source=source, mode="comparisons", slideCount=6, job_id="test",
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert [slide["layout"] for slide in result["slides"]] == ["title", *["text"] * 4, "closing"]


@pytest.mark.parametrize("source", [
    {"blocks": [SOURCE["blocks"][0]] * 2},
    {"blocks": [{"id": "bad", "kind": "text", "text": "Текст\x00"}]},
    {"blocks": [{"id": "picture", "kind": "illustration", "locator": "picture"}]},
])
def test_generate_rejects_invalid_or_contentless_sources(source):
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({"source": source, "slideCount": 6})


def test_source_snapshot_survives_publish_and_is_used_for_revision_and_deleted(client, database):
    from app.worker import execute_job

    _, csrf = register(client)
    result = client.post(
        "/api/v1/presentations", json={"source": SOURCE, "slideCount": 6},
        headers=headers(csrf, "source-generation"),
    )
    assert result.status_code == 202
    job_id = result.json()["job_id"]
    identifier = result.json()["presentation_id"]
    with database() as db:
        snapshot = db.get(Job, UUID(job_id)).input_snapshot
        assert snapshot["source"]["blocks"][1]["rows"][2] == ["Школы", "20", "35"]
    execute_job.run(job_id)
    current = client.get(f"/api/v1/presentations/{identifier}").json()
    result = client.post(
        f"/api/v1/presentations/{identifier}/revisions",
        json={"instruction": "Уточни условия", "base_document_token": current["document_token"]},
        headers=headers(csrf, "source-revision"),
    )
    assert result.status_code == 202
    revision_id = result.json()["job_id"]
    with database() as db:
        assert db.get(Job, UUID(revision_id)).input_snapshot["source"] == snapshot["source"]
    execute_job.run(revision_id)
    deleted = client.delete(f"/api/v1/presentations/{identifier}", headers=headers(csrf))
    assert deleted.status_code == 204
    with database() as db:
        assert db.get(Presentation, UUID(identifier)).source_document is None
