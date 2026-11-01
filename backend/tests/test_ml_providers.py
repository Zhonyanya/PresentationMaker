"""Provider boundary and prompt migration checks: no live requests."""

import hashlib

import pytest


@pytest.mark.parametrize(('operation', 'digest'), [
    ('generate', '81b11d685f67c5c72503bef9adc7d65f1090cc13f55dacd3ab1b1d3b9dbd8959'),
    ('revise', '48b726cce216e20689db03bb8f8fe1e2ef2c13479f66b0970490fdf826b0409b'),
])
def test_prompt_migration_preserves_existing_messages(operation, digest, monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v1')
    assert hashlib.sha256(build_prompt(operation).encode()).hexdigest() == digest


def test_unknown_provider_fails_before_any_fallback(monkeypatch):
    from presentation_ml.providers import get_provider

    monkeypatch.setenv('PM_ML_PROVIDER', 'not-configured')
    with pytest.raises(NotImplementedError, match='Unsupported ML provider'):
        get_provider()


def test_transport_calls_selected_provider_once(monkeypatch):
    from presentation_ml import transport

    calls = []

    class FakeProvider:
        def complete_json(self, **kwargs):
            calls.append(kwargs)
            return {'title': 'Доклад', 'slides': []}

    monkeypatch.setattr(transport, 'get_provider', lambda: FakeProvider())
    result = transport.request_document(system='rules', payload={'text': 'source'},
                                        schema={'type': 'object'}, timeout=30)
    assert result['title'] == 'Доклад'
    assert calls == [{'system': 'rules', 'payload': {'text': 'source'},
                      'schema': {'type': 'object'}, 'timeout': 30}]


def test_prompt_v2_is_explicit_and_operation_specific(monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v2')
    generated = build_prompt('generate')
    revised = build_prompt('revise')
    assert 'Самоотчёт' in generated
    assert 'document.title' in revised
    assert 'unsupported' in revised
    assert generated != revised


def test_unknown_prompt_version_is_rejected(monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'unknown')
    with pytest.raises(ValueError, match='prompt version'):
        build_prompt('generate')


def test_revision_wire_prompt_separately_versions_internal_protocol():
    from presentation_ml.prompts import REVISION_WIRE_VERSION, build_revision_prompt

    assert REVISION_WIRE_VERSION == 'v3'
    prompt = build_revision_prompt()
    assert '{"unsupported":true}' not in prompt
    assert '"status":"unsupported","document":null' in prompt
    assert '"status":"applied"' in prompt


def test_prompt_v3_limits_short_sources_without_invented_followups(monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v3')
    generated = build_prompt('generate')
    assert '1000' in generated and '4 слайда' in generated
    assert 'обратную связь' in generated
    assert 'document.title' in build_prompt('revise')


def test_v4_preserves_scope_and_strength_without_changing_v3(monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v3')
    original = build_prompt('generate')
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    generated = build_prompt('generate')
    assert original in generated
    assert 'степень уверенности' in generated
    assert 'адресатов' in generated
    assert 'степень уверенности' in build_prompt('revise')


def test_v5_uses_source_section_coverage_without_replacing_v4(monkeypatch):
    from presentation_ml.prompts import build_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v4')
    original = build_prompt('generate')
    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v5')
    assert original in build_prompt('generate')
    assert 'source_sections' in build_prompt('generate')


def test_v6_is_standalone_and_keeps_metric_identity(monkeypatch):
    from presentation_ml.prompts import build_prompt, build_revision_prompt

    monkeypatch.setenv('PM_ML_PROMPT_VERSION', 'v6')
    prompt = build_prompt('generate')
    assert 'название показателя' in prompt
    assert 'Не вычисляй' in prompt
    assert 'source_sections' in prompt
    assert 'Дополнение v3' not in prompt and 'Дополнение v4' not in prompt
    assert 'revision-wire-v3' in build_revision_prompt()
