import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.errors import AppError
from app.presentations.routes import pdf_preview
from app.presentations.source_blocks import IllustrationBlock, SourceDocument, TableBlock, TextBlock
from app.presentations.source_preview import build_comparison_preview


@pytest.mark.parametrize('changed_value', [False, True])
def test_preview_keeps_address_and_checks_responder_against_authoritative_packet(changed_value):
    source = SourceDocument((TableBlock('p76-table-1', (
        ('Группа', 'Количество участников', None),
        (None, '2022', '2023'),
        ('Школы', '20', '35'),
    ), page=76, number='18'),))

    def respond(payload, schema):
        assert schema['properties']['comparisons']['maxItems'] == 1
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


def test_pdf_preview_rejects_comparison_requests():
    request = SimpleNamespace(body=AsyncMock(return_value=b'%PDF-'))
    with pytest.raises(AppError) as exc:
        asyncio.run(pdf_preview(request, user=None, compare=True))
    assert exc.value.code == 'COMPARISON_REQUIRES_JOB'


def test_comparison_without_recognized_rows_does_not_call_model():
    source = SourceDocument((TextBlock('text', 'Результаты будут опубликованы позже.'),))
    with pytest.raises(AppError) as exc:
        build_comparison_preview(source, 'Доклад', 3, propose=lambda *_: pytest.fail('Called ML'))
    assert exc.value.code == 'NO_TABLE_COMPARISONS'


def test_comparison_candidates_keep_table_rows_when_prose_would_fill_the_budget():
    source = SourceDocument((
        TextBlock('text', ' '.join(
            f'ООО «Организация {n}» участвует в программе «Пилот».' for n in range(10)
        )),
        TableBlock('table', (
            ('Группа', 'Количество участников', None),
            (None, '2022', '2023'),
            ('Школы', '20', '35'),
            ('Колледжи', '10', '12'),
        )),
    ))

    def respond(payload, _schema):
        first, second = payload['source_facts']
        assert first['relation'] == second['relation'] == 'metric_comparison'
        return {'comparisons': [{
            'fact_id': second['id'], 'group': second['subject'], 'metric': second['target'],
            **second['qualifiers'],
        }]}

    deck = build_comparison_preview(source, 'Доклад', 3, propose=respond)
    assert [slide.layout for slide in deck.slides] == ['title', 'text', 'closing']
    assert deck.slides[1].body == 'Колледжи\n2022 — 10\n2023 — 12'


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
