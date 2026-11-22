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
    'context': re.compile(
        r'^(?:введение|контекст|исходные условия|охват(?: оценки)?|'
        r'introduction|background|context|(?:purpose and )?scope)$',
        re.I,
    ),
    'observed': re.compile(
        r'^(?:результаты(?:\s|$)|что не получилось$|findings$|results\b|what went wrong$)', re.I,
    ),
    'limitations': re.compile(
        r'^(?:ограничения(?:\s|$)|границы вывода$|(?:study )?limitations\b)', re.I,
    ),
    'proposed': re.compile(
        r'^(?:предложение по следующему этапу$|следующ(?:ий этап|ие шаги)(?:\s|$)|'
        r'рекомендации(?:\s|$)|next steps\b|recommendations?(?: for .+)?$)',
        re.I,
    ),
}
_REVIEW_LIST_MARKER = re.compile(r'^(?:[•—–-]|\d{1,3}[.)])\s+')
_METHOD_CHANGE = re.compile(
    r'\b(?:introduction|change[ds]?|switch|transition|revis(?:ed|ion)|replac(?:ed|ement)|'
    r'введени\w*|переход\w*|изменен\w*|изменён\w*|замен\w*)\b', re.I,
)
_MEASUREMENT_METHOD = re.compile(
    r'\b(?:\w+ diary|questionnaire|data collection|collection method|survey method|'
    r'дневник\w*|анкет\w*|(?:способ\w*|метод\w*) (?:сбора|регистрации|уч[её]та))\b', re.I,
)
_MEASUREMENT_EFFECT = re.compile(
    r'\b(?:(?:lower|higher) (?:recorded|reported)|break in (?:the )?series|'
    r'(?:affect\w*|limit\w*) comparability|not directly comparable|'
    r'сопоставимост\w*|(?:снижен\w*|рост\w*) (?:числа |доли )?'
    r'(?:учт[её]нных|зарегистрированных))\b',
    re.I,
)
_REVIEW_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+(?=[A-ZА-ЯЁ«“])')
_PERIOD_COMPARISON = re.compile(
    r'\b(?:compared (?:to|with)|(?:up|down) from|(?:higher|lower) than|versus|'
    r'по сравнению с|против|вместо)\b', re.I,
)
_COMPARISON_CONTINUATION = re.compile(
    r'^(?:this\b|it\s+(?:was|is)\b|это\b|что\b|по сравнению с\b)', re.I,
)
_PERIOD_YEAR = re.compile(r'\b(?:19|20)\d{2}\b')
_COMPARISON_VALUE = re.compile(r'\b\d+(?:[,. ]\d+)*')
_ABBREVIATION = re.compile(r'\(([A-ZА-ЯЁ][A-ZА-ЯЁ0-9]{1,9})\)')
_DEFINITION_WORD = re.compile(r'[^\W_]+')
_DEFINITION_BOUNDARY = re.compile(r'[.!?,:;()]')
_CONNECTIVES = frozenset({'and', 'by', 'for', 'in', 'of', 'the', 'в', 'для', 'и', 'по'})


def _literal_definition(paragraph: str, end: int, abbreviation: str) -> str | None:
    start = max(0, end - 160)
    if start and paragraph[start - 1].isalnum() and paragraph[start].isalnum():
        space = paragraph.find(' ', start, end)
        if space < 0:
            return None
        start = space + 1
    prefix = paragraph[start:end]
    phrase = _DEFINITION_BOUNDARY.split(prefix)[-1].rstrip()
    words = list(_DEFINITION_WORD.finditer(phrase))[-len(abbreviation) - 2:]
    index = len(abbreviation) - 1
    for word in reversed(words):
        name = word[0]
        initial = name if name.isdecimal() else name[0].upper()
        if initial == abbreviation[index]:
            if index == 0:
                return phrase[word.start():]
            index -= 1
        elif index == len(abbreviation) - 1 or name.casefold() not in _CONNECTIVES:
            break
    return None


def source_glossary(source: SourceDocument) -> list[dict]:
    """Return literal, unambiguous definitions from parenthesized abbreviations."""
    entries = {}
    conflicts = set()
    for block in source.blocks:
        if not isinstance(block, TextBlock):
            continue
        paragraph = ' '.join(block.text.split())
        for match in _ABBREVIATION.finditer(paragraph):
            abbreviation = match[1]
            definition = _literal_definition(paragraph, match.start(), abbreviation)
            if definition is None:
                continue
            previous = entries.get(abbreviation)
            if previous:
                if definition.casefold() != previous['definition'].casefold():
                    conflicts.add(abbreviation)
                continue
            address = {'block_id': block.id}
            if block.page is not None:
                address['page'] = block.page
            entries[abbreviation] = {
                'abbreviation': abbreviation, 'definition': definition, 'source': address,
            }
    return list(islice((entry for key, entry in entries.items() if key not in conflicts), 12))


def _period_comparisons(paragraph: str) -> list[str]:
    sentences = _REVIEW_SENTENCE_BREAK.split(paragraph)
    excerpts = []
    for index, sentence in enumerate(sentences):
        if not _PERIOD_COMPARISON.search(sentence):
            continue
        excerpt = sentence
        if index and _COMPARISON_CONTINUATION.match(sentence):
            excerpt = f'{sentences[index - 1]} {sentence}'
        if (len(excerpt) <= 460 and len(set(_PERIOD_YEAR.findall(excerpt))) >= 2
                and len(_COMPARISON_VALUE.findall(_PERIOD_YEAR.sub(' ', excerpt))) >= 2):
            excerpts.append(excerpt)
    return excerpts


def review_sections(source: SourceDocument) -> dict[str, list[str]]:
    """Surface literal excerpts from labeled sections and qualified comparisons."""
    sections = defaultdict(list)
    current = None
    for block in source.blocks:
        if not isinstance(block, TextBlock):
            current = None
            continue
        paragraph = ' '.join(block.text.split())
        if block.page is not None and paragraph == str(block.page):
            continue
        if (len(paragraph) <= 500 and _METHOD_CHANGE.search(paragraph)
                and _MEASUREMENT_METHOD.search(paragraph)
                and _MEASUREMENT_EFFECT.search(paragraph)):
            sections['method_changes'].append([paragraph])
        comparisons = _period_comparisons(paragraph)
        if comparisons:
            sections['period_comparisons'].append(comparisons)
        if (len(paragraph) <= 90 and not paragraph.endswith(('.', '!', '?', ';'))
                and '\n' not in block.text.strip()):
            heading = _REVIEW_LIST_MARKER.sub('', paragraph.rstrip(':'))
            role = next(
                (key for key, rule in _REVIEW_HEADINGS.items() if rule.match(heading)), None,
            )
            if role:
                paragraphs = []
                current = (role, paragraphs)
                sections[role].append(paragraphs)
                continue
            if not _REVIEW_LIST_MARKER.match(paragraph):
                current = None
                continue
        if current is not None:
            active_role, paragraphs = current
            minimum = 15 if active_role == 'limitations' else 20
            if minimum <= len(paragraph) <= 500:
                paragraphs.append(paragraph)

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
