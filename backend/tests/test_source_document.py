import pytest

from app.presentations.pdf_blocks import pdf_blocks
from app.presentations.pdf_source import SourcePage, SourceTable
from presentation_ml.source_document import (
    build_source_payload,
    prepare_evidence,
    read_source_json,
    text_blocks,
)
from presentation_ml.source_reply import verified_table_claim


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
