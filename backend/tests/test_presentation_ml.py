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
    for fragment in ['Comparison', 'Before', '48 kg/day', 'After', '33 kg/day',
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


def test_generated_closing_uses_document_title_without_assuming_language(monkeypatch, ml, inputs):
    candidate = {'title': 'Incident review', 'slides': [
        {'layout': 'title', 'title': 'Incident review'},
        {'layout': 'text', 'title': 'Scope', 'body': 'The root cause is unconfirmed.'},
    ]}
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**inputs)
    assert result['slides'][-1]['layout'] == 'closing'
    assert result['slides'][-1]['title'] == 'Incident review'
    assert result['slides'][1] == dict(candidate['slides'][1], id=result['slides'][1]['id'])


@pytest.mark.parametrize('version', ['v3', 'v4'])
def test_v3_packs_short_sections_without_losing_text_or_notes(monkeypatch, ml, version, inputs):
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', version)
    candidate = {'title': 'Museum review', 'slides': [
        {'layout': 'title', 'title': 'Museum review'},
        {'layout': 'bullets', 'title': 'Feedback', 'bullets': ['Calm light', 'Clear labels']},
        {'layout': 'text', 'title': 'Navigation', 'body': 'Some visitors had difficulty.',
         'notes': 'Proposal is not approved.'},
        {'layout': 'bullets', 'title': 'Limits', 'bullets': ['No visitor counts measured',
                                                         'Budget not approved']},
    ]}
    original = copy.deepcopy(candidate)
    provider(monkeypatch, ml, candidate)
    result = ml.generate(**dict(inputs, slideCount=8))
    assert len(result['slides']) == 4
    assert result['slides'][0]['layout'] == 'title'
    assert result['slides'][-1]['layout'] == 'closing'
    visible = '\n'.join(s.get('body', '') for s in result['slides'])
    for fragment in ('Feedback', 'Calm light', 'Clear labels', 'Navigation',
                     'Some visitors had difficulty.', 'Limits',
                     'No visitor counts measured', 'Budget not approved'):
        assert fragment in visible
    assert any('Proposal is not approved.' in s.get('notes', '') for s in result['slides'])
    assert all(len(s.get('body', '')) <= 800 for s in result['slides'])
    assert candidate == original

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
