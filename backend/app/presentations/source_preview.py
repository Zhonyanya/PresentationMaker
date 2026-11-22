"""Build comparison slides from verified rows and a structured reply."""

import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from copy import deepcopy
from itertools import islice, zip_longest
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError
from app.presentations.source_blocks import IllustrationBlock, SourceDocument, TableBlock
from presentation_ml.source_document import build_source_payload
from presentation_ml.source_reply import (
    COMPARISON_CATEGORY_LIMIT,
    TableClaim,
    table_claim_from_fact,
    table_comparison_chart,
    verified_table_claim,
)

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


def _comparison_key(fact: dict) -> tuple[str, str, str, str, bool]:
    qualifiers = fact['qualifiers']
    return (fact['source']['block_id'], fact['target'], qualifiers['first_period'],
            qualifiers['second_period'], qualifiers['first_value'].endswith('%'))


def _direction_groups(chart: dict) -> dict[str, list[str]]:
    before, after = (series['values'] for series in chart['series'])
    directions = {'Рост': [], 'Снижение': [], 'Без изменений': []}
    for group, left, right in zip(chart['categories'], before, after, strict=True):
        direction = 'Рост' if right > left else 'Снижение' if right < left else 'Без изменений'
        directions[direction].append(group)
    return directions


def _literal_comparison(claim: TableClaim) -> str:
    return (
        f'{claim.group}. {claim.first_period} — {claim.first_value}; '
        f'{claim.second_period} — {claim.second_value}'
    )


def _comparison_batches(facts: list[dict]) -> Iterator[tuple[str, ...]]:
    batch = []
    size = 0
    for fact in sorted(facts, key=lambda item: item['source']['row']):
        line_size = len(_literal_comparison(table_claim_from_fact(fact)).encode('utf-16-le')) // 2
        if batch and (len(batch) == COMPARISON_CATEGORY_LIMIT or size + 1 + line_size > 4000):
            yield tuple(batch)
            batch, size = [], 0
        size += int(bool(batch)) + line_size
        batch.append(fact['id'])
    if batch:
        yield tuple(batch)


def _comparison_slide(facts: list[dict]) -> dict:
    claims = [table_claim_from_fact(fact) for fact in facts]
    first = claims[0]
    address = facts[0]['source']
    row_numbers = ', '.join(str(fact['source']['row']) for fact in facts)
    row_label = 'строка' if len(facts) == 1 else 'строки'
    location = [f'блок {address["block_id"]}', f'{row_label} {row_numbers}']
    if 'table_number' in address:
        location.insert(0, f'таблица {address["table_number"]}')
    if 'page' in address:
        location.insert(0, f'стр. {address["page"]}')
    slide = {
        'id': str(uuid4()), 'layout': 'text', 'title': first.metric,
        'notes': 'Источник — ' + ', '.join(location),
    }
    chart = table_comparison_chart(claims)
    if chart is not None:
        slide['composition'] = chart
    if len(claims) == 1:
        slide['body'] = '\n'.join((first.group, f'{first.first_period} — {first.first_value}',
                                   f'{first.second_period} — {first.second_value}'))
    elif chart is not None:
        slide['body'] = '\n'.join(
            f'{direction} — {", ".join(groups)}.'
            for direction, groups in _direction_groups(chart).items() if groups
        )
    else:
        table_rows = [['Группа', first.first_period, first.second_period],
                      *[[claim.group, claim.first_value, claim.second_value] for claim in claims]]
        slide['body'] = '\n'.join(_literal_comparison(claim) for claim in claims)
        if ('page' in address
                and all(len(cell.encode('utf-16-le')) // 2 <= 300
                        for row in table_rows for cell in row)):
            slide['sourceMaterial'] = {'kind': 'table', 'page': address['page'], 'rows': table_rows}
    return slide


def build_comparison_preview(
    source: SourceDocument, title: str, slide_count: int, *,
    propose: Callable[[dict, dict], object],
    render: Callable[[IllustrationBlock], dict] | None = None,
) -> Document:
    """Run a supplied offline responder and return a validated presentation."""
    if not 3 <= slide_count <= 20:
        raise ValueError('Slide count must be between 3 and 20')
    comparison_slots = slide_count - 2
    facts = build_source_payload(
        source, limit=None, relations=frozenset({'metric_comparison'}),
    )['source_facts']
    if not facts:
        raise AppError(
            422, 'NO_TABLE_COMPARISONS', 'В таблицах нет распознанных сравнений по периодам.',
        )
    by_id = {fact['id']: fact for fact in facts}
    families = defaultdict(list)
    for fact in facts:
        families[_comparison_key(fact)].append(fact)
    # Give different tables and period pairs a chance to be selected even when
    # the first table has many rows. Keep the prompt packet bounded.
    candidates = (
        fact for row in zip_longest(*families.values()) for fact in row if fact is not None
    )
    payload = {'source_facts': list(islice(candidates, 3 * comparison_slots))}
    schema = ComparisonReply.model_json_schema()
    schema['properties']['comparisons'].update(minItems=1, maxItems=comparison_slots)
    # Keep the authoritative packet separate from the responder's copy.
    reply = ComparisonReply.model_validate(propose(deepcopy(payload), schema))
    ids = [claim.fact_id for claim in reply.comparisons]
    if not 1 <= len(ids) <= comparison_slots or len(set(ids)) != len(ids):
        raise ValueError('Invalid comparison slide count or duplicate fact')
    for claim in reply.comparisons:
        verified_table_claim(payload, claim)

    keys = dict.fromkeys(_comparison_key(by_id[identifier]) for identifier in ids)
    ordered_batches = [batch for key in keys for batch in _comparison_batches(families[key])]
    batch_by_id = {identifier: batch for batch in ordered_batches for identifier in batch}
    priority = dict.fromkeys([*(batch_by_id[identifier] for identifier in ids), *ordered_batches])
    visible = set(islice(priority, comparison_slots))
    slides = [{'id': str(uuid4()), 'layout': 'title', 'title': title}]
    links = linked_illustrations(source, build_source_payload(
        source, limit=1000, relations=frozenset({'tabulated_in', 'illustrated_by'}),
    )) if render else {}
    used_figures = set()
    for batch in ordered_batches:
        if batch not in visible:
            continue
        rows = [by_id[identifier] for identifier in batch]
        slide = _comparison_slide(rows)
        address = rows[0]['source']
        figure = links.get(address['block_id'])
        if len(batch) == 1 and render and figure and figure.id not in used_figures:
            try:
                slide['sourceMaterial'] = {**render(figure), 'page': figure.page}
            except (ValueError, OSError):
                pass
            else:
                group, first, second = slide['body'].split('\n')
                slide['body'] = f'{group}\n{first} · {second}'
                slide['notes'] += f', {figure.caption}'
                slide.pop('composition', None)
                used_figures.add(figure.id)
        slides.append(slide)
    closing = {'id': str(uuid4()), 'layout': 'closing', 'title': 'Итоги сравнений'}
    shown = sum(len(batch) for batch in visible)
    available = len(batch_by_id)
    if shown < available:
        closing['subtitle'] = f'Показано {shown} из {available} строк выбранных сравнений.'
    elif len(visible) == 1 and shown > 1 and 'composition' in slides[-1]:
        directions = _direction_groups(slides[-1]['composition'])
        closing['subtitle'] = f'Из {shown} групп: ' + ', '.join(
            f'{direction.lower()} — {len(groups)}' for direction, groups in directions.items()
        ) + '.'
    slides.append(closing)
    return Document.model_validate({'title': title, 'slides': slides})
