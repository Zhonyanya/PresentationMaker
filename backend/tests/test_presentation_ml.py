"""ML contract checks with a deterministic provider boundary, no network calls."""

import copy
import importlib
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError


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
        if kwargs['payload']['operation'] == 'revise':
            if result == {'unsupported': True}:
                return {'status': 'unsupported', 'document': None}
            response = copy.deepcopy(result)
            if kwargs['payload'].get('response_scope') == 'selected_slides':
                wanted = kwargs['payload']['target_slide_ids']
                response['slides'] = [s for s in response['slides'] if s['id'] in wanted]
            return {'status': 'applied', 'document': response}
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


@pytest.mark.parametrize('count', [3, 7, 8])
def test_long_generation_budget_includes_cover_and_closing(monkeypatch, ml, inputs, count):
    candidate = {'title': 'Pilot results', 'slides': [
        {'layout': 'title', 'title': 'Pilot results'},
        *[{'layout': 'text', 'title': f'Result {i}', 'body': f'Observed fact {i}'}
          for i in range(count - 2)],
        {'layout': 'closing', 'title': 'Conclusion'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=count))
    assert len(result['slides']) == count
    assert calls[0]['schema']['properties']['slides']['maxItems'] == count
    assert 'generation-wire-v1' in calls[0]['system']
    assert 'document.title' in calls[0]['system']
    assert len(calls) == 1


@pytest.mark.parametrize('missing_boundaries', [False, True])
def test_long_generation_rejects_final_overflow_without_truncation_or_retry(
    monkeypatch, ml, inputs, missing_boundaries,
):
    slides = [{'layout': 'text', 'title': f'Result {i}', 'body': f'Fact {i}. ' * 150}
              for i in range(6)]
    if not missing_boundaries:
        slides = [{'layout': 'title', 'title': 'Pilot'}, *slides,
                  {'layout': 'closing', 'title': 'Conclusion'}]
    candidate = {'title': 'Pilot', 'slides': slides}
    original = copy.deepcopy(candidate)
    calls = provider(monkeypatch, ml, candidate)
    with pytest.raises(ValueError, match='slide budget'):
        ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=7))
    assert len(calls) == 1
    assert candidate == original


def test_generation_fits_missing_closing_without_losing_visible_text_or_notes(
    monkeypatch, ml, inputs,
):
    candidate = {'title': 'Pilot results', 'slides': [
        {'layout': 'title', 'title': 'Pilot results'},
        {'layout': 'section', 'title': 'Scope', 'subtitle': 'One canteen; four weeks.',
         'notes': 'No control group.'},
        *[{'layout': 'bullets', 'title': f'Result {i}',
           'bullets': [f'{i} measurements', 'Budget not approved'], 'notes': f'Detail {i}'}
          for i in range(1, 6)],
    ]}
    original = copy.deepcopy(candidate)
    calls = provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=7))
    assert len(result['slides']) == 7
    assert result['slides'][0]['layout'] == 'title'
    assert result['slides'][-1]['layout'] == 'closing'
    visible = '\n'.join(ml._slide_text(s) for s in result['slides'])
    notes = '\n'.join(s.get('notes', '') for s in result['slides'])
    for slide in original['slides']:
        for fragment in ml._slide_text(slide).splitlines():
            assert fragment in visible
        if slide.get('notes'):
            assert slide['notes'] in notes
    assert candidate == original
    assert len(calls) == 1


@pytest.mark.parametrize('requested_title', [None, 'Food waste pilot'])
def test_generated_cover_names_the_document_subject(monkeypatch, ml, inputs, requested_title):
    candidate = {'title': 'Reducing food waste', 'slides': [
        {'layout': 'title', 'title': 'Problem and goal', 'subtitle': 'March 2026',
         'caption': 'University canteen', 'notes': 'Scope: one canteen.'},
        {'layout': 'text', 'title': 'Results', 'body': '48 to 33 kg per day.'},
        {'layout': 'closing', 'title': 'Conclusion'},
    ]}
    original = copy.deepcopy(candidate)
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs, title=requested_title)
    expected = requested_title or candidate['title']
    assert result['title'] == expected
    assert result['slides'][0]['title'] == expected
    for key in ('subtitle', 'caption', 'notes'):
        assert result['slides'][0][key] == candidate['slides'][0][key]
    assert candidate == original


def test_budget_merge_preserves_column_labels_and_notes(monkeypatch, ml, inputs):
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'title', 'title': 'Pilot'},
        {'layout': 'two-column', 'title': 'Comparison',
         'leftTitle': 'Before', 'left': ['48 kg/day'],
         'rightTitle': 'After', 'right': ['33 kg/day'], 'notes': 'One site only.'},
        {'layout': 'bullets', 'title': 'Limits', 'bullets': ['Budget not approved'],
         'notes': 'No control group.'},
        {'layout': 'closing', 'title': 'Conclusion'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=3))
    assert len(result['slides']) == 3
    merged = result['slides'][1]
    assert merged['title'] == 'Comparison'
    assert 'Comparison' not in merged['body']
    for fragment in ['Before', '48 kg/day', 'After', '33 kg/day',
                     'Limits', 'Budget not approved']:
        assert fragment in merged['body']
    assert 'One site only.' in merged['notes']
    assert 'No control group.' in merged['notes']
    assert len(calls) == 1


@pytest.mark.parametrize('large_notes', [False, True])
def test_budget_merge_rejects_utf16_or_notes_overflow(monkeypatch, ml, inputs, large_notes):
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'title', 'title': 'Pilot'},
        *[{'layout': 'text', 'title': f'Fact {i}',
           'body': 'Short fact.' if large_notes else '\U0001f600' * 220,
           'notes': 'N' * 5001 if large_notes else 'Short note.'} for i in range(2)],
        {'layout': 'closing', 'title': 'Conclusion'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    with pytest.raises(ValueError, match='readable slide budget'):
        ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=3))
    assert len(calls) == 1


def test_budget_merge_finds_valid_partition_instead_of_greedy_dead_end(monkeypatch, ml, inputs):
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'title', 'title': 'Pilot'},
        *[{'layout': 'text', 'title': str(i), 'body': str(i) * size}
          for i, size in enumerate([600, 190, 190, 600])],
        {'layout': 'closing', 'title': 'Conclusion'},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, text='Source material. ' * 100, slideCount=4))
    assert len(result['slides']) == 4
    assert '0' * 600 in result['slides'][1]['body']
    assert '1' * 190 in result['slides'][1]['body']
    assert '2' * 190 in result['slides'][2]['body']
    assert '3' * 600 in result['slides'][2]['body']


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


def test_text_presentation_style_does_not_restrict_command_revision(monkeypatch, ml, inputs):
    document = {"title": "Архив", "slides": [{
        "id": "access", "layout": "text", "title": "Запись",
        "body": "Запись до 14:00.", "textStyle": "lead",
    }]}
    response = {"title": "Архив", "slides": [{
        "id": "access", "layout": "text", "title": "Запись",
        "body": "Запись до 15:00.", "textStyle": "steps",
    }]}
    provider(monkeypatch, ml, response)
    revised = revise(ml, inputs, document, [1])
    assert revised["slides"] == [{**response["slides"][0], "textStyle": "lead"}]


def test_revising_tree_body_removes_previously_verified_style(monkeypatch, ml, inputs):
    original = {"title": "Архив", "slides": [{
        "id": "access", "layout": "text", "title": "Запись", "textStyle": "tree",
        "body": "Доступ\nЧитальный зал\n  Подлинники\nДистанционно\n  Копии",
    }]}
    candidate = copy.deepcopy(original)
    candidate["slides"][0]["body"] = "Запишитесь заранее."
    provider(monkeypatch, ml, candidate)
    result = revise(ml, inputs, original, [1])
    assert result["slides"][0]["body"] == "Запишитесь заранее."
    assert "textStyle" not in result["slides"][0]


@pytest.fixture
def comparison_document():
    return {"title": "Пилот", "slides": [
        {"id": "cover", "layout": "title", "title": "Пилот"},
        {"id": "data", "layout": "text", "title": "Занятия по площадкам",
         "body": "Северная площадка провела 63 занятия в 2025 году. Подробности в отчёте.",
         "composition": {
             "kind": "comparison", "categories": ["Северная", "Центральная"],
             "series": [{"label": "2024", "values": [48, 72]},
                        {"label": "2025", "values": [63, 69]}],
         }},
        {"id": "end", "layout": "closing", "title": "Итог", "subtitle": "Данные пилота"},
    ]}


@pytest.mark.parametrize("generation", [True, False])
@pytest.mark.parametrize("composition", [None, {"kind": "unexpected"}])
def test_provider_cannot_supply_structured_visuals(monkeypatch, ml, inputs,
                                                   comparison_document, generation, composition):
    candidate = copy.deepcopy(comparison_document)
    candidate["slides"][1].update(sourceMaterial={"kind": "table", "page": 1,
        "rows": [["Группа", "Занятия"], ["Северная", "99"]]}, composition=composition)
    provider(monkeypatch, ml, candidate)
    result = (ml.generate(**inputs) if generation else
              revise(ml, inputs, comparison_document, [2]))
    assert "sourceMaterial" not in result["slides"][1]
    expected = None if generation else comparison_document["slides"][1]["composition"]
    assert result["slides"][1].get("composition") == expected


def test_revision_preserves_saved_source_table(monkeypatch, ml, inputs, comparison_document):
    slide = comparison_document["slides"][1]
    slide.pop("composition")
    slide["sourceMaterial"] = {
        "kind": "table", "page": 1, "rows": [["Площадка", "Итог"], ["Северная", "63"]],
    }
    candidate = copy.deepcopy(comparison_document)
    candidate["slides"][1].pop("sourceMaterial")
    candidate["slides"][1]["title"] = "Итоги"
    provider(monkeypatch, ml, candidate)
    revised = revise(ml, inputs, comparison_document, [2])
    assert revised["slides"][1]["title"] == "Итоги"
    assert revised["slides"][1]["sourceMaterial"] == slide["sourceMaterial"]


@pytest.mark.parametrize("body", [
    "Северная площадка провела 69 занятий в 2025 году.",
    "Северная площадка провела 63 занятия в 2024 году.",
    "Центральная площадка провела 63 занятия в 2025 году.",
    "Северная площадка провела 63% занятий в 2025 году.",
])
def test_revision_rejects_changed_numeric_statement(monkeypatch, ml, inputs,
                                                   comparison_document, body):
    candidate = copy.deepcopy(comparison_document)
    candidate["slides"][1]["body"] = body
    provider(monkeypatch, ml, candidate)
    with pytest.raises(NotImplementedError, match="numeric"):
        revise(ml, inputs, comparison_document, [2])


def test_revision_can_shorten_around_numeric_statement(monkeypatch, ml, inputs,
                                                      comparison_document):
    candidate = copy.deepcopy(comparison_document)
    candidate["slides"][1]["body"] = "Северная площадка провела 63 занятия в 2025 году."
    candidate["slides"][1]["title"] = "Результаты площадок"
    provider(monkeypatch, ml, candidate)
    revised = revise(ml, inputs, comparison_document, [2])
    assert revised == candidate


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


@pytest.mark.parametrize(("reason", "content", "error", "code"), [
    ("length", "{}", AppError, "ML_PROVIDER_INCOMPLETE"),
    ("blacklist", "{}", AppError, "ML_PROVIDER_REJECTED"),
    ("stop", "not JSON", ValueError, None),
    pytest.param("stop", "x" * 8_000_001, ValueError, None, id="oversize-response"),
])
def test_transport_rejects_incomplete_or_invalid_output(monkeypatch, reason, content, error, code):
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
    with pytest.raises(error) as caught:
        request_document(system="test", payload={}, schema={}, timeout=60)
    if code is not None:
        assert caught.value.code == code
    assert client.chat.call_count == 1

def test_revision_schema_fixes_snapshot_slide_count(monkeypatch, ml, inputs, document):
    calls = provider(monkeypatch, ml, document)
    revise(ml, inputs, document)
    slides = calls[0]['schema']['properties']['document']['anyOf'][0]['properties']['slides']
    assert slides['minItems'] == len(document['slides'])
    assert slides['maxItems'] == len(document['slides'])

@pytest.mark.parametrize('status', ['applied', 'unsupported'])
def test_revision_envelope(monkeypatch, ml, inputs, document, status):
    response = {'status': status, 'document': document if status == 'applied' else None}
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        return copy.deepcopy(response)
    monkeypatch.setattr(ml, 'request_document', request)
    if status == 'unsupported':
        with pytest.raises(NotImplementedError):
            revise(ml, inputs, document)
    else:
        assert revise(ml, inputs, document) == document
    schema = calls[0]['schema']
    assert schema['type'] == 'object'
    assert set(schema['required']) == {'status', 'document'}
    assert schema['properties']['status']['enum'] == ['applied', 'unsupported']


@pytest.mark.parametrize('response', [
    {'status': 'applied', 'document': None},
    {'status': 'unknown', 'document': None},
    {'status': 'unsupported', 'document': {'title': 'ambiguous'}},
    {'status': 'unsupported'},
    {'status': 'applied', 'document': None, 'extra': True},
])
def test_revision_rejects_malformed_envelope(monkeypatch, ml, inputs, document, response):
    monkeypatch.setattr(ml, 'request_document', lambda **_: copy.deepcopy(response))
    with pytest.raises(ValueError):
        revise(ml, inputs, document)

@pytest.mark.parametrize('instruction', [
    'Удали четвёртый слайд из презентации.',
    'Добавь новый слайд после второго.',
    'Перемести слайд 4 в конец.',
    'Поменяй местами слайды 2 и 3.',
    'Remove the fourth slide.',
    'Сократи заголовок. Затем удали слайд 4.',
])
def test_explicit_structure_command_refused_without_provider(
        monkeypatch, ml, inputs, document, instruction):
    calls = provider(monkeypatch, ml, document)
    with pytest.raises(NotImplementedError):
        ml.revise(**inputs, document=document, instruction=instruction,
                  target_slide_numbers=None, target_slide_ids=None)
    assert not calls


@pytest.mark.parametrize('instruction', [
    'Удали слово «слайд» из заголовка.',
    'Не удаляй четвёртый слайд, сократи его текст.',
    'Добавь пункт в список слайда.',
    'Do not remove the fourth slide; shorten its title.',
    'Сократи заголовок слайда.',
    'Move slide title into the body.',
    'Add slide title to the second slide.',
    'Напиши в заголовке «Удали четвёртый слайд».',
])
def test_content_or_negated_command_still_reaches_provider(
        monkeypatch, ml, inputs, document, instruction):
    calls = provider(monkeypatch, ml, document)
    ml.revise(**inputs, document=document, instruction=instruction,
              target_slide_numbers=None, target_slide_ids=None)
    assert len(calls) == 1


def test_revision_rejects_deleted_slide(monkeypatch, ml, inputs, document):
    candidate = copy.deepcopy(document)
    candidate['slides'].pop(2)
    provider(monkeypatch, ml, candidate)
    with pytest.raises(ValueError, match='identities or order'):
        revise(ml, inputs, document)

@pytest.mark.parametrize('version', ['v3', 'v4'])
def test_v3_short_source_budget_reaches_provider(monkeypatch, ml, version, inputs, document):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', version)
    candidate = copy.deepcopy(document)
    candidate['slides'] = [document['slides'][i] for i in (0, 1, 2, 5)]
    calls = provider(monkeypatch, ml, candidate)
    ml.generate(**dict(inputs, slideCount=8))
    assert calls[0]['payload']['slideCount'] == 4
    assert calls[0]['schema']['properties']['slides']['maxItems'] == 4


@pytest.mark.parametrize('version', ['v3', 'v4'])
def test_v3_checks_final_count_after_structural_normalization(monkeypatch, ml, version, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', version)
    provider(monkeypatch, ml, {'title': 'Доклад', 'slides': [
        {'layout': 'text', 'title': str(i), 'body': 'Факт ' * 200} for i in range(4)
    ]})
    with pytest.raises(ValueError, match='short-source budget'):
        ml.generate(**dict(inputs, slideCount=8))


@pytest.mark.parametrize('requested_title', [None, 'User heading'])
def test_generated_closing_reuses_content_without_assuming_language(
    monkeypatch, ml, inputs, requested_title,
):
    candidate = {'title': 'Incident review', 'slides': [
        {'layout': 'title', 'title': 'Incident review'},
        {'layout': 'text', 'title': 'Scope', 'body': 'The root cause is unconfirmed.'},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs, title=requested_title)
    assert result['slides'][-1]['layout'] == 'closing'
    assert result['slides'][-1]['title'] == 'Scope'
    assert result['slides'][-1]['subtitle'] == 'The root cause is unconfirmed.'
    assert result['slides'][1] == dict(candidate['slides'][1], id=result['slides'][1]['id'])


def test_generation_repairs_empty_cover_repeat_as_closing(monkeypatch, ml, inputs):
    candidate = {'title': 'Laboratory booking', 'slides': [
        {'layout': 'title', 'title': 'Laboratory booking'},
        {'layout': 'bullets', 'title': 'Pilot results',
         'bullets': ['12 conflicts before; 3 during the pilot.',
                     'One laboratory; wider rollout is not yet approved.'],
         'notes': 'Keep the qualification visible.'},
        {'layout': 'closing', 'title': 'Laboratory booking'},
    ]}
    original = copy.deepcopy(candidate)
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    closing = result['slides'][-1]
    assert closing['title'] == 'Pilot results'
    assert '12 conflicts before; 3 during the pilot.' in closing['subtitle']
    assert 'wider rollout is not yet approved' in closing['subtitle']
    assert result['slides'][1]['bullets'] == candidate['slides'][1]['bullets']
    assert len(result['slides']) == len(candidate['slides'])
    assert candidate == original


def test_generation_rejects_unreadable_empty_closing_without_retry(monkeypatch, ml, inputs):
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'title', 'title': 'Pilot'},
        {'layout': 'text', 'title': 'Results', 'body': '\U0001f600' * 201},
        {'layout': 'closing', 'title': 'Pilot'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    with pytest.raises(ValueError, match='readable closing recap'):
        ml.generate(**dict(inputs, text='Source material. ' * 100))
    assert len(calls) == 1


def test_generation_fills_title_only_closing_without_changing_heading(monkeypatch, ml, inputs):
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'title', 'title': 'Pilot'},
        {'layout': 'text', 'title': 'Only in one laboratory', 'body': 'Conflicts fell 75%.'},
        {'layout': 'closing', 'title': 'Conclusion', 'notes': 'Existing notes.'},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    assert result['slides'][-1]['title'] == 'Conclusion'
    assert result['slides'][-1]['subtitle'] == 'Only in one laboratory\nConflicts fell 75%.'
    assert result['slides'][-1]['notes'] == 'Existing notes.'


def test_generation_preserves_meaningful_closing(monkeypatch, ml, inputs):
    candidate = {'title': 'Laboratory booking', 'slides': [
        {'layout': 'title', 'title': 'Laboratory booking'},
        {'layout': 'text', 'title': 'Pilot', 'body': 'One laboratory.'},
        {'layout': 'closing', 'title': 'Next step',
         'subtitle': 'Test two more laboratories; budget is not approved.',
         'notes': 'No automatic rollout.'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    assert {k: v for k, v in result['slides'][-1].items() if k != 'id'} == candidate['slides'][-1]
    closing_schema = calls[0]['schema']['$defs']['ClosingSlide']
    assert 'subtitle' in closing_schema['required']
    assert closing_schema['properties']['subtitle']['minLength'] == 1


@pytest.mark.parametrize('version', ['v3', 'v4'])
def test_v3_packs_short_sections_without_losing_text_or_notes(monkeypatch, ml, version, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', version)
    candidate = {'title': 'Museum review', 'slides': [
        {'layout': 'title', 'title': 'Museum review'},
        {'layout': 'bullets', 'title': 'Feedback', 'bullets': ['Calm light', 'Clear labels']},
        {'layout': 'text', 'title': 'Navigation', 'body': 'Some visitors had difficulty.',
         'notes': 'Proposal is not approved.'},
        {'layout': 'bullets', 'title': 'Limits', 'bullets': ['No visitor counts measured',
                                                         'Budget not approved'],
         'notes': 'Use the figures only for the pilot.'},
    ]}
    original = copy.deepcopy(candidate)
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, slideCount=8))
    assert len(result['slides']) == 4
    assert result['slides'][0]['layout'] == 'title'
    assert result['slides'][-1]['layout'] == 'closing'
    visible = '\n'.join(ml._slide_text(s) for s in result['slides'])
    for fragment in ('Feedback', 'Calm light', 'Clear labels', 'Navigation',
                     'Some visitors had difficulty.', 'Limits',
                     'No visitor counts measured', 'Budget not approved'):
        assert visible.count(fragment) == 1
    assert result['slides'][-1]['title'] == 'Limits'
    assert result['slides'][-1]['subtitle'] == 'No visitor counts measured\nBudget not approved'
    assert result['slides'][-1]['notes'] == 'Use the figures only for the pilot.'
    assert any('Proposal is not approved.' in s.get('notes', '') for s in result['slides'])
    assert all(len(s.get('body', '')) <= 800 for s in result['slides'])
    assert candidate == original

@pytest.mark.parametrize('explicit_closing', [False, True])
def test_short_merge_keeps_section_headings_once_and_preserves_long_content(
    monkeypatch, ml, inputs, explicit_closing,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    details = 'А' * 399 + '\U0001f600'
    closing = {'layout': 'closing', 'title': 'Дальше', 'subtitle': 'Проверьте условия.'}
    candidate = {'title': 'Доклад', 'slides': [
        {'layout': 'title', 'title': 'Доклад'},
        {'layout': 'text', 'title': 'Условия', 'body': 'Срок не гарантирован.'},
        {'layout': 'text', 'title': 'Ограничения', 'body': details},
        *([closing] if explicit_closing else []),
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, slideCount=3))
    _, content, last = result['slides']
    assert content['title'] == 'Условия'
    assert content['body'] == f'Срок не гарантирован.\n\nОграничения\n{details}'
    expected = 'Проверьте условия.' if explicit_closing else 'Срок не гарантирован.'
    assert last['subtitle'] == expected


def test_generation_joins_heading_with_untitled_content_verbatim(monkeypatch, ml, inputs):
    candidate = {'title': 'Report', 'slides': [
        {'layout': 'title', 'title': 'Report'},
        {'layout': 'title', 'title': 'Before and after', 'caption': 'Evening only',
         'notes': 'Header note'},
        {'layout': 'two-column', 'title': '', 'leftTitle': 'Before', 'left': ['14 minutes'],
         'rightTitle': 'After', 'right': ['11 minutes'], 'notes': 'Content note'},
        {'layout': 'closing', 'title': 'Report'},
    ]}
    snapshot = copy.deepcopy(candidate)
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    assert len(result['slides']) == 3
    slide = result['slides'][1]
    assert slide['title'] == 'Before and after'
    assert slide['layout'] == 'text'
    for fragment in ('Evening only', 'Before', '14 minutes', 'After', '11 minutes'):
        assert fragment in slide['body']
    assert 'Header note' in slide['notes'] and 'Content note' in slide['notes']
    assert candidate == snapshot


@pytest.mark.parametrize(('extra', 'draft', 'expected'), [
    ('', 'Уменьшенный гарнир — 28% заказов.', 'Уменьшенный гарнир — 28% заказов с гарниром.'),
    (' В другом пилоте уменьшенный гарнир выбирали в 28% заказов без подписки.',
     'Уменьшенный гарнир — 28% заказов.', 'Уменьшенный гарнир — 28% заказов.'),
    (' Обычный гарнир выбирали в 28% заказов.',
     'Уменьшенный гарнир — 28% заказов.', 'Уменьшенный гарнир — 28% заказов.'),
    ('', 'Доставка курьером — 28% заказов.', 'Доставка курьером — 28% заказов.'),
    ('', 'Уменьшенный гарнир — 28% всех заказов.', 'Уменьшенный гарнир — 28% всех заказов.'),
    ('', 'Уменьшенный гарнир — 28% заказов в филиале.',
     'Уменьшенный гарнир — 28% заказов в филиале.'),
    ('', 'Уменьшенный гарнир — на 28% заказов.', 'Уменьшенный гарнир — на 28% заказов.'),
    ('', 'Уменьшенный гарнир не брали в 28% заказов.',
     'Уменьшенный гарнир не брали в 28% заказов.'),
])
def test_generation_restores_omitted_percentage_scope_only_when_source_is_unambiguous(
    monkeypatch, ml, inputs, extra, draft, expected,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    source = 'Уменьшенную порцию гарнира выбирали в 28 процентах заказов с гарниром.' + extra
    candidate = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот'},
        {'id': 'result', 'layout': 'section', 'title': 'Доля', 'subtitle': draft,
         'notes': 'Оговорки.'},
        {'layout': 'closing', 'title': 'Итог', 'subtitle': 'Продолжим измерения.'},
    ]}
    calls = provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, text=source))
    assert len(calls) == 1
    assert result['slides'][1] == dict(candidate['slides'][1], subtitle=expected)


def test_generation_restores_percentage_scope_from_a_cited_source_block(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    source = {'blocks': [{
        'id': 'sample', 'kind': 'text',
        'text': 'Teams completed training in 30.5 percent of sites with night shifts.',
    }]}
    intent = {'goal': 'Show participation', 'takeaway': 'Training sites', 'visual_intent': 'Rate',
              'evidence_ids': ['block-1']}
    candidate = {'title': 'Training', 'plan': [intent], 'slides': [
        {'layout': 'bullets', 'title': 'Results',
         'bullets': ['Completed training — 30.5% of sites.']},
    ]}
    provider(monkeypatch, ml, candidate)
    deck = ml._generate(**inputs, source=source)
    assert deck.document['slides'][1]['bullets'] == [
        'Completed training — 30.5% of sites with night shifts.',
    ]
    assert deck.plan.slides[1].intents[0].evidence[0].block_id == 'sample'


@pytest.mark.parametrize('plan_problem', ['missing_intent', 'unknown_evidence', 'blank_evidence'])
def test_structured_generation_keeps_valid_slides_when_the_plan_is_invalid(
    monkeypatch, ml, inputs, plan_problem,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    intent = {'goal': 'Show the pilot', 'takeaway': 'Measured results', 'visual_intent': 'Read',
              'evidence_ids': ['block-1']}
    source = {'blocks': [{
        'id': 'text-1', 'kind': 'text', 'text': 'Пилот: выдано 50 комплектов в одном корпусе.',
    }]}
    result = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот'},
        {'layout': 'text', 'title': 'Результат', 'body': source['blocks'][0]['text']},
        {'layout': 'closing', 'title': 'Итоги', 'subtitle': 'Пилот прошёл в одном корпусе.'},
    ]}
    result['plan'] = [copy.deepcopy(intent) for _ in result['slides']]
    if plan_problem == 'missing_intent':
        result['plan'].pop()
    else:
        result['plan'][1]['evidence_ids'] = ['missing-block'] if plan_problem == 'unknown_evidence' else []
    calls = provider(monkeypatch, ml, result)

    deck = ml._generate(**inputs, source=source)

    assert deck.plan is None
    assert [{key: value for key, value in slide.items() if key != 'id'}
            for slide in deck.document['slides']] == result['slides']
    assert len(calls) == 1


def test_bad_evidence_on_one_slide_does_not_discard_a_verified_table(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    rows = [['Region', 'Output, MWh'], ['North', '41'], ['South', '27']]
    source = {'blocks': [{'id': 'table-id', 'kind': 'table', 'rows': rows, 'page': 2}]}
    draft = {'title': 'Output', 'slides': [
        {'layout': 'title', 'title': 'Output'},
        {'layout': 'text', 'title': 'Context', 'body': 'Measured during the pilot.'},
        {'layout': 'text', 'title': 'Comparison', 'body': 'Results by region.'},
        {'layout': 'closing', 'title': 'Summary', 'subtitle': 'Two regions.'},
    ], 'plan': [
        {'evidence_ids': [], 'visual_kind': 'text'},
        {'evidence_ids': ['unknown'], 'visual_kind': 'chart'},
        {'evidence_ids': ['block-1'], 'visual_kind': 'table'},
        {'evidence_ids': [], 'visual_kind': 'text'},
    ]}
    calls = provider(monkeypatch, ml, draft)
    slides = ml.generate(**inputs, source=source)['slides']
    assert slides[1]['body'] == 'Measured during the pilot.'
    assert 'composition' not in slides[1]
    assert slides[2]['sourceMaterial'] == {'kind': 'table', 'rows': rows, 'page': 2}
    assert len(calls) == 1


def test_joined_heading_preserves_its_content_slide_table(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    rows = [['Region', 'Output, MWh'], ['North', '41'], ['South', '27']]
    source = {'blocks': [{'id': 'table-id', 'kind': 'table', 'rows': rows}]}
    draft = {'title': 'Output', 'slides': [
        {'layout': 'title', 'title': 'Output'},
        {'layout': 'section', 'title': 'Regional results'},
        {'layout': 'text', 'title': '', 'body': 'Measured output.'},
        {'layout': 'closing', 'title': 'Summary', 'subtitle': 'Two regions.'},
    ], 'plan': [
        {'evidence_ids': [], 'visual_kind': 'text'},
        {'evidence_ids': [], 'visual_kind': 'text'},
        {'evidence_ids': ['block-1'], 'visual_kind': 'table'},
        {'evidence_ids': ['block-1'], 'visual_kind': 'text'},
    ]}
    provider(monkeypatch, ml, draft)
    slide = ml.generate(**inputs, source=source)['slides'][1]
    assert slide['title'] == 'Regional results'
    assert slide['sourceMaterial']['rows'] == rows


def test_generation_omits_null_optional_fields_without_rewriting_visible_content(
    monkeypatch, ml, inputs,
):
    candidate = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот', 'subtitle': None, 'caption': None},
        {'layout': 'text', 'title': 'Результат', 'body': 'Результат получен в пилоте.', 'notes': None},
        {'layout': 'closing', 'title': 'Итоги', 'subtitle': 'Пилот завершён.'},
    ]}
    provider(monkeypatch, ml, candidate)
    slides = ml.generate(**inputs)['slides']
    assert 'subtitle' not in slides[0] and 'caption' not in slides[0]
    assert slides[1]['body'] == candidate['slides'][1]['body']
    assert 'notes' not in slides[1]
    assert slides[2]['subtitle'] == candidate['slides'][2]['subtitle']


@pytest.mark.parametrize('page', [4, None])
@pytest.mark.parametrize('table_case', ['exact', 'ambiguous', 'incomplete', 'too_wide'])
def test_generation_places_a_cited_source_table_as_native_cells(
    monkeypatch, ml, inputs, page, table_case,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    rows = [['Сценарий', 'Вт·ч на изображение', 'МВт·ч в день'],
            ['Базовый', '1,35', '135'], ['Новый', '0,563', '56']]
    table = {'id': 'input-table', 'kind': 'table', 'page': page, 'rows': copy.deepcopy(rows)}
    source = {'blocks': [table]}
    ids = ['block-1']
    if table_case == 'ambiguous':
        source['blocks'].append(dict(table, id='another-table'))
        ids.append('block-2')
    elif table_case == 'incomplete':
        table['rows'][1][1] = None
    elif table_case == 'too_wide':
        table['rows'] = [row * 3 for row in rows]
    body = 'При фиксированном объёме меняется дневное потребление.'
    candidate = {'title': 'Энергопотребление', 'slides': [
        {'layout': 'text', 'title': 'Сценарии', 'body': body},
    ], 'plan': [{
        'goal': 'Сопоставить сценарии', 'takeaway': body,
        'visual_intent': 'Показать исходные значения',
        'visual_kind': 'table', 'evidence_ids': ids,
    }]}
    calls = provider(monkeypatch, ml, candidate)
    slides = ml.generate(**inputs, source=source)['slides']

    assert slides[1]['body'] == body
    assert len(calls) == 1
    if table_case == 'exact':
        expected = {'kind': 'table', 'rows': rows}
        if page is not None:
            expected['page'] = page
        assert slides[1]['sourceMaterial'] == expected
    else:
        assert 'sourceMaterial' not in slides[1]


@pytest.mark.parametrize('invalid', [None, 'column', 'missing_cell', 'row', 'missing_label', 'other_label_column'])
def test_planned_large_table_uses_addressed_rows_and_columns_with_source_headers(
    monkeypatch, ml, inputs, invalid,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    rows = [['Сценарий', 'Период', 'Энергия, кВт·ч на 1000 изображений',
             *[f'Метрика {i}' for i in range(4, 11)]],
            *[[f'Режим {i}', '2024', f'{i},05', *['—'] * 7] for i in range(1, 13)]]
    selection = {'header_rows': 1, 'rows': [3, 12], 'columns': [1, 3]}
    if invalid == 'column':
        selection['columns'] = [1, 11]
    elif invalid == 'missing_cell':
        rows[2][2] = None
    elif invalid == 'row':
        selection['rows'] = [1, 12]
    elif invalid == 'missing_label':
        selection['columns'] = [2, 3]
    elif invalid == 'other_label_column':
        rows = [[row[1], row[0], *row[2:]] for row in rows]
        selection.update(columns=[2, 3], label_column=2)
    source = {'blocks': [{'id': 'table-large', 'kind': 'table', 'page': 7,
                          'number': '4', 'rows': rows}]}
    result = {'title': 'Энергопотребление', 'slides': [
        {'layout': 'text', 'title': 'Сравнение двух режимов',
         'body': 'Сопоставлены режимы при одном объёме.'},
    ], 'plan': [{'evidence_ids': ['block-1'], 'visual_kind': 'table',
                 'table_selection': selection}]}
    calls = provider(monkeypatch, ml, result)

    slide = ml.generate(**inputs, source=source)['slides'][1]

    if invalid in (None, 'other_label_column'):
        header = rows[0][selection['columns'][0]-1]
        assert slide['sourceMaterial'] == {
            'kind': 'table', 'page': 7, 'rows': [[header, rows[0][2]],
                                                 ['Режим 2', '2,05'], ['Режим 11', '11,05']],
        }
        packet = calls[0]['payload']
        assert packet['source_visuals'][0]['dimensions'] == {'rows': 13, 'columns': 10}
        assert 'row 12:' in packet['text']
    else:
        assert 'sourceMaterial' not in slide
    assert slide['body'] == result['slides'][0]['body']


def test_generation_can_render_a_table_from_a_regular_text_source(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    source = {'blocks': [
        {'id': 'energy', 'kind': 'text',
         'text': 'Breakdown by district: North – 2,100.5 MWh (industrial users – 51%), '
                 'and South – 2,221 MWh (industrial users – 55%).'},
    ]}
    result = {'title': 'Electricity', 'slides': [
        {'layout': 'text', 'title': 'Differences between districts', 'body': 'Two districts reported usage.'},
    ], 'plan': [{'evidence_ids': ['block-2'], 'visual_kind': 'table'}]}
    provider(monkeypatch, ml, result)

    slide = ml.generate(**inputs, source=source)['slides'][1]

    assert slide['sourceMaterial']['rows'] == [
        ['Group', 'Value, MWh', 'Share (industrial users)'],
        ['North', '2,100.5', '51%'],
        ['South', '2,221', '55%'],
    ]


@pytest.mark.parametrize('reused_number', [False, True])
def test_generation_restores_explicitly_referenced_table_even_without_a_plan(
    monkeypatch, ml, inputs, reused_number,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    rows = [['Сценарий', 'МВт·ч в день'], ['Базовый', '135'], ['Новый', '56']]
    table = {'id': 'input-table', 'kind': 'table', 'page': 4, 'number': '6', 'rows': rows}
    source = {'blocks': [table]}
    if reused_number:
        source['blocks'].append(dict(table, id='other-table', page=8))
    result = {'title': 'Энергопотребление', 'slides': [
        {'layout': 'text', 'title': 'Сценарии', 'body': 'Мощность по сценариям показана в таблице 6.'},
        {'layout': 'text', 'title': 'Условия', 'body': 'Повтор вычислений по табл. №6.'},
    ]}
    provider(monkeypatch, ml, result)

    deck = ml._generate(**inputs, source=source)
    materials = [slide['sourceMaterial'] for slide in deck.document['slides'] if 'sourceMaterial' in slide]
    assert materials == ([] if reused_number else [{'kind': 'table', 'page': 4, 'rows': rows}])


def test_visual_reference_renders_chart_with_printed_values_for_both_named_periods(
    monkeypatch, ml, inputs,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    source = {'blocks': [{
        'id': 'pdf-chart-one', 'kind': 'table', 'page': 4,
        'caption': 'Рисунок 2.1.7а – Доля обучающихся, %',
        'rows': [['Категория', 'Доля', None, None], [None, '2022', '2023', '2024'],
                 ['Группа А', '40,2%', '48,9%', '51,5%'],
                 ['Группа Б', '43,1%', '47,3%', '53,9%']],
    }]}
    result = {'title': 'Обучение', 'slides': [
        {'layout': 'text', 'title': 'Доля в 2023 и 2024 годах',
         'body': 'Динамика по группам, рис. 2.1.7а.'},
    ]}
    provider(monkeypatch, ml, result)

    chart = ml.generate(**inputs, source=source)['slides'][1]['composition']

    assert chart == {
        'kind': 'comparison', 'categories': ['Группа А', 'Группа Б'], 'unit': '%',
        'series': [{'label': '2023', 'values': [48.9, 47.3]},
                   {'label': '2024', 'values': [51.5, 53.9]}],
    }


def test_generation_offers_addressable_pdf_chart_and_uses_plan_block_without_prose_reference(
    monkeypatch, ml, inputs,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    caption = 'Рисунок 2.1.7а – Доля заявок, %'
    source = {'blocks': [
        {'id': 'summary', 'kind': 'text', 'page': 4, 'text': 'Обращения разделили на две группы.'},
        {'id': 'pdf-chart', 'kind': 'table', 'page': 4, 'caption': caption,
         'rows': [['Категория', 'Доля', None], [None, '2023', '2024'],
                  ['Группа А', '48,9%', '51,5%'], ['Группа Б', '47,3%', '53,9%']]},
    ]}
    result = {'title': 'Обращения', 'slides': [
        {'layout': 'text', 'title': 'Динамика обращений',
         'body': 'Доля выросла в обеих группах.'},
        {'layout': 'text', 'title': 'Методика', 'body': 'Группы показаны на рис. 2.1.7а.'},
    ], 'plan': [{'visual_kind': 'chart', 'evidence_ids': ['block-2']},
                {'visual_kind': 'text', 'evidence_ids': ['block-1']}]}
    calls = provider(monkeypatch, ml, result)

    slides = ml.generate(**inputs, source=source)['slides']

    assert calls[0]['payload']['source_visuals'] == [
        {'id': 'block-2', 'kind': 'chart', 'page': 4, 'caption': caption},
    ]
    assert slides[1]['composition']['series'] == [
        {'label': '2023', 'values': [48.9, 47.3]}, {'label': '2024', 'values': [51.5, 53.9]},
    ]
    assert 'composition' not in slides[2]


@pytest.mark.parametrize('variant', ['exact', 'duplicate', 'unit', 'year', 'one_value'])
def test_vector_chart_matches_published_numbers_when_draft_omits_figure_reference(
    monkeypatch, ml, inputs, variant,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    first = {
        'id': 'pdf-chart-one', 'kind': 'table', 'page': 4,
        'caption': 'Рисунок 2.1.1 – Доля заявок, %',
        'rows': [['Категория', 'Доля', None, None], [None, '2022', '2023', '2024'],
                 ['Группа А', '40,2%', '48,9%', '51,5%'],
                 ['Группа Б', '43,1%', '47,3%', '53,9%'],
                 ['Группа В', '46,4%', '52,7%', '55,8%']],
    }
    source = {'blocks': [first]}
    title = 'Доли в 2023 и 2024 годах'
    body = 'Группа А показала рост доли с 48,9 % до 51,5%.'
    if variant == 'duplicate':
        source['blocks'].append(dict(first, id='pdf-chart-two', page=5,
                                     caption='Рисунок 2.1.2 – Доля обращений, %'))
    elif variant == 'unit':
        body = 'В группе А обработали от 48,9 до 51,5 тысячи заявок.'
    elif variant == 'year':
        title = 'Изменения в 2024 году'
    elif variant == 'one_value':
        body = 'Для группы А опубликовано значение 51,5%.'
    result = {'title': 'Обращения', 'slides': [
        {'layout': 'text', 'title': title, 'body': body},
        {'layout': 'text', 'title': 'Сводка', 'body': body, 'notes': 'Периоды 2023 и 2024.'},
    ]}
    provider(monkeypatch, ml, result)

    slides = ml.generate(**inputs, source=source)['slides']
    assert slides[1]['body'] == body
    if variant == 'exact':
        assert slides[1]['composition'] == {
            'kind': 'comparison', 'categories': ['Группа А', 'Группа Б', 'Группа В'], 'unit': '%',
            'series': [{'label': '2023', 'values': [48.9, 47.3, 52.7]},
                       {'label': '2024', 'values': [51.5, 53.9, 55.8]}],
        }
    else:
        assert 'composition' not in slides[1]
    assert 'composition' not in slides[2]


@pytest.mark.parametrize("plan", [True, False])
def test_indexed_source_figure_import_reuses_pixels_and_ignores_ambiguous_catalog_code(
    monkeypatch, ml, inputs, plan,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    png = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
           'AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=')
    source = {'blocks': [
        {'id':'one', 'kind':'illustration', 'page':1,
         'locator':'30,90,200,220', 'caption':'Average trips [STAT0101]', 'png':png},
        {'id':'two', 'kind':'illustration', 'page':2,
         'locator':'30,90,200,220', 'caption':'Average miles [STAT0101]', 'png':png},
    ]}
    result = {'title':'Survey', 'slides':[
        {'layout':'text', 'title':'Average trips by year', 'body':'Trips dropped in 2025.'},
        {'layout':'text', 'title':'Comparison', 'body':'Two measures are reported in STAT0101.'},
    ]}
    if plan:
        result['plan'] = [{'evidence_ids':['block-1'], 'visual_kind':'figure'},
                          {'evidence_ids':['block-1', 'block-2'], 'visual_kind':'figure'}]
    calls = provider(monkeypatch, ml, result)
    deck = ml.generate(**inputs, source=source)

    assert deck['slides'][1]['sourceMaterial'] == {'kind':'image', 'page':1, 'png':png}
    assert 'sourceMaterial' not in deck['slides'][2]
    assert png not in repr(calls[0]['payload'])
    assert [visual['kind'] for visual in calls[0]['payload']['source_visuals']] == ['figure', 'figure']


def test_figure_selection_can_use_two_ratios_from_adjacent_source_prose(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    png = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
           'AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=')
    source = {'blocks': [
        {'id':'method', 'kind':'text', 'page':2, 'text':'84% responded, up from 82%.'},
        {'id':'described', 'kind':'text', 'page':2,
         'text':'Walking made up 47% of school journeys in 2025, down from 51% in 2024.'},
        {'id':'figure', 'kind':'illustration', 'page':2, 'locator':'30,90,200,220',
         'caption':'Trips to and from school by main mode and age [STAT0613]', 'png':png},
    ]}
    result = {'title':'Survey', 'slides':[
        {'layout':'text', 'title':'School response rate', 'body':'84% responded, up from 82%.'},
        {'layout':'text', 'title':'Children’s school travel', 'body':'Walking accounted for 47% in 2025 and 51% in 2024.'},
        {'layout':'text', 'title':'Survey participation', 'body':'47% in 2025 and 51% in 2024.'},
    ]}
    provider(monkeypatch, ml, result)
    slides = ml.generate(**inputs, source=source)['slides']
    assert slides[2]['sourceMaterial'] == {'kind':'image', 'page':2, 'png':png}
    assert 'sourceMaterial' not in slides[1]
    assert 'sourceMaterial' not in slides[3]


@pytest.mark.parametrize('duplicate', [False, True])
def test_figure_selection_uses_unique_verbatim_adjacent_prose(duplicate):
    from app.presentations.source_blocks import IllustrationBlock, SourceDocument, TextBlock
    from presentation_ml.deck_plan import apply_referenced_figures

    body = ('Walking accounted for 47% of journeys among younger children, while older children '
            'made 38% of their school journeys on foot during the same period.')
    png = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
           'AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=')
    blocks = [
        IllustrationBlock('chart', '30,90,200,220', 'School travel by age', 2, png),
        TextBlock('description', body, 2),
    ]
    if duplicate:
        blocks.append(IllustrationBlock('other-chart', '30,230,200,390', 'Travel patterns', 2, png))
    slide = {'id': 'slide', 'layout': 'text', 'title': 'Routenwahl nach Altersgruppe', 'body': body}
    apply_referenced_figures({'slides': [slide]}, SourceDocument(tuple(blocks)), None)
    assert slide.get('sourceMaterial') == (None if duplicate else {'kind': 'image', 'page': 2, 'png': png})


@pytest.mark.parametrize('body, attached', [
    ('В сценарии S1 рост составил около 4,2 раза.', True),
    ('Рост составил около 4,2 раза.', False),
    ('В сценарии S1 рост составил около 14,2 раза.', False),
])
def test_equation_fallback_requires_result_and_variable(body, attached):
    from app.presentations.source_blocks import SOURCE_ADAPTER
    from presentation_ml.deck_plan import apply_referenced_equations

    png = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
           'AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=')
    source = SOURCE_ADAPTER.validate_python({'blocks': [
        {'id': 'equation', 'kind': 'illustration', 'page': 4,
         'locator': '20,60,400,70', 'caption': 'Формула (16)', 'png': png},
        {'id': 'line', 'kind': 'text', 'page': 4, 'text': 'E(S1) ≈ 4,2 (16)'},
    ]})
    slide = {'id': 'x', 'layout': 'text', 'title': 'Результат', 'body': body}
    apply_referenced_equations({'slides': [slide]}, source)
    assert ('sourceMaterial' in slide) == attached


@pytest.mark.parametrize("planned", [False, True])
def test_numbered_formula_uses_the_source_image_without_sending_it_to_the_model(
    monkeypatch, ml, inputs, planned,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    png = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC'
           'AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=')
    source = {'blocks': [{'id': 'eq', 'kind': 'illustration', 'page': 4,
                          'locator': '100,200,300,220', 'caption': 'Формула (16)', 'png': png}]}
    result = {'title': 'Энергопотребление', 'slides': [
        {'layout': 'text', 'title': 'Отскок спроса',
         'body': 'Рост объёма учтён в формуле (16).'},
    ]}
    if planned:
        result['slides'][0]['body'] = 'В расчёте учитывается рост объёма.'
        result['plan'] = [{'evidence_ids':['block-1'], 'visual_kind':'equation'}]
    calls = provider(monkeypatch, ml, result)

    deck = ml.generate(**inputs, source=source)

    assert deck['slides'][1]['sourceMaterial'] == {'kind': 'image', 'page': 4, 'png': png}
    assert png not in repr(calls[0]['payload'])

    calls = provider(monkeypatch, ml, deck)
    revised = ml.revise(**inputs, document=deck, source=source, instruction='Проверь заголовок',
                        target_slide_numbers=[2], target_slide_ids=[deck['slides'][1]['id']])
    assert revised['slides'][1]['sourceMaterial'] == deck['slides'][1]['sourceMaterial']
    assert png not in repr(calls[0]['payload'])


@pytest.mark.parametrize('ambiguous', [False, True])
def test_generation_restores_unambiguous_prefix_without_changing_denominator(monkeypatch, ml, inputs, ambiguous):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    source = 'Медиана составила 1,35 кВт·ч на 1000 изображений.'
    draft = source.replace('кВт·ч', 'Вт·ч')
    blocks = [{'id': 'original', 'kind': 'text', 'text': source}]
    if ambiguous:
        blocks.append({'id': 'second', 'kind': 'text', 'text': draft})
    provider(monkeypatch, ml, {'title': 'Энергия', 'slides': [
        {'layout': 'text', 'title': 'Медиана', 'body': draft},
    ]})
    slide = ml.generate(**inputs, source={'blocks': blocks})['slides'][1]
    assert slide['body'] == (draft if ambiguous else source)


def test_rate_unit_prefix_survives_pdf_line_breaks_and_slash_notation():
    from presentation_ml.grounding import restore_percentage_scopes

    paragraphs = [('a', 'На установке медиана 1,35 кВт·ч на 1000'),
                  ('b', 'изображений и среднее значение выше.')]
    slide = {'id': 'check', 'body': 'Медиана 1,35 Вт·ч/1000 изображений.'}
    restore_percentage_scopes({'slides': [slide]}, paragraphs)
    assert slide['body'] == 'Медиана 1,35 кВт·ч/1000 изображений.'
    slide['body'] = 'Медиана 1,35 Вт·ч/100 изображений.'
    restore_percentage_scopes({'slides': [slide]}, paragraphs)
    assert slide['body'] == 'Медиана 1,35 Вт·ч/100 изображений.'


def test_percentage_scope_keeps_different_actions_separate(monkeypatch, ml, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    text = (
        'In the pilot project, analysts reviewed 20% of the applications at the central site. '
        'In the pilot project, staff rejected twenty percent of the applications '
        'at the remote site.'
    )
    draft = 'In the pilot project, staff rejected 20% of the applications.'
    candidate = {'title': 'Pilot', 'slides': [
        {'layout': 'text', 'title': 'Applications', 'body': draft},
        {'layout': 'closing', 'title': 'Results', 'subtitle': 'Pilot completed.'},
    ]}
    provider(monkeypatch, ml, candidate)
    assert ml.generate(**dict(inputs, text=text))['slides'][1]['body'] == draft


def test_percentage_scope_does_not_use_uncited_paragraph_on_planned_slide(
    monkeypatch, ml, inputs,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    draft = 'Completed training — 30.5% of sites.'
    source = {'blocks': [
        {'id': 'sample', 'kind': 'text',
         'text': 'Teams completed training in 30.5 percent of sites with night shifts.'},
        {'id': 'overview', 'kind': 'text', 'text': 'Training participation is reviewed monthly.'},
    ]}
    intent = {'goal': 'Show participation', 'takeaway': 'Training sites', 'visual_intent': 'Rate',
              'evidence_ids': ['block-2']}
    candidate = {'title': 'Training', 'plan': [intent], 'slides': [
        {'layout': 'text', 'title': 'Results', 'body': draft},
    ]}
    provider(monkeypatch, ml, candidate)
    assert ml._generate(**inputs, source=source).document['slides'][1]['body'] == draft


def test_generation_places_dense_section_subtitles_on_content_slides(monkeypatch, ml, inputs):
    details = ('В пилоте участвовали четыре площадки. Учёт занимал 15 минут в день. '
               'Контрольной группы не было. Опрос посетителей не проводили. '
               'Применимость подхода в других корпусах пока не проверяли.')
    candidate = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот'},
        {'id': 'division', 'layout': 'section', 'title': 'Результаты',
         'subtitle': 'Апрельский пилот.'},
        {'id': 'constraints', 'layout': 'section', 'title': 'Ограничения',
         'subtitle': details, 'notes': 'Только пилотный период.'},
        {'layout': 'closing', 'title': 'Итог', 'subtitle': 'Нужна повторная проверка.'},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, slideCount=4))
    assert result['slides'][1] == candidate['slides'][1]
    assert result['slides'][2] == {
        'id': 'constraints', 'layout': 'text', 'title': 'Ограничения',
        'body': details, 'notes': 'Только пилотный период.',
    }


@pytest.mark.parametrize('structured', [False, True])
def test_v4_sends_literal_review_sections_without_mixing_results_and_targets(
    monkeypatch, ml, inputs, structured,
):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    paragraphs = [
        'Что не получилось', 'Учёт занимал около 15 минут в день.',
        '1. Ограничения исследования', 'Контрольной столовой не было.',
        '• Опрос удовлетворённости не проводили',
        'Краткая справка', 'Отчёт подготовила команда пилота.',
        'Предложение по следующему этапу', 'Цель на следующий этап — до 15 минут на смену.',
    ]
    intent = dict(goal='Показать ограничения', takeaway='Пилот без контроля',
                  visual_intent='Ограничения', evidence_ids=['block-4'])
    candidate = {'title': 'Пилот', 'slides': [
        {'layout': 'text', 'title': 'Ограничения', 'body': 'Контрольной столовой не было.'},
    ]}
    options = dict(inputs, text='\r\n\r\n'.join(paragraphs))
    if structured:
        candidate['plan'] = [intent]
        options['source'] = {'blocks': [
            {'kind': 'text', 'id': f'b{i}', 'text': value}
            for i, value in enumerate(paragraphs)
        ]}
    calls = provider(monkeypatch, ml, candidate)
    ml.generate(**options)
    assert len(calls) == 1
    assert calls[0]['payload']['review_sections'] == {
        'observed': ['Учёт занимал около 15 минут в день.'],
        'limitations': ['Контрольной столовой не было.', '• Опрос удовлетворённости не проводили'],
        'proposed': ['Цель на следующий этап — до 15 минут на смену.'],
    }
    assert 'review_sections' in calls[0]['system']


def test_v5_extracts_section_labels_as_source_data(monkeypatch, ml, inputs, document):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v5')
    calls = provider(monkeypatch, ml, document)
    text = ('Название\n\nОбласть работ\nРаботы проведены только на северном участке.\n\n'
            'Доступ жителей\nПроход сохранён только для жителей двух домов.\n\n'
            'Обычный абзац без отдельного заголовка.')
    ml.generate(**dict(inputs, text=text))
    assert calls[0]['payload']['source_sections'] == ['Область работ', 'Доступ жителей']
    assert calls[0]['payload']['text'] == text
    assert 'critical_facts' not in calls[0]['payload']


@pytest.mark.parametrize('quotes,valid', [
    (['Approved budget: 4.8 million.'], True),
    (['Approved budget: 9.9 million.'], False),
    ([], False),
    ([' ' * 25], False),
    ('Approved budget: 4.8 million.', False),
])
def test_v7_requires_real_source_quotes_and_keeps_them_in_notes(
        monkeypatch, ml, inputs, quotes, valid):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v7')
    text = ('Approved budget: 4.8 million. Paid: 3.6 million. '
            'The remainder is not savings until obligations close. No new actions approved.')
    candidate = {'title': 'Budget review', 'slides': [
        {'layout': 'title', 'title': 'Budget review', 'source_quotes': []},
        {'layout': 'text', 'title': 'Budget', 'body': 'Approved budget: 4.8 million.',
         'source_quotes': quotes},
        {'layout': 'closing', 'title': 'Budget review', 'source_quotes': []},
    ]}
    snapshot = copy.deepcopy(candidate)
    calls = provider(monkeypatch, ml, candidate)
    if valid:
        result = ml.generate(**dict(inputs, text=text))
        assert 'Approved budget: 4.8 million.' in result['slides'][1]['notes']
        assert 'source_quotes' not in result['slides'][1]
        assert result['slides'][1]['body'] == candidate['slides'][1]['body']
        assert candidate == snapshot
        for definition in calls[0]['schema']['$defs'].values():
            if 'layout' in definition.get('properties', {}):
                assert 'source_quotes' in definition['required']
    else:
        with pytest.raises(ValueError, match='source quote'):
            ml.generate(**dict(inputs, text=text))


def test_scoped_revision_accepts_only_requested_replacements_in_any_response_order(
        monkeypatch, ml, inputs, document):
    snapshot = copy.deepcopy(document)
    replacements = [copy.deepcopy(document['slides'][2]), copy.deepcopy(document['slides'][0])]
    replacements[0]['notes'] = 'Selected update'
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        return {'status': 'applied', 'document': {'title': document['title'],
                                                'slides': replacements}}
    monkeypatch.setattr(ml, 'request_document', request)
    result = revise(ml, inputs, document, [3, 1])
    assert document == snapshot
    assert result['slides'][2]['notes'] == 'Selected update'
    assert [s['id'] for s in result['slides']] == [s['id'] for s in snapshot['slides']]
    assert result['slides'][1] == snapshot['slides'][1]
    assert calls[0]['payload']['response_scope'] == 'selected_slides'
    schema = calls[0]['schema']
    slides = schema['properties']['document']['anyOf'][0]['properties']['slides']
    assert slides['minItems'] == slides['maxItems'] == 2
    for definition in schema['$defs'].values():
        if 'layout' in definition.get('properties', {}):
            assert definition['properties']['id']['enum'] == [
                document['slides'][2]['id'], document['slides'][0]['id']]


def test_scoped_revision_keeps_frozen_base_if_provider_mutates_payload(
        monkeypatch, ml, inputs, document):
    snapshot = copy.deepcopy(document)
    def request(**kwargs):
        kwargs['payload']['document']['slides'][1]['title'] = 'Changed inside provider'
        return {'status': 'applied', 'document': {'title': document['title'],
                                                'slides': [copy.deepcopy(document['slides'][2])]}}
    monkeypatch.setattr(ml, 'request_document', request)
    assert revise(ml, inputs, document, [3]) == snapshot
    assert document == snapshot


@pytest.mark.parametrize('indices', [[1], [2, 2], []])
def test_scoped_revision_rejects_unauthorized_duplicate_or_missing_replacements(
        monkeypatch, ml, inputs, document, indices):
    snapshot = copy.deepcopy(document)
    monkeypatch.setattr(ml, 'request_document', lambda **_: {
        'status': 'applied', 'document': {'title': document['title'],
            'slides': [copy.deepcopy(document['slides'][i]) for i in indices]},
    })
    with pytest.raises(ValueError):
        revise(ml, inputs, document, [3])
    assert document == snapshot


def test_provider_cannot_change_requested_scope_or_caller_target_lists(
        monkeypatch, ml, inputs, document):
    snapshot = copy.deepcopy(document)
    numbers = [3]
    targets = [document['slides'][2]['id']]
    def request(**kwargs):
        kwargs['payload']['target_slide_ids'][:] = [document['slides'][1]['id']]
        kwargs['payload']['target_slide_numbers'][:] = [2]
        replacement = copy.deepcopy(document['slides'][1])
        replacement['title'] = 'Unauthorized change'
        return {'status': 'applied', 'document': {'title': document['title'],
                                                'slides': [replacement]}}
    monkeypatch.setattr(ml, 'request_document', request)
    with pytest.raises(ValueError):
        ml.revise(**inputs, document=document, instruction='Сократи текст',
                  target_slide_numbers=numbers, target_slide_ids=targets)
    assert numbers == [3]
    assert targets == [document['slides'][2]['id']]
    assert document == snapshot
