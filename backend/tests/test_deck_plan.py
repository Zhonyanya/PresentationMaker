from datetime import UTC, datetime, timedelta

import pytest

import presentation_ml

SOURCE = {"blocks": [
    {"kind": "text", "id": "p1-text", "page": 1,
     "text": "Архив открыт по предварительной записи."},
    {"kind": "text", "id": "p2-text", "page": 2,
     "text": "В субботу выдача заканчивается в 14:00."},
]}


def intent(takeaway, *evidence_ids):
    return {"goal": "Объяснить порядок доступа", "takeaway": takeaway,
            "visual_intent": "Порядок посещения", "evidence_ids": list(evidence_ids)}


def planned_generation(monkeypatch, reply, *, slide_count=5, inspect_request=None, source=SOURCE):
    monkeypatch.setenv("PM_ML_PROMPT_VERSION", "v4")
    calls = []

    def respond(**request):
        calls.append(request)
        if inspect_request:
            inspect_request(request)
        return reply

    monkeypatch.setattr(presentation_ml, "request_document", respond)
    result = presentation_ml._generate(
        text="", source=source, slideCount=slide_count, job_id="test",
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert len(calls) == 1
    return result


def test_generation_binds_intent_to_source_without_graph_facts(monkeypatch):
    def inspect(request):
        assert "предварительной записи" in request["payload"]["text"]
        anchors = request["payload"]["source_anchors"]
        assert [anchor["source"]["block_id"] for anchor in anchors] == ["p1-text", "p2-text"]
        assert "plan" in request["schema"]["required"]

    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Правила доступа"), intent("Требуется запись", "block-1"),
                 intent("Проверьте время выдачи", "block-2")],
        "slides": [
            {"layout": "title", "title": "Архив"},
            {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            {"layout": "closing", "title": "Порядок доступа", "subtitle": "Выдача до 14:00."},
        ],
    }, inspect_request=inspect)
    assert set(result.document) == {"title", "slides"}
    assert [s.slide_id for s in result.plan.slides] == [s["id"] for s in result.document["slides"]]
    (content,) = result.plan.slides[1].intents
    assert content.goal == "Объяснить порядок доступа"
    assert content.takeaway == "Требуется запись"
    assert content.visual_intent == "Порядок посещения"
    (evidence,) = content.evidence
    assert (evidence.id, evidence.block_id, evidence.page) == ("block-1", "p1-text", 1)


@pytest.mark.parametrize("evidence_ids", [("invented",), ()])
def test_generation_rejects_unresolved_evidence_on_content_slide(monkeypatch, evidence_ids):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("Требуется запись", *evidence_ids)],
            "slides": [{"layout": "text", "title": "Запись", "body": "Запишитесь заранее."}],
        })


@pytest.mark.parametrize("long_source", [False, True])
def test_compaction_preserves_intents_and_binds_inserted_boundaries(monkeypatch, long_source):
    first, second = SOURCE["blocks"]
    source = {"blocks": [{**first, "text": first["text"] + " Справки в архиве." * 100}, second]}
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Требуется запись", "block-1"),
                 intent("Выдача до 14:00", "block-2")],
        "slides": [
            {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            {"layout": "text", "title": "Суббота", "body": "Выдача до 14:00."},
        ],
    }, slide_count=3, source=source if long_source else SOURCE)
    slides = result.document["slides"]
    assert [slide["layout"] for slide in slides] == ["title", "text", "closing"]
    assert [slide.slide_id for slide in result.plan.slides] == [slide["id"] for slide in slides]
    assert [part.takeaway for part in result.plan.slides[1].intents] == [
        "Требуется запись", "Выдача до 14:00",
    ]
    assert result.plan.slides[2].intents[0].evidence[0].block_id == "p2-text"


def test_joined_heading_keeps_the_heading_and_content_intents(monkeypatch):
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Правила доступа"), intent("Требуется запись", "block-1")],
        "slides": [
            {"layout": "section", "title": "Правила доступа"},
            {"layout": "text", "title": "", "body": "Запишитесь заранее."},
        ],
    })
    joined = result.plan.slides[1]
    assert joined.slide_id == result.document["slides"][1]["id"]
    assert [part.takeaway for part in joined.intents] == ["Правила доступа", "Требуется запись"]


def test_evidence_can_reference_a_block_outside_the_excerpt_sample(monkeypatch):
    source = {"blocks": [
        {"kind": "text", "id": f"p{i}", "text": f"Справочная запись номер {i}."}
        for i in range(1, 41)
    ]}

    def inspect(request):
        payload = request["payload"]
        assert "block-5" not in {item["id"] for item in payload["source_anchors"]}
        assert "[block-5]\nСправочная запись номер 5." in payload["text"]

    result = planned_generation(monkeypatch, {
        "title": "Справочник",
        "plan": [intent("Справочная запись", "block-5")],
        "slides": [{"layout": "text", "title": "Запись", "body": "Справочная запись номер 5."}],
    }, source=source, inspect_request=inspect)
    assert result.plan.slides[1].intents[0].evidence[0].block_id == "p5"


def test_evidence_addresses_the_end_of_a_long_text_block(monkeypatch):
    tail = "Заявки на отпуск принимаются до 14:00."
    full_text = "Справочная информация. " * 64 + tail
    source = {"blocks": [{"kind": "text", "id": "text-1", "text": full_text}]}

    def inspect(request):
        text = request["payload"]["text"]
        assert "[block-1-part-2]" in text
        assert text.endswith(tail)

    result = planned_generation(monkeypatch, {
        "title": "Порядок подачи",
        "plan": [intent("Срок подачи", "block-1-part-2")],
        "slides": [{"layout": "text", "title": "Срок", "body": tail}],
    }, source=source, inspect_request=inspect)
    (ref,) = result.plan.slides[1].intents[0].evidence
    assert ref.block_id == "text-1"
    assert 0 < ref.start < ref.end == len(full_text)
    assert full_text[ref.start:ref.end].endswith(tail)


@pytest.mark.parametrize("layout", ["section", "closing", "title"])
def test_boundary_with_substantive_subtitle_requires_evidence(monkeypatch, layout):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("В 14:00"), intent("Требуется запись", "block-1")],
            "slides": [
                {"layout": layout, "title": "Часы работы", "subtitle": "Выдача до 14:00."},
                {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            ],
        })


def test_compaction_rejects_content_without_evidence_even_after_layout_changes(monkeypatch):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("Введение"), intent("Суббота"), intent("Итог", "block-2")],
            "slides": [
                {"layout": "section", "title": "Введение"},
                {"layout": "section", "title": "Суббота"},
                {"layout": "closing", "title": "Часы работы", "subtitle": "Выдача до 14:00."},
            ],
        }, slide_count=3)
