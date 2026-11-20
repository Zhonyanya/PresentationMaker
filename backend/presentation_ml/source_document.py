"""Format-independent source blocks for offline preparation of slide evidence."""

from collections import defaultdict
from dataclasses import dataclass

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
    paragraphs = (part.strip() for part in text.split('\n\n'))
    return SourceDocument(tuple(
        TextBlock(f'text-{index}', part) for index, part in enumerate(paragraphs, 1) if part
    ))


def prepare_evidence(
    source: SourceDocument, *, limit: int, relations: frozenset[str] | None = None,
) -> tuple[KnowledgeGraph, tuple[Evidence, ...]]:
    """Rank graph assertions with resolvable evidence, preferring named entities."""
    if limit < 1:
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
    source: SourceDocument, *, limit: int = 12, relations: frozenset[str] | None = None,
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
