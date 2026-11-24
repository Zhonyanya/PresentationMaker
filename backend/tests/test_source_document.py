import pytest

from app.presentations.pdf_blocks import pdf_blocks
from app.presentations.pdf_source import SourcePage, SourceParagraph, SourceTable
from presentation_ml.source_document import (
    build_source_payload,
    prepare_evidence,
    read_source_json,
    review_sections,
    source_glossary,
    text_blocks,
)
from presentation_ml.source_reply import verified_table_claim


@pytest.mark.parametrize('heading', ['Recommendations', 'Рекомендации'])
def test_review_sections_keeps_recommendations_across_pdf_folios(heading):
    first = 'Collect participation data separately for each route and subject.'
    second = 'Evaluate longer-term outcomes in a separate follow-up study.'
    pages = (
        SourcePage(15, '', (), (), paragraphs=(
            SourceParagraph(30, 0, heading),
            SourceParagraph(60, 0, first),
            SourceParagraph(720, 0, '15'),
        )),
        SourcePage(16, '', (), (), paragraphs=(
            SourceParagraph(30, 0, second),
            SourceParagraph(60, 0, 'References'),
            SourceParagraph(90, 0, 'The methods paper contains the full selection criteria.'),
        )),
    )
    assert review_sections(pdf_blocks(pages)) == {'proposed': [first, second]}


def test_review_sections_keep_unheaded_method_change_and_complete_period_comparisons():
    travel = 'People made 841 trips on average in 2025.'
    baseline = 'This was down from 922 trips in 2024.'
    distance = 'People travelled 5,605 miles in 2025, down from 6,082 miles in 2024.'
    school = 'Walking to school accounted for 47% of trips in 2025, down from 51% in 2024.'
    caveat = (
        'The introduction of a digital travel diary in 2025 was associated with lower recorded '
        'rates for short trips. Statistics based on interview questions are not affected.'
    )
    source = text_blocks('\n\n'.join([
        caveat, f'{travel} {baseline} {distance}', school,
        'The introduction of an online diary was announced at the annual meeting.',
        'The committee met in 2024 and again in 2025 to review its schedule.',
    ]))

    assert review_sections(source) == {
        'method_changes': [caveat],
        'period_comparisons': [f'{travel} {baseline}', school, distance],
    }


def test_source_glossary_keeps_only_unambiguous_literal_expansions():
    source = text_blocks(
        'The Board of Governors (BG) commissioned the study. Key Stage 2 (KS2) was included.\n\n'
        'Project Management (PM) had a workstream. Power Mode (PM) had another workstream.\n\n'
        'One route was omitted (ZZ). Территориальный общественный центр (ТОЦ) участвовал.'
    )
    assert source_glossary(source) == [
        {'abbreviation': 'BG', 'definition': 'Board of Governors',
         'source': {'block_id': 'text-1'}},
        {'abbreviation': 'KS2', 'definition': 'Key Stage 2', 'source': {'block_id': 'text-1'}},
        {'abbreviation': 'ТОЦ', 'definition': 'Территориальный общественный центр',
         'source': {'block_id': 'text-3'}},
    ]


def test_pdf_reference_and_comparison_keep_distinct_source_addresses():
    row = ('Городские школы', '20', '35')
    table = SourceTable((0, 0, 1, 1), (
        ('Группа', 'Количество участников', None),
        (None, '2022 год', '2023 год'),
        row,
    ), '18')
    page = SourcePage(76, 'Динамика участия представлена в таблице 18.', (table,), ())
    _, evidence = prepare_evidence(pdf_blocks((page,)), limit=2)
    reference, comparison = evidence
    assert (reference.block_id, reference.related_block_id) == ('p76-text', 'p76-table-1')
    assert (comparison.block_id, comparison.row) == ('p76-table-1', 3)
    assert comparison.edge.table_row == row


def test_text_adapter_supplies_evidence_without_inventing_page_numbers():
    source = text_blocks('ООО «Вектор» участвует в программе «Пилот».')
    _, (evidence,) = prepare_evidence(source, limit=1)
    assert evidence.block_id == 'text-1'
    assert evidence.edge.page is None


def test_docx_wire_blocks_keep_table_row_without_pdf_pagination():
    source = read_source_json('''{"blocks": [
        {"id":"docx-1","kind":"text","text":"Динамика участия представлена в таблице 18."},
        {"id":"docx-2","kind":"table","number":"18","rows":[
            ["Группа","Количество участников",null],[null,"2022","2023"],["Школы","20","35"]
        ]}
    ]}''')
    _, (reference, comparison) = prepare_evidence(source, limit=2)
    assert reference.related_block_id == comparison.block_id == 'docx-2'
    assert comparison.row == 3
    assert comparison.edge.page is None
    reference_fact, comparison_fact = build_source_payload(source, limit=2)['source_facts']
    assert reference_fact['related_block_id'] == 'docx-2'
    assert comparison_fact['source'] == {'block_id': 'docx-2', 'table_number': '18', 'row': 3}
    assert comparison_fact['qualifiers'] == {
        'first_period': '2022', 'first_value': '20', 'second_period': '2023', 'second_value': '35',
    }
    assert comparison_fact['source_row'] == ['Школы', '20', '35']
    payload = {'source_facts': [reference_fact, comparison_fact]}
    reply = {
        'fact_id': comparison_fact['id'], 'group': 'Школы', 'metric': 'Количество участников',
        'first_period': '2022', 'first_value': '20', 'second_period': '2023', 'second_value': '35',
    }
    assert verified_table_claim(payload, reply) == {
        'title': 'Количество участников',
        'body': 'Школы\n2022 — 20\n2023 — 35',
        'source': comparison_fact['source'],
    }
    for field, value in [('fact_id', 'unknown'), ('second_value', '36'), ('first_period', '2021')]:
        with pytest.raises(ValueError):
            verified_table_claim(payload, {**reply, field: value})


def test_text_blocks_preserves_pasted_table_and_surrounding_prose():
    source = text_blocks(
        'Monthly loans\n'
        '| Month | Loans, units |\n'
        '| :--- | ---: |\n'
        '| January | 48 |\n'
        '| February | 62 |\n'
        'Completed loans only.'
    )
    heading, table, caveat = source.blocks
    assert heading.text == 'Monthly loans'
    assert table.kind == 'table'
    assert table.id
    assert table.rows == (('Month', 'Loans, units'), ('January', '48'), ('February', '62'))
    assert caveat.text == 'Completed loans only.'
