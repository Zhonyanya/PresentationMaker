"""Format-independent source blocks for offline preparation of slide evidence."""

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice, zip_longest

from app.presentations.source_blocks import (
    SOURCE_ADAPTER,
    SourceDocument,
    TableBlock,
    TextBlock,
)

from .grounding import recognize_entities
from .knowledge_graph import KnowledgeGraph, RelationEdge, ReportTable, build_knowledge_graph


def read_source_json(payload: str | bytes) -> SourceDocument:
    return SOURCE_ADAPTER.validate_json(payload)


@dataclass(frozen=True)
class Evidence:
    block_id: str
    edge: RelationEdge
    row: int | None = None
    related_block_id: str | None = None


def text_blocks(text: str) -> SourceDocument:
    paragraphs = (part.strip() for part in re.split(r'\r?\n[ \t]*\r?\n', text))
    return SourceDocument(tuple(
        TextBlock(f'text-{index}', part) for index, part in enumerate(paragraphs, 1) if part
    ))


_REVIEW_HEADINGS = {
    'observed': re.compile(
        r'^(?:результаты(?:\s|$)|что не получилось$|findings$|results\b|what went wrong$)', re.I,
    ),
    'limitations': re.compile(
        r'^(?:ограничения(?:\s|$)|границы вывода$|(?:study )?limitations\b)', re.I,
    ),
    'proposed': re.compile(
        r'^(?:предложение по следующему этапу$|следующ(?:ий этап|ие шаги)(?:\s|$)|next steps\b)',
        re.I,
    ),
}
_REVIEW_LIST_MARKER = re.compile(r'^(?:[•—–-]|\d{1,3}[.)])\s+')


def review_sections(source: SourceDocument) -> dict[str, list[str]]:
    """Surface literal paragraphs from explicit report sections, in bounded groups."""
    sections = defaultdict(list)
    current = None
    for block in source.blocks:
        if not isinstance(block, TextBlock):
            current = None
            continue
        paragraph = ' '.join(block.text.split())
        if (len(paragraph) <= 90 and not paragraph.endswith(('.', '!', '?', ';'))
                and '\n' not in block.text.strip()):
            heading = _REVIEW_LIST_MARKER.sub('', paragraph.rstrip(':'))
            role = next(
                (key for key, rule in _REVIEW_HEADINGS.items() if rule.match(heading)), None,
            )
            if role:
                current = []
                sections[role].append(current)
                continue
            if not _REVIEW_LIST_MARKER.match(paragraph):
                current = None
                continue
        if current is not None and 20 <= len(paragraph) <= 500:
            current.append(paragraph)

    excerpts = {}
    for role, groups in sections.items():
        # Interleave sections of the same kind so a long results section cannot
        # crowd out later observations about how the pilot actually ran.
        candidates = (paragraph for row in zip_longest(*groups)
                      for paragraph in row if paragraph is not None)
        chosen = list(islice(candidates, 6 if role == 'observed' else 4))
        if chosen:
            excerpts[role] = chosen
    return excerpts


def prepare_evidence(
    source: SourceDocument, *, limit: int | None, relations: frozenset[str] | None = None,
) -> tuple[KnowledgeGraph, tuple[Evidence, ...]]:
    """Rank graph assertions with resolvable evidence, preferring named entities."""
    if limit is not None and limit < 1:
        raise ValueError('Evidence limit must be positive')
    texts = [block for block in source.blocks if isinstance(block, TextBlock)]
    tables = [block for block in source.blocks if isinstance(block, TableBlock)]
    # Internal table keys are unique even when caption numbers repeat or are missing.
    by_id = {block.id: block for block in tables}
    graph = build_knowledge_graph(
        ((block.page, block.text) for block in texts),
        tables=(
            ReportTable(block.page, block.id, block.rows) for block in tables if block.comparable
        ),
    )
    candidates = []
    names = {node.id: node.name for node in graph.nodes}
    normalized = defaultdict(list)
    for block in texts:
        normalized[block.page].append((block, ' '.join(block.text.split())))
    for edge in graph.select_edges(limit=max(1, len(graph.edges)), relations=relations):
        if edge.table_row is not None:
            fields = dict(edge.qualifiers)
            table = by_id[fields['table']]
            candidates.append((0, Evidence(table.id, edge, int(fields['row']))))
        elif edge.quote:
            matches = [
                block for block, content in normalized[edge.page] if edge.quote in content
            ]
            if len(matches) == 1:
                related = None
                if edge.relation == 'tabulated_in':
                    number = names[edge.target].rsplit(' ', 1)[-1]
                    referenced = [
                        table for table in tables
                        if table.page == edge.page and table.number == number
                    ]
                    if len(referenced) == 1:
                        related = referenced[0].id
                candidates.append((
                    len(recognize_entities(edge.quote)),
                    Evidence(matches[0].id, edge, related_block_id=related),
                ))
    candidates.sort(key=lambda item: -item[0])
    return graph, tuple(evidence for _, evidence in candidates[:limit])


def build_source_payload(
    source: SourceDocument, *, limit: int | None = 12, relations: frozenset[str] | None = None,
) -> dict:
    """Build JSON-ready facts and their source addresses."""
    graph, evidence = prepare_evidence(source, limit=limit, relations=relations)
    entities = {node.id: node.name for node in graph.nodes}
    tables = {block.id: block for block in source.blocks if isinstance(block, TableBlock)}
    facts = []
    for index, item in enumerate(evidence, 1):
        edge = item.edge
        qualifiers = dict(edge.qualifiers)
        address = {'block_id': item.block_id}
        if edge.page is not None:
            address['page'] = edge.page
        if item.row is not None:
            address['row'] = item.row
            table_number = tables[item.block_id].number
            if table_number is not None:
                address['table_number'] = table_number
            qualifiers.pop('table')
            qualifiers.pop('row')
        fact = {
            'id': f'fact-{index}',
            'subject': entities[edge.subject],
            'relation': edge.relation,
            'target': entities[edge.target],
            'status': edge.status,
            'qualifiers': qualifiers,
            'source': address,
        }
        if edge.quote is not None:
            fact['quote'] = edge.quote
        if edge.table_row is not None:
            fact['source_row'] = list(edge.table_row)
        if item.related_block_id is not None:
            fact['related_block_id'] = item.related_block_id
        facts.append(fact)
    return {'source_facts': facts}
