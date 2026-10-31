"""ML contract checks with a deterministic provider boundary, no network calls."""

import copy
import importlib
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def ml():
    return importlib.import_module("presentation_ml")


@pytest.fixture
def inputs():
    return dict(text="Исходный доклад. " * 12, slideCount=6, job_id="test-job",
                deadline=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())


def provider(monkeypatch, ml, result):
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        return copy.deepcopy(result)

    monkeypatch.setattr(ml, "request_document", request)
    return calls


def test_generate_single_request(monkeypatch, ml, inputs, document):
    calls = provider(monkeypatch, ml, document)
    result = ml.generate(**inputs, title="Название")
    assert len(calls) == 1
    assert result["slides"][0]["layout"] == "title"
    assert result["slides"][-1]["layout"] == "closing"
    assert "Название" in calls[0]["payload"]["title"]


def test_revision_schema_requires_slide_ids(ml):
    schema = ml._schema(revision=True)
    for definition in schema['$defs'].values():
        if 'layout' in definition.get('properties', {}):
            assert 'id' in definition['required']


def test_generate_adds_structural_slides_without_losing_content(monkeypatch, ml, inputs):
    candidate = {'title': 'Доклад', 'slides': [
        {'layout': 'bullets', 'title': 'Результаты', 'bullets': ['12 студентов']},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    assert [s['layout'] for s in result['slides']] == ['title', 'bullets', 'closing']
    assert result['slides'][1]['bullets'] == ['12 студентов']
    assert len(candidate['slides']) == 1


def revise(ml, inputs, document, targets=None):
    return ml.revise(**inputs, document=document, instruction="Сократи текст",
                     target_slide_numbers=targets,
                     target_slide_ids=[document["slides"][i - 1]["id"] for i in targets]
                     if targets else None)


def test_targeted_revision_preserves_snapshot(monkeypatch, ml, inputs, document):
    original = copy.deepcopy(document)
    result = copy.deepcopy(document)
    result["slides"][2]["notes"] = "Короче"
    result["slides"][1]["title"] = "Посторонняя правка модели"
    result["title"] = "Посторонний заголовок"
    provider(monkeypatch, ml, result)
    revised = revise(ml, inputs, document, [3])
    assert document == original
    assert revised["slides"][2]["notes"] == "Короче"
    assert revised["slides"][1] == original["slides"][1]
    assert revised["title"] == original["title"]


def test_global_revision_can_change_title(monkeypatch, ml, inputs, document):
    result = copy.deepcopy(document)
    result["title"] = "Новое название"
    provider(monkeypatch, ml, result)
    assert revise(ml, inputs, document)["title"] == "Новое название"


def test_revision_rejects_identity_changes(monkeypatch, ml, inputs, document):
    result = copy.deepcopy(document)
    result["slides"].reverse()
    provider(monkeypatch, ml, result)
    with pytest.raises(ValueError):
        revise(ml, inputs, document)


def test_unsupported_operation(monkeypatch, ml, inputs, document):
    provider(monkeypatch, ml, {"unsupported": True})
    with pytest.raises(NotImplementedError):
        revise(ml, inputs, document)


def test_expired_deadline_never_calls_provider(monkeypatch, ml, inputs, document):
    calls = provider(monkeypatch, ml, document)
    inputs["deadline"] = datetime.now(UTC).isoformat()
    with pytest.raises(TimeoutError):
        ml.generate(**inputs)
    assert not calls


def test_bad_targets_never_call_provider(monkeypatch, ml, inputs, document):
    calls = provider(monkeypatch, ml, document)
    with pytest.raises(ValueError):
        ml.revise(**inputs, document=document, instruction="Сократи",
                  target_slide_numbers=[1], target_slide_ids=["wrong"])
    assert not calls


def test_publication_reserve_is_not_an_expired_deadline(monkeypatch, ml, inputs, document):
    calls = provider(monkeypatch, ml, document)
    inputs["deadline"] = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    with pytest.raises(RuntimeError, match="Insufficient"):
        ml.generate(**inputs)
    assert not calls


def test_all_explicit_targets_still_freeze_title(monkeypatch, ml, inputs, document):
    result = copy.deepcopy(document)
    result["title"] = "Не должно сохраниться"
    provider(monkeypatch, ml, result)
    assert revise(ml, inputs, document, list(range(1, 7)))["title"] == document["title"]


def test_sdk_transport_disables_retries_and_validates_payload(monkeypatch, document):
    import json
    from types import SimpleNamespace

    import gigachat
    from gigachat.models import Chat

    from presentation_ml.transport import request_document

    options = {}

    class FakeClient:
        def __init__(self, **kwargs):
            options.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def chat(self, payload):
            Chat.model_validate(payload)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=json.dumps(document)))])

    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "synthetic-test-key")
    monkeypatch.setenv("GIGACHAT_MODEL", "test-model")
    monkeypatch.setattr(gigachat, "GigaChat", FakeClient)
    assert request_document(system="test", payload={}, schema={"type": "object"},
                            timeout=60) == document
    assert options["verify_ssl_certs"] is True
    assert options["max_retries"] == 0


@pytest.mark.parametrize(("reason", "content", "error"), [
    ("length", "{}", RuntimeError),
    ("blacklist", "{}", RuntimeError),
    ("stop", "not JSON", ValueError),
    ("stop", "x" * 8_000_001, ValueError),
])
def test_transport_rejects_incomplete_or_invalid_output(monkeypatch, reason, content, error):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import gigachat

    from presentation_ml.transport import request_document

    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=reason, message=SimpleNamespace(content=content))])
    monkeypatch.setattr(gigachat, "GigaChat", lambda **_: client)
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "synthetic-test-key")
    monkeypatch.setenv("GIGACHAT_MODEL", "test-model")
    with pytest.raises(error):
        request_document(system="test", payload={}, schema={}, timeout=60)
    assert client.chat.call_count == 1
