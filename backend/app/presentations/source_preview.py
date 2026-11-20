"""Build comparison slides from verified rows and a structured reply."""

import re
from collections.abc import Callable
from copy import deepcopy
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError
from app.presentations.source_blocks import IllustrationBlock, SourceDocument, TableBlock
from presentation_ml.source_document import build_source_payload
from presentation_ml.source_reply import TableClaim, verified_table_claim

from .schemas import Document


class ComparisonReply(BaseModel):
    model_config = ConfigDict(extra='forbid')

    comparisons: list[TableClaim]


def linked_illustrations(source: SourceDocument, payload: dict) -> dict[str, IllustrationBlock]:
    """Resolve a chart only when the same source statement names both materials."""
    figures = [block for block in source.blocks if isinstance(block, IllustrationBlock)]
    tables = {block.id: block for block in source.blocks if isinstance(block, TableBlock)}
    links: dict[str, set[IllustrationBlock]] = {}
    facts = payload['source_facts']
    for table_fact in facts:
        if table_fact['relation'] != 'tabulated_in' or 'related_block_id' not in table_fact:
            continue
        table = tables[table_fact['related_block_id']]
        for figure_fact in facts:
            if (
                figure_fact['relation'] != 'illustrated_by'
                or figure_fact['source'] != table_fact['source']
                or figure_fact.get('quote') != table_fact.get('quote')
            ):
                continue
            label = figure_fact['target'].casefold()
            matches = [
                figure for figure in figures if figure.page == table.page
                and re.match(
                    rf'{re.escape(label)}\b', re.sub(r'\s*№\s*', ' ', figure.caption.casefold()),
                )
            ]
            if len(matches) == 1:
                links.setdefault(table.id, set()).add(matches[0])
    return {key: next(iter(value)) for key, value in links.items() if len(value) == 1}


def build_comparison_preview(
    source: SourceDocument, title: str, slide_count: int, *,
    propose: Callable[[dict, dict], object],
    render: Callable[[IllustrationBlock], dict] | None = None,
) -> Document:
    """Run a supplied offline responder and return a validated presentation."""
    if not 3 <= slide_count <= 20:
        raise ValueError('Slide count must be between 3 and 20')
    comparison_slots = slide_count - 2
    payload = build_source_payload(
        source, limit=3 * comparison_slots, relations=frozenset({'metric_comparison'}),
    )
    if not payload['source_facts']:
        raise AppError(
            422, 'NO_TABLE_COMPARISONS', 'В таблицах нет распознанных сравнений по периодам.',
        )
    schema = ComparisonReply.model_json_schema()
    schema['properties']['comparisons'].update(minItems=1, maxItems=comparison_slots)
    # Keep the authoritative packet separate from the responder's copy.
    reply = ComparisonReply.model_validate(propose(deepcopy(payload), schema))
    ids = [claim.fact_id for claim in reply.comparisons]
    if not 1 <= len(ids) <= comparison_slots or len(set(ids)) != len(ids):
        raise ValueError('Invalid comparison slide count or duplicate fact')
    slides = [{'id': str(uuid4()), 'layout': 'title', 'title': title}]
    links = linked_illustrations(source, build_source_payload(
        source, limit=1000, relations=frozenset({'tabulated_in', 'illustrated_by'}),
    )) if render else {}
    used_figures = set()
    for claim in reply.comparisons:
        content = verified_table_claim(payload, claim.model_dump())
        address = content['source']
        location = [f'блок {address["block_id"]}', f'строка {address["row"]}']
        if 'table_number' in address:
            location.insert(0, f'таблица {address["table_number"]}')
        if 'page' in address:
            location.insert(0, f'стр. {address["page"]}')
        slide = {
            'id': str(uuid4()), 'layout': 'text',
            'title': content['title'], 'body': content['body'],
            'notes': 'Источник — ' + ', '.join(location),
        }
        figure = links.get(address['block_id'])
        if render and figure and figure.id not in used_figures:
            try:
                slide['sourceMaterial'] = {**render(figure), 'page': figure.page}
            except (ValueError, OSError):
                pass
            else:
                group, first, second = content['body'].split('\n')
                slide['body'] = f'{group}\n{first} · {second}'
                slide['notes'] += f', {figure.caption}'
                used_figures.add(figure.id)
        slides.append(slide)
    slides.append({'id': str(uuid4()), 'layout': 'closing', 'title': 'Итоги сравнений'})
    return Document.model_validate({'title': title, 'slides': slides})
