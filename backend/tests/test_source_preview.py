import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.presentations.routes import pdf_preview
from app.presentations.schemas import Document
from app.presentations.source_preview import build_comparison_preview
from presentation_ml.source_document import SourceDocument, TableBlock


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
