"""Quality indicators flag review work; they are not semantic correctness proofs."""

import pytest

from tools.ml_acceptance import inspect_document


def test_flags_missing_anchors_and_repeated_content():
    document = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот'},
        {'layout': 'text', 'title': 'Итоги', 'body': '12 студентов.'},
        {'layout': 'text', 'title': 'Повтор', 'body': '12 студентов.'},
        {'layout': 'closing', 'title': 'Спасибо'},
    ]}
    result = inspect_document(document, {'slideCount': 4, 'anchors': ['12', 'не доказано']})
    assert result['missing_anchors'] == ['не доказано']
    assert result['repeated_content'] == ['12 студентов.']
    assert result['contract_valid'] is True
    assert result['human_review_required'] is True


def test_notes_do_not_hide_missing_visible_facts():
    document = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот', 'notes': '12 студентов'},
        {'layout': 'closing', 'title': 'Спасибо'},
    ]}
    result = inspect_document(document, {'slideCount': 3, 'anchors': ['12']})
    assert result['missing_anchors'] == ['12']
    assert result['slide_count_delta'] == -1


@pytest.mark.parametrize('failure', [False, True])
def test_repeated_run_never_repeats_paid_attempt(monkeypatch, tmp_path, document, failure):
    import json

    import presentation_ml
    from tools import ml_acceptance

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'case', 'text': 'Доклад ' * 20, 'slideCount': 6}]))
    monkeypatch.setattr(ml_acceptance, 'CASES', cases)
    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--case', 'case',
                                   '--output', str(tmp_path / 'out')])
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if failure:
            raise RuntimeError('Synthetic provider failure')
        return document

    monkeypatch.setattr(presentation_ml, 'generate', generate)
    assert ml_acceptance.main() == int(failure)
    if failure:
        with pytest.raises(RuntimeError, match='Prior attempt failed'):
            ml_acceptance.main()
    else:
        assert ml_acceptance.main() == 0
    assert len(calls) == 1


def test_live_run_requires_explicit_case_selection(monkeypatch, tmp_path):
    from tools.ml_acceptance import main

    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--output', str(tmp_path)])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2


def test_live_cache_tracks_generation_structure_prompt(monkeypatch, tmp_path, document):
    import json

    import presentation_ml
    from presentation_ml import prompts
    from tools import ml_acceptance

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'case', 'text': 'Report ' * 200, 'slideCount': 6}]))
    monkeypatch.setattr(ml_acceptance, 'CASES', cases)
    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--case', 'case',
                                   '--output', str(tmp_path / 'out')])
    calls = []
    monkeypatch.setattr(presentation_ml, 'generate',
                        lambda **kwargs: calls.append(kwargs) or document)
    assert ml_acceptance.main() == 0
    original = prompts.build_generation_prompt()
    monkeypatch.setattr(prompts, 'build_generation_prompt', lambda: original + '\nNew rules')
    with pytest.raises(RuntimeError, match='profile changed'):
        ml_acceptance.main()
    assert len(calls) == 1


def test_error_classification_never_stores_exception_text():
    import json
    import socket

    from tools.ml_acceptance import safe_error_details

    secret = 'PRIVATE-KEY-OR-DOCUMENT-TEXT'
    try:
        try:
            raise socket.gaierror(secret)
        except socket.gaierror as cause:
            raise ConnectionError(secret) from cause
    except ConnectionError as exc:
        details = safe_error_details(exc)
    assert details['cause_types'] == ['gaierror']
    assert secret not in json.dumps(details)


@pytest.mark.parametrize(('setting', 'value'), [
    ('PM_ML_PROMPT_VERSION', 'v2'),
    ('GIGACHAT_SCOPE', 'GIGACHAT_API_B2B'),
])
def test_live_cache_cannot_masquerade_as_another_profile(
        monkeypatch, tmp_path, document, setting, value):
    import json

    import presentation_ml
    from tools import ml_acceptance

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'case', 'text': 'Доклад ' * 20, 'slideCount': 6}]))
    monkeypatch.setattr(ml_acceptance, 'CASES', cases)
    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--case', 'case',
                                   '--output', str(tmp_path / 'out')])
    calls = []
    monkeypatch.setattr(presentation_ml, 'generate',
                        lambda **kwargs: calls.append(kwargs) or document)
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v1')
    monkeypatch.setenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS')
    assert ml_acceptance.main() == 0
    monkeypatch.setenv(setting, value)
    with pytest.raises(RuntimeError, match='profile changed'):
        ml_acceptance.main()
    assert len(calls) == 1


def test_opt_in_candidate_saved_before_validation_failure(monkeypatch, tmp_path):
    import json

    import presentation_ml
    from tools import ml_acceptance

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'synthetic', 'synthetic': True,
                                 'text': 'Доклад ' * 20, 'slideCount': 6}]))
    monkeypatch.setattr(ml_acceptance, 'CASES', cases)
    output = tmp_path / 'out'
    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--case', 'synthetic',
                                   '--save-candidates', '--output', str(output)])
    candidate = {'title': 'Synthetic', 'slides': [{'layout': 'unknown', 'title': 'Fact'}]}
    calls = []
    def request(**kwargs):
        calls.append(kwargs)
        return candidate
    monkeypatch.setattr(presentation_ml, 'request_document', request)
    assert ml_acceptance.main() == 1
    assert len(calls) == 1
    assert presentation_ml.request_document is request
    assert json.loads((output / 'synthetic.candidate.json').read_text()) == candidate
    assert json.loads((output / 'synthetic.json').read_text())['status'] == 'error'


def test_candidate_capture_requires_explicit_synthetic_mark(monkeypatch, tmp_path):
    import json

    from tools import ml_acceptance

    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'unclassified', 'text': 'Доклад ' * 20,
                                 'slideCount': 6}]))
    monkeypatch.setattr(ml_acceptance, 'CASES', cases)
    monkeypatch.setattr('sys.argv', ['acceptance', '--live', '--case', 'unclassified',
                                   '--save-candidates', '--output', str(tmp_path / 'out')])
    with pytest.raises(SystemExit) as result:
        ml_acceptance.main()
    assert result.value.code == 2
    assert not (tmp_path / 'out').exists()
