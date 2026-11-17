"""Offline prototype for explicit entity relations in a single report."""

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal
from uuid import uuid4

from .grounding import recognize_entities

_SENTENCES = re.compile(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«])')
_ALIAS = re.compile(r'^\s*\(далее\s*[—–-]?\s*(«[^»\n]{1,100}»)\)', re.I)
_QUOTED_NAME = re.compile(r'^«[^»\n]{1,100}»')
_PROGRAM = re.compile(r'\bпрограмм[аеуы]\s+«([^»\n]{1,100})»', re.I)
_PARTICIPATION = re.compile(
    r'^\s+(?:(?P<planned>планирует участвовать)|(?P<denied>не участвует)|участвует)'
    r'\s+в программе «(?P<target>[^»\n]{1,100})»'
    r'(?: с (?P<since>[^.!?;]+))?[.!?]?$', re.I,
)
_RESPONSIBILITY = re.compile(
    r'^\s+отвечает за реализацию программы «(?P<target>[^»\n]{1,100})»[.!?]?$', re.I,
)
_CHANGE = re.compile(
    r'^\s+(?P<verb>увеличил[аио]?|снизил[аио]?) (?P<target>охват|численность|долю)'
    r' с (?P<before>\d+(?:[.,]\d+)?)\s*% до (?P<after>\d+(?:[.,]\d+)?)\s*%'
    r'(?: в (?P<period>\d{4} году))?(?: (?P<scope>в [^.!?;]+))?[.!?]?$', re.I,
)
_REFERENCE = r'(?:на (?:диаграмме|рисунке|графике)|в таблице)\s+(?:№\s*)?\d+'
_PRESENTED_IN = re.compile(
    rf'^(?P<topic>[А-ЯЁ][^.!?;:]{{8,159}}?)\s+представлен(?:а|о|ы)?\s+'
    rf'(?P<references>{_REFERENCE}(?:(?:,\s*| и ){_REFERENCE})*)[.!?]?$', re.I,
)
_REFERENCE_ITEM = re.compile(r'(диаграмме|рисунке|графике|таблице)\s+(?:№\s*)?(\d+)', re.I)
_REFERENCE_LABELS = {
    'диаграмме': 'Диаграмма', 'рисунке': 'Рисунок', 'графике': 'График', 'таблице': 'Таблица',
}
_YEAR = re.compile(r'(\d{4})(?:\s+(?:год|г\.))?', re.I)
_VALUE = re.compile(r'[+-]?(?:\d+|\d{1,3}(?: \d{3})+)(?:[.,]\d+)?(?:\s*%)?')


@dataclass(frozen=True)
class EntityNode:
    id: int
    kind: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class RelationEdge:
    subject: int
    relation: Literal[
        'participates_in', 'responsible_for', 'metric_change', 'metric_comparison',
        'illustrated_by', 'tabulated_in',
    ]
    target: int
    status: Literal['reported', 'planned', 'denied']
    page: int | None
    quote: str | None
    qualifiers: tuple[tuple[str, str], ...] = ()
    table_row: tuple[str | None, ...] | None = None


@dataclass(frozen=True)
class ReportTable:
    page: int | None
    number: str
    rows: tuple[tuple[str | None, ...], ...]


@dataclass(frozen=True)
class KnowledgeGraph:
    nodes: tuple[EntityNode, ...]
    edges: tuple[RelationEdge, ...]

    def select_edges(self, *, limit: int) -> tuple[RelationEdge, ...]:
        """Select distinct assertions in source order, retaining their evidence."""
        if limit < 1:
            raise ValueError('Relation limit must be positive')
        selected = {}
        for edge in self.edges:
            key = (edge.subject, edge.relation, edge.target, edge.status, edge.qualifiers)
            selected.setdefault(key, edge)
            if len(selected) == limit:
                break
        return tuple(selected.values())


def _key(name: str) -> str:
    return ' '.join(name.casefold().split())


def _sentences(pages: Iterable[tuple[int | None, str]]) -> Iterable[tuple[int | None, str]]:
    for page, text in pages:
        if page is not None:
            first_line, separator, remaining = text.lstrip().partition('\n')
            if separator and re.fullmatch(r'\d{1,4}', first_line.strip()):
                text = remaining
        for paragraph in re.split(r'\n\s*\n', text):
            for sentence in _SENTENCES.split(' '.join(paragraph.split())):
                if sentence:
                    yield page, sentence


def _leading_organization(quote: str, entities: list[tuple[str, str]]) -> str | None:
    return next((name for kind, name in entities
                 if kind == 'organization' and quote.startswith(name)), None)


def _extract_relation(
    subject: int, tail: str, page: int | None, quote: str, node: Callable[[str, str], int],
) -> RelationEdge | None:
    if match := _PARTICIPATION.fullmatch(tail):
        status = 'planned' if match['planned'] else 'denied' if match['denied'] else 'reported'
        qualifiers = (('since', match['since']),) if match['since'] else ()
        return RelationEdge(
            subject, 'participates_in', node('program', match['target']),
            status, page, quote, qualifiers,
        )
    if match := _RESPONSIBILITY.fullmatch(tail):
        return RelationEdge(
            subject, 'responsible_for', node('program', match['target']), 'reported', page, quote,
        )
    if match := _CHANGE.fullmatch(tail):
        before, after = match['before'], match['after']
        increasing = float(after.replace(',', '.')) > float(before.replace(',', '.'))
        decreasing = float(after.replace(',', '.')) < float(before.replace(',', '.'))
        if not (increasing if match['verb'].casefold().startswith('увелич') else decreasing):
            return None
        qualifiers = [('before', before), ('after', after), ('unit', '%')]
        qualifiers.extend((key, match[key]) for key in ('period', 'scope') if match[key])
        name = 'доля' if match['target'].casefold() == 'долю' else match['target'].casefold()
        return RelationEdge(
            subject, 'metric_change', node('metric', name), 'reported', page, quote,
            tuple(qualifiers),
        )
    return None


def _table_relations(table: ReportTable, node: Callable[[str, str], int]) -> Iterable[RelationEdge]:
    if len(table.rows) < 3:
        return
    header, periods, *data = table.rows
    if len(header) != len(periods):
        return
    labels = [' '.join((cell or '').split()) for cell in periods]
    first = next((index for index, label in enumerate(labels) if _YEAR.fullmatch(label)), 0)
    years = [_YEAR.fullmatch(label) for label in labels[first:]]
    if first < 1 or len(years) < 2 or not all(years):
        return
    year_labels = [match[1] for match in years]
    if len(set(year_labels)) != len(year_labels):
        return
    metric = ' '.join((header[first] or '').split())
    if not metric or not header[first - 1] or any(header[first + 1:]) or len(metric) > 180:
        return
    for row_index, row in enumerate(data, 3):
        if len(row) != len(header):
            continue
        group = ' '.join((row[first - 1] or '').split())
        if not group or len(group) > 300:
            continue
        values = [' '.join((cell or '').split()) for cell in row[first:]]
        for index, (left, right) in enumerate(pairwise(values)):
            if not all(len(value) <= 24 and _VALUE.fullmatch(value) for value in (left, right)):
                continue
            if left.endswith('%') != right.endswith('%'):
                continue
            qualifiers = (
                ('table', table.number), ('row', str(row_index)),
                ('first_period', year_labels[index]), ('first_value', left),
                ('second_period', year_labels[index + 1]), ('second_value', right),
            )
            yield RelationEdge(
                node('table_group', group), 'metric_comparison', node('metric', metric),
                'reported', table.page, None, qualifiers, row,
            )


def table_comparison_slide(graph: KnowledgeGraph, edge: RelationEdge) -> dict[str, str]:
    """Format one comparison for offline inspection without inferring a trend or cause."""
    if edge.relation != 'metric_comparison' or edge.table_row is None:
        raise ValueError('A table comparison is required')
    names = {node.id: node.name for node in graph.nodes}
    data = dict(edge.qualifiers)
    row_text = ' | '.join(' '.join((cell or '').split()) for cell in edge.table_row)
    return {
        'id': str(uuid4()),
        'layout': 'text',
        'title': f'{names[edge.target]} · стр. {edge.page}',
        'body': '\n'.join((
            names[edge.subject],
            f'{data["first_period"]} — {data["first_value"]}',
            f'{data["second_period"]} — {data["second_value"]}',
        )),
        'notes': (
            f'Источник: PDF, стр. {edge.page}, таблица {data["table"]}, '
            f'строка {data["row"]}.\nЯчейки источника: {row_text}'
        ),
    }


def build_knowledge_graph(
    pages: Iterable[tuple[int | None, str]], *, tables: Iterable[ReportTable] = (),
) -> KnowledgeGraph:
    """Extract literal relations from a narrow set of explicit Russian constructions."""
    sources = [(page, quote, recognize_entities(quote)) for page, quote in _sentences(pages)]
    aliases: dict[str, set[str]] = defaultdict(set)
    alias_display = {}
    for _, quote, entities in sources:
        org = _leading_organization(quote, entities)
        if org and (alias := _ALIAS.match(quote[len(org):])):
            aliases[_key(alias[1])].add(_key(org))
            alias_display.setdefault(_key(alias[1]), alias[1])

    nodes = {}
    edges = []

    def node(kind: str, name: str) -> int:
        key = kind, _key(name)
        if key not in nodes:
            spellings = tuple(alias_display[alias] for alias, owners in aliases.items()
                              if kind == 'organization' and owners == {key[1]})
            nodes[key] = EntityNode(len(nodes), kind, name, spellings)
        return nodes[key].id

    for page, quote, entities in sources:
        for kind, name in entities:
            if kind != 'person':  # The existing recognizer also returns capitalized non-names.
                node(kind, name)
        for program in _PROGRAM.finditer(quote):
            node('program', program[1])
        if len(quote) > 800:
            continue
        if presented := _PRESENTED_IN.fullmatch(quote):
            subject = node('topic', presented['topic'])
            for item in _REFERENCE_ITEM.finditer(presented['references']):
                kind = item[1].casefold()
                label = f'{_REFERENCE_LABELS[kind]} {item[2]}'
                is_table = kind == 'таблице'
                target = node('table_reference' if is_table else 'figure_reference', label)
                edges.append(RelationEdge(
                    subject, 'tabulated_in' if is_table else 'illustrated_by',
                    target, 'reported', page, quote,
                ))
            continue
        org = _leading_organization(quote, entities)
        if org:
            subject = node('organization', org)
            tail = quote[len(org):]
            if alias := _ALIAS.match(tail):
                tail = tail[alias.end():]
        elif name := _QUOTED_NAME.match(quote):
            owners = aliases.get(_key(name[0]), set())
            if len(owners) != 1:
                continue
            canonical = nodes.get(('organization', next(iter(owners))))
            if canonical is None:
                continue
            subject = canonical.id
            tail = quote[name.end():]
        else:
            continue
        if edge := _extract_relation(subject, tail, page, quote, node):
            edges.append(edge)
    for table in tables:
        edges.extend(_table_relations(table, node))
    return KnowledgeGraph(tuple(nodes.values()), tuple(edges))
