import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.presentations.routes import pdf_preview
from app.presentations.schemas import Document
from app.presentations.source_preview import build_comparison_preview
from presentation_ml.source_document import IllustrationBlock, SourceDocument, TableBlock, TextBlock


@pytest.mark.parametrize('changed_value', [False, True])
def test_preview_keeps_address_and_checks_responder_against_authoritative_packet(changed_value):
    source = SourceDocument((TableBlock('p76-table-1', (
        ('Группа', 'Количество участников', None),
        (None, '2022', '2023'),
        ('Школы', '20', '35'),
    ), page=76, number='18'),))

    def respond(payload, schema):
        assert schema['properties']['comparisons']['maxItems'] == 2
        (fact,) = payload['source_facts']
        if changed_value:
            fact['qualifiers']['second_value'] = '36'
        return {'comparisons': [{
            'fact_id': fact['id'], 'group': fact['subject'], 'metric': fact['target'],
            **fact['qualifiers'],
        }]}

    if changed_value:
        with pytest.raises(ValueError, match='differs from source'):
            build_comparison_preview(source, 'Доклад', 3, propose=respond)
        return
    deck = build_comparison_preview(source, 'Доклад', 3, propose=respond)
    assert deck.slides[1].body == 'Школы\n2022 — 20\n2023 — 35'
    assert deck.slides[1].notes == 'Источник — стр. 76, таблица 18, блок p76-table-1, строка 3'


def test_pdf_comparison_response_omits_unset_slide_fields(monkeypatch):
    document = Document.model_validate({
        'title': 'Доклад', 'slides': [{'id': 'cover', 'layout': 'title', 'title': 'Доклад'}],
    })
    monkeypatch.setattr(
        'app.presentations.source_preview.generate_pdf_comparisons', lambda *_: document,
    )
    request = SimpleNamespace(body=AsyncMock(return_value=b'%PDF-'))
    reply = asyncio.run(pdf_preview(request, user=None, compare=True))
    assert reply['slides'] == [{'id': 'cover', 'layout': 'title', 'title': 'Доклад'}]


@pytest.mark.parametrize('linked', [True, False])
def test_comparison_uses_only_chart_linked_by_same_statement(linked):
    table = TableBlock('table', (
        ('Группа', 'Количество участников', None),
        (None, '2022', '2023'),
        ('Школы', '20', '35'),
        ('Колледжи', '10', '12'),
    ), page=76, number='18')
    prose = (
        'Динамика участия представлена на диаграмме 1 и в таблице 18.'
        if linked else 'Динамика участия представлена в таблице 18.'
    )
    figure = IllustrationBlock('figure', '0,0,10,10', 'Диаграмма 1', 76)
    source = SourceDocument((TextBlock('text', prose, 76), table, figure))

    def respond(payload, _schema):
        return {'comparisons': [
            {'fact_id': f['id'], 'group': f['subject'], 'metric': f['target'], **f['qualifiers']}
            for f in payload['source_facts'] if f['relation'] == 'metric_comparison'
        ]}

    def render(block):
        assert block == figure
        return {'kind': 'image', 'png': 'data:image/png;base64,AAAA'}

    deck = build_comparison_preview(source, 'Доклад', 5, propose=respond, render=render)
    assert (deck.slides[1].sourceMaterial is not None) is linked
    assert deck.slides[2].sourceMaterial is None
    assert ('Диаграмма 1' in deck.slides[1].notes) is linked
