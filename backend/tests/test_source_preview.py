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
    assert deck.slides[1].composition.model_dump(exclude_none=True) == {
        'kind': 'comparison',
        'categories': ['Школы'],
        'series': [{'label': '2022', 'values': [20]}, {'label': '2023', 'values': [35]}],
    }


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
    assert deck.slides[1].composition.categories == ['Школы', 'Колледжи']
    assert deck.slides[1].body == 'Рост — Школы, Колледжи.'


@pytest.mark.parametrize('linked', [True, False])
def test_comparison_uses_only_chart_linked_by_same_statement(linked):
    table = TableBlock('table', (
        ('Группа', 'Количество участников', None),
        (None, '2022', '2023'),
        ('Школы', '20', '35'),
    ), page=76, number='18')
    prose = (
        'Динамика участия представлена на диаграмме 1 и в таблице 18.'
        if linked else 'Динамика участия представлена в таблице 18.'
    )
    figure = IllustrationBlock('figure', '0,0,10,10', 'Диаграмма 1', 76)
    other = TableBlock('other', (*table.rows[:2], ('Колледжи', '10', '12')), page=77)
    source = SourceDocument((TextBlock('text', prose, 76), table, figure, other))

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
    assert (deck.slides[1].composition is None) is linked


@pytest.mark.parametrize('value', ['-2', '1,234'])
def test_ambiguous_or_negative_comparison_stays_in_literal_text(value):
    source = SourceDocument((TableBlock('table', (
        ('Группа', 'Отклонение', None), (None, '2022', '2023'), ('Школы', value, '3'),
    )),))

    def respond(payload, _schema):
        (fact,) = payload['source_facts']
        return {'comparisons': [{
            'fact_id': fact['id'], 'group': fact['subject'], 'metric': fact['target'],
            **fact['qualifiers'],
        }]}

    slide = build_comparison_preview(source, 'Доклад', 3, propose=respond).slides[1]
    assert slide.composition is None
    assert slide.body == f'Школы\n2022 — {value}\n2023 — 3'


def test_grouped_comparison_keeps_table_period_and_units_separate():
    header = (('Группа', 'Участники', None, None), (None, '2022', '2023', '2024'))
    source = SourceDocument((
        TableBlock('first', (*header, ('Школы', '20', '35', '40'),
                            ('Колледжи', '10', '12', '16'), ('Доля', '10%', '12%', '16%'))),
        TableBlock('second', (*header, ('Кружки', '9', '8', '7'))),
    ))

    def respond(payload, _schema):
        facts = payload['source_facts']
        chosen = []
        for table, group, period in [
            ('first', 'Школы', '2022'), ('first', 'Школы', '2023'),
            ('first', 'Доля', '2022'), ('second', 'Кружки', '2022'),
        ]:
            fact = next(f for f in facts if (f['source']['block_id'], f['subject'],
                        f['qualifiers']['first_period']) == (table, group, period))
            chosen.append({'fact_id': fact['id'], 'group': fact['subject'],
                           'metric': fact['target'], **fact['qualifiers']})
        return {'comparisons': chosen}

    deck = build_comparison_preview(source, 'Доклад', 6, propose=respond)
    charts = [slide.composition for slide in deck.slides[1:-1]]
    assert [chart.categories for chart in charts] == [
        ['Школы', 'Колледжи'], ['Школы', 'Колледжи'], ['Доля'], ['Кружки'],
    ]
    assert [[series.label for series in chart.series] for chart in charts] == [
        ['2022', '2023'], ['2023', '2024'], ['2022', '2023'], ['2022', '2023'],
    ]
    assert [chart.unit for chart in charts] == [None, None, '%', None]


@pytest.mark.parametrize('slide_count', [3, 4])
def test_grouped_comparison_uses_extra_space_and_reports_remaining_rows(slide_count):
    source = SourceDocument((TableBlock('table', (
        ('Группа', 'Количество участников', None), (None, '2022', '2023'),
        *((f'Группа {i}', str(i), str(i + 2)) for i in range(1, 9)),
    )),))

    def respond(payload, _schema):
        row = payload['source_facts'][0]
        return {'comparisons': [{'fact_id': row['id'], 'group': row['subject'],
                                 'metric': row['target'], **row['qualifiers']}]}

    deck = build_comparison_preview(source, 'Доклад', slide_count, propose=respond)
    assert len(deck.slides) == slide_count
    chart_groups = [group for slide in deck.slides[1:-1] for group in slide.composition.categories]
    assert chart_groups == [f'Группа {i}' for i in range(1, 7 if slide_count == 3 else 9)]
    if slide_count == 3:
        assert '6 из 8' in deck.slides[-1].subtitle


@pytest.mark.parametrize('page', [1, None])
def test_grouped_comparison_preserves_unplottable_values(page):
    source = SourceDocument((TableBlock('table', (
        ('Группа', 'Отклонение', None), (None, '2022', '2023'),
        ('Школы', '-2', '3'), ('Колледжи', '1,234', '5'),
    ), page=page),))

    def respond(payload, _schema):
        row = payload['source_facts'][0]
        return {'comparisons': [{'fact_id': row['id'], 'group': row['subject'],
                                 'metric': row['target'], **row['qualifiers']}]}

    slide = build_comparison_preview(source, 'Доклад', 3, propose=respond).slides[1]
    assert slide.composition is None
    assert slide.body == 'Школы. 2022 — -2; 2023 — 3\nКолледжи. 2022 — 1,234; 2023 — 5'
    if page is not None:
        assert slide.sourceMaterial.rows == [
            ['Группа', '2022', '2023'], ['Школы', '-2', '3'], ['Колледжи', '1,234', '5'],
        ]
    else:
        assert slide.sourceMaterial is None


def test_comparison_splits_literal_fallback_before_reaching_the_body_limit():
    groups = [character * 300 for character in '😀😃😄😁😆😅']
    value = '9' * 24
    source = SourceDocument((TableBlock('long-labels', (
        ('Group', 'Count', None), (None, '2022', '2023'),
        *((group, value, value) for group in groups),
    )),))

    def respond(payload, _schema):
        fact = payload['source_facts'][0]
        return {'comparisons': [{'fact_id': fact['id'], 'group': fact['subject'],
                                 'metric': fact['target'], **fact['qualifiers']}]}

    document = build_comparison_preview(source, 'Report', 4, propose=respond)
    assert len(document.slides) == 4
    body = '\n'.join(slide.body for slide in document.slides[1:-1])
    assert all(group in body for group in groups)
