"""Internal slide intents and their addresses in the source report."""

import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from itertools import groupby, takewhile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.presentations.pdf_vector_charts import chart_caption_number
from app.presentations.schemas import MetricComposition, SourceTableMaterial, text
from app.presentations.source_blocks import MAX_SOURCE_TEXT, IllustrationBlock, SourceDocument, TableBlock, TextBlock, source_text

from .source_reply import TableClaim, table_comparison_chart

ANCHOR_LIMIT = 32
TEXT_FRAGMENT_LIMIT = 1200
LARGE_SOURCE_PROMPT_LIMIT = 60_000
LARGE_SOURCE_VERBATIM_LIMIT = 64
VisualKind = Literal['text', 'lead', 'blocks', 'steps', 'tree', 'comparison', 'metric', 'table', 'chart', 'figure', 'equation']
TEXT_STYLE_LINES = {'lead': (1, 5), 'blocks': (2, 3), 'steps': (2, 4)}
TREE_INDENT = re.compile(r'^(?: {2}|\t)(?=\S)')
SOURCE_BULLET = re.compile(r'^(?: {0,2}|\t)[-–—•▪*]\s+')
TREE_SHAPE = re.compile(r'l(?:lc{1,2}){2,3}')
OUTLINE_TOKENS = re.compile(
    r'[+\-−]?\d+(?:[.,:/–—-]\d+)*(?:[%‰])?|[^\W\d_]+(?:[-‑][^\W\d_]+)*|[^\s,.;:—–]'
)
PROCEDURE_HEADING = re.compile(
    r'^(?:Порядок|Последовательность|Этапы|Procedure|Steps)(?:\s|$)', re.I,
)
CONDITIONS_HEADING = re.compile(r'^(?:Условия|Условие|Conditions?|Requirements?)(?:\s|$)', re.I)
YEAR = re.compile(r'\b(\d{3,4})(?=\s+год(?:а|у|е|ом)?\b)', re.I)
SENTENCE_BREAK = re.compile(r'((?<=[.!?])\s+|\r?\n+)')
STANDALONE_NUMBER = re.compile(r'(?<!\w)\d+(?!\w)')
TABLE_REFERENCE = re.compile(
    r'\b(?:таблиц[а-яё]*|табл\.|table)\s*(?:№\s*)?(\d+(?:[.-]\d+)*)(?!\w)', re.I,
)
FIGURE_REFERENCE = re.compile(
    r'\b(?:рисун[а-яё]*|рис\.|figure)\s*(?:№\s*)?(\d+(?:\.\d+)+[а-яa-z]?)(?!\w)', re.I,
)
RASTER_FIGURE_NUMBER = re.compile(
    r'\b(?:figure|chart|рисун[а-яё]*|рис\.|диаграмм[а-яё]*|график[а-яё]*|схем[а-яё]*)'
    r'\s*(?:№\s*)?(\d+(?:\.\d+)*[а-яa-z]?)(?!\w)', re.I,
)
FIGURE_INDEX = re.compile(r'\b[A-Z]{2,8}\d{3,8}\b')
YEAR_LABEL = re.compile(r'\b(?:19|20)\d{2}\b')
CHART_DECIMAL = re.compile(r'(?<![\w.,+−-])(\d+[.,]\d{1,3})([ \t]*%)?(?!\w|[.,]\d)')
EQUATION_REFERENCE = re.compile(
    r'\b(?:формул[а-яё]*|уравнен[а-яё]*|equations?)\s*(?:№\s*)?\(?([1-9]\d{0,2})\)?(?![\w.\d])',
    re.I,
)


TableIndex = Annotated[int, Field(strict=True, ge=1)]


class TableSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)

    header_rows: Annotated[int, Field(ge=1, le=3)]
    label_column: TableIndex = 1
    rows: Annotated[tuple[TableIndex, ...], Field(strict=False, min_length=1, max_length=9)]
    columns: Annotated[tuple[TableIndex, ...], Field(strict=False, min_length=2, max_length=8)]


class ProposedIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    goal: text(160, 1, trim=True) = ''
    takeaway: text(400, 1, trim=True) = ''
    evidence_ids: Annotated[list[text(32, 1)], Field(max_length=10)]
    visual_intent: text(200, 1, trim=True) = ''
    visual_kind: VisualKind = 'text'
    table_selection: TableSelection | None = None
    verbatim_block_ids: Annotated[list[text(32, 1)], Field(max_length=2)] = Field(
        default_factory=list,
    )


@dataclass(frozen=True)
class EvidenceAddress:
    id: str
    block_id: str
    page: int | None = None
    row: int | None = None
    quote: str | None = None
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class SlideIntent:
    goal: str
    takeaway: str
    evidence: tuple[EvidenceAddress, ...]
    visual_intent: str
    visual_kind: VisualKind = 'text'
    verbatim_block_ids: tuple[str, ...] = ()
    table_selection: TableSelection | None = None


@dataclass(frozen=True)
class PlannedSlide:
    slide_id: str
    intents: tuple[SlideIntent, ...]


@dataclass(frozen=True)
class DeckPlan:
    slides: tuple[PlannedSlide, ...]


@dataclass(frozen=True)
class GeneratedDeck:
    document: dict
    plan: DeckPlan | None = None


def plan_schema(schema: dict, slide_count: int, verbatim: dict[str, str]) -> None:
    """Place the plan before the slides in the single provider response."""
    intent = ProposedIntent.model_json_schema()
    fields = intent['properties']
    fields['table_selection'] = intent.pop('$defs')['TableSelection']
    for field in ('goal', 'takeaway', 'visual_intent'):
        fields.pop(field)
    fields['visual_kind'].pop('default')
    intent['required'].append('visual_kind')
    if verbatim:
        fields['verbatim_block_ids']['items']['enum'] = list(verbatim)
    else:
        fields.pop('verbatim_block_ids')
    schema['properties'] = {
        'title': schema['properties']['title'],
        'plan': {
            'type': 'array', 'items': intent,
            'minItems': 1, 'maxItems': slide_count,
        },
        'slides': schema['properties']['slides'],
    }
    schema['required'].insert(1, 'plan')


def _text_fragments(value: str) -> Iterator[tuple[int, int]]:
    start = 0
    while start < len(value):
        end = min(start + TEXT_FRAGMENT_LIMIT, len(value))
        if end < len(value):
            lower_bound = start + TEXT_FRAGMENT_LIMIT // 2
            boundary = value.rfind('\n', lower_bound, end)
            if boundary < 0:
                boundary = value.rfind(' ', lower_bound, end)
            if boundary >= 0:
                end = boundary + 1
        yield start, end
        start = end


def _source_fragments(source: SourceDocument) -> Iterator[tuple[EvidenceAddress, str, str]]:
    for index, block in enumerate(source.blocks, 1):
        identifier = f'block-{index}'
        if isinstance(block, TextBlock):
            for part, (start, end) in enumerate(_text_fragments(block.text), 1):
                label = identifier if part == 1 else f'{identifier}-part-{part}'
                ref = EvidenceAddress(label, block.id, block.page, start=start, end=end)
                yield ref, block.kind, block.text[start:end]
        else:
            ref = EvidenceAddress(identifier, block.id, block.page)
            if isinstance(block, TableBlock) and _requires_table_selection(block):
                caption = block.caption or (f'Таблица {block.number}' if block.number else '')
                lines = [f'row {row}: ' + '\t'.join(cell or '' for cell in cells)
                         for row, cells in enumerate(block.rows, 1)]
                yield ref, block.kind, '\n'.join([caption, *lines]).lstrip()
            else:
                yield ref, block.kind, source_text(SourceDocument((block,)))


def plan_evidence(
    source: SourceDocument, facts: list[dict], *, limitations: Collection[str] = (),
) -> tuple[str, list[dict], dict[str, EvidenceAddress], dict[str, str]]:
    """Label the full source and sample excerpts separately from eligible references."""
    references = {
        fact['id']: EvidenceAddress(
            fact['id'], fact['source']['block_id'], fact['source'].get('page'),
            fact['source'].get('row'), fact.get('quote'),
        )
        for fact in facts
    }
    candidates = []
    parts = []
    for ref, kind, fragment in _source_fragments(source):
        if fragment.strip():
            references[ref.id] = ref
            parts.append(f'[{ref.id}]\n{fragment}')
            candidates.append((ref, kind, fragment))
    sizes = [len(part.encode('utf-16-le')) // 2 + 2 for part in parts]
    total_size = sum(sizes)
    included_ids = None
    if total_size > MAX_SOURCE_TEXT:
        # Keep structured material first, then sample prose across the document.
        visual = [i for i, (_, kind, _) in enumerate(candidates) if kind != 'text']
        prose = [i for i, (_, kind, _) in enumerate(candidates) if kind == 'text']
        stride = (total_size + LARGE_SOURCE_PROMPT_LIMIT - 1) // LARGE_SOURCE_PROMPT_LIMIT
        selected = set()
        remaining = LARGE_SOURCE_PROMPT_LIMIT
        for i in (*visual, *prose[::stride], *prose):
            if i not in selected and sizes[i] <= remaining:
                selected.add(i)
                remaining -= sizes[i]
        parts = [parts[i] for i in sorted(selected)]
        included_ids = {candidates[i][0].id for i in selected}
    if len(candidates) > ANCHOR_LIMIT:
        last = len(candidates) - 1
        candidates = [candidates[i * last // (ANCHOR_LIMIT - 1)] for i in range(ANCHOR_LIMIT)]
    anchors = []
    for ref, kind, fragment in candidates:
        address = {'block_id': ref.block_id}
        if ref.page is not None:
            address['page'] = ref.page
        if ref.start is not None:
            address.update(start=ref.start, end=ref.end)
        anchors.append({
            'id': ref.id, 'kind': kind, 'source': address,
            'excerpt': ' '.join(fragment.split())[:280],
        })
    verbatim = {}
    for index, block in enumerate(source.blocks, 1):
        if isinstance(block, TextBlock):
            paragraph = ' '.join(block.text.split())
            size = len(paragraph.encode('utf-16-le')) // 2
            if 15 <= size <= 360 and (paragraph in limitations
                                      or (size >= 30 and STANDALONE_NUMBER.search(paragraph))):
                verbatim[f'block-{index}'] = paragraph
    if included_ids is not None:
        eligible = [(key, text) for key, text in verbatim.items() if key in included_ids]
        priority = [(key, text) for key, text in eligible if text in limitations]
        routine = [(key, text) for key, text in eligible if text not in limitations]
        slots = max(0, LARGE_SOURCE_VERBATIM_LIMIT - len(priority))
        if 0 < slots < len(routine):
            routine = [routine[i * len(routine) // slots] for i in range(slots)]
        verbatim = dict((priority + routine[:slots])[:LARGE_SOURCE_VERBATIM_LIMIT])
    return '\n\n'.join(parts).rstrip(), anchors, references, verbatim


def _requires_evidence(slide: dict) -> bool:
    layout = slide.get('layout')
    if layout == 'title':
        fields = ('subtitle', 'caption')
    elif layout in ('section', 'closing'):
        fields = ('subtitle',)
    else:
        return True
    return any(isinstance(slide.get(field), str) and slide[field].strip() for field in fields)


def read_intents(
    result: dict, references: dict[str, EvidenceAddress], verbatim: dict[str, str],
    *, allow_partial: bool = False,
) -> tuple[SlideIntent, ...]:
    if not isinstance(result, dict):
        raise ValueError('Invalid generation plan')
    slides, proposals = result.get('slides'), result.get('plan')
    if (not isinstance(slides, list) or not isinstance(proposals, list)
            or not 1 <= len(slides) <= 60 or len(slides) != len(proposals)):
        raise ValueError('Generation plan must match draft slides in order')
    intents = []
    for slide, raw in zip(slides, proposals, strict=True):
        if not isinstance(slide, dict):
            raise ValueError('Invalid planned slide')
        try:
            proposal = ProposedIntent.model_validate(raw)
            ids = proposal.evidence_ids
            chosen = list(dict.fromkeys(proposal.verbatim_block_ids))
            if not ids and not chosen and _requires_evidence(slide):
                raise ValueError('Missing plan evidence for content slide')
            if len(ids) != len(set(ids)) or any(identifier not in references for identifier in ids):
                raise ValueError('Unknown or duplicate plan evidence')
            if not set(chosen) <= verbatim.keys():
                raise ValueError('Unknown verbatim block reference')
            evidence = tuple(references[i] for i in dict.fromkeys(ids + chosen))
            intents.append(SlideIntent(
                proposal.goal, proposal.takeaway, evidence,
                proposal.visual_intent, proposal.visual_kind, tuple(chosen), proposal.table_selection,
            ))
        except ValueError:
            if not allow_partial:
                raise
            intents.append(SlideIntent('', '', (), ''))
    return tuple(intents)


def _restore_truncated_years(
    draft: str, evidence: tuple[EvidenceAddress, ...], source_texts: dict[str, str],
) -> str:
    """Restore a missing digit only when the rest of a cited sentence matches."""
    if not any(len(match[1]) == 3 for match in YEAR.finditer(draft)):
        return draft
    source_years: dict[str, set[str]] = {}
    for ref in evidence:
        if ref.start is None or ref.block_id not in source_texts:
            continue
        for sentence in SENTENCE_BREAK.split(source_texts[ref.block_id][ref.start:ref.end]):
            hits = list(YEAR.finditer(sentence))
            if len(hits) == 1:
                pattern = ' '.join(YEAR.sub('#', sentence).split())
                source_years.setdefault(pattern, set()).add(hits[0][1])
    parts = SENTENCE_BREAK.split(draft)
    for index in range(0, len(parts), 2):
        sentence = parts[index]
        hits = list(YEAR.finditer(sentence))
        if len(hits) != 1 or len(hits[0][1]) != 3:
            continue
        years = source_years.get(' '.join(YEAR.sub('#', sentence).split()), set())
        if len(years) != 1:
            continue
        (year,) = years
        hit = hits[0]
        if len(year) == 4 and any(year[:i] + year[i + 1:] == hit[1] for i in range(4)):
            parts[index] = sentence[:hit.start()] + year + sentence[hit.end():]
    return ''.join(parts)


def render_planned_text(
    result: dict, intents: tuple[SlideIntent, ...], blocks: dict[str, str], source: SourceDocument,
) -> dict:
    """Resolve cited whole paragraphs before slide sizing and closing synthesis."""
    source_texts = {block.id: block.text for block in source.blocks if isinstance(block, TextBlock)}
    slides = []
    for slide, intent in zip(result['slides'], intents, strict=True):
        field = {'text': 'body', 'closing': 'subtitle'}.get(slide.get('layout'))
        if field is None and not intent.verbatim_block_ids:
            slides.append(slide)
            continue
        if field is None:
            raise ValueError('Invalid layout for verbatim block reference')
        draft = slide.get(field, '')
        if not isinstance(draft, str):
            if intent.verbatim_block_ids:
                raise ValueError('Invalid text for verbatim block reference')
            slides.append(slide)
            continue
        restored = _restore_truncated_years(draft, intent.evidence, source_texts)
        if not intent.verbatim_block_ids:
            slides.append(dict(slide, **{field: restored}) if restored != draft else slide)
            continue
        selected = set(intent.verbatim_block_ids)
        excerpts = list(dict.fromkeys(blocks[i] for i in intent.verbatim_block_ids))
        if all(ref.id in selected for ref in intent.evidence):
            # The selected paragraphs are the entire evidence for this slide.
            # Render them directly instead of also publishing their paraphrase.
            slides.append(dict(slide, **{field: '\n\n'.join(excerpts)}))
            continue
        existing = restored.strip()
        paragraphs = {' '.join(paragraph.split()) for paragraph in existing.splitlines()}
        additions = [excerpt for excerpt in excerpts if excerpt not in paragraphs]
        slides.append(dict(slide, **{field: '\n\n'.join(filter(None, (existing, *additions)))}))
    return dict(result, slides=slides)


type SlideIntents = dict[str, tuple[SlideIntent, ...]]


def merge_intents(plans: SlideIntents, merged: dict, parts: list[dict]) -> None:
    plans[merged['id']] = tuple(
        intent for part in parts for intent in plans[part['id']]
    )


def complete_plan(
    document: dict, plans: SlideIntents, recap_intents: tuple[SlideIntent, ...] | None,
    *, allow_partial: bool = False,
) -> DeckPlan:
    """Bind synthesized cover and recap to the same final slide IDs as model-supplied intents."""
    slides = document['slides']
    cover, closing = slides[0], slides[-1]
    if cover['id'] not in plans:
        plans[cover['id']] = (
            SlideIntent(
                'Представить тему доклада', cover['title'] or 'Тема доклада', (),
                'Титульный слайд',
            ),
        )
    if recap_intents is not None:
        evidence = tuple(dict.fromkeys(ref for intent in recap_intents for ref in intent.evidence))
        plans[closing['id']] = (
            SlideIntent('Подвести итог', closing['subtitle'], evidence, 'Краткое резюме'),
        )
    planned = []
    for slide in slides:
        intents = plans[slide['id']]
        if not allow_partial and _requires_evidence(slide) and not any(intent.evidence for intent in intents):
            raise ValueError('Missing plan evidence for final slide')
        planned.append(PlannedSlide(slide['id'], intents))
    return DeckPlan(tuple(planned))


def _tree_rows(body: str, *, source: bool = False) -> tuple[tuple[str, str], ...]:
    rows = []
    for line in body.splitlines():
        if not line.strip():
            continue
        bullet = SOURCE_BULLET.match(line) if source else None
        if bullet or TREE_INDENT.match(line):
            label = line[bullet.end():] if bullet else line
            rows.append(('child', ' '.join(label.split())))
        elif line == line.lstrip():
            label = ' '.join(line.rstrip().removesuffix(':').split())
            rows.append(('label', label))
        else:
            rows.append(('unknown', line))
    return tuple(rows)


@dataclass(frozen=True)
class SourceTree:
    rows: tuple[tuple[str, str], ...]
    label_ids: frozenset[str]
    node_ids: frozenset[str]

    @property
    def body(self) -> str:
        return '\n'.join('  ' + value if kind == 'child' else value for kind, value in self.rows)


def _source_trees(source: SourceDocument) -> Iterator[SourceTree]:
    for has_text, run in groupby(_source_fragments(source), lambda item: item[1] == 'text'):
        if not has_text:
            continue
        rows = [
            (kind, label, ref.id)
            for ref, _, fragment in run for kind, label in _tree_rows(fragment, source=True)
        ]
        shape = ''.join(kind[0] for kind, _, _ in rows)
        for root in range(len(rows) - 4):
            for end in range(root + 5, min(root + 10, len(rows)) + 1):
                # Match the root, then two or three labelled branches with one or two children each.
                if not TREE_SHAPE.fullmatch(shape, root, end) or shape[end:end + 1] == 'c':
                    continue
                window = rows[root:end]
                yield SourceTree(
                    tuple((kind, label) for kind, label, _ in window),
                    frozenset(ref for kind, _, ref in window if kind == 'label'),
                    frozenset(ref for _, _, ref in window),
                )


def _verified_tree_body(
    title: str, body: str, intent: SlideIntent, trees: tuple[SourceTree, ...],
) -> str | None:
    cited = {ref.id for ref in intent.evidence}
    if intent.visual_kind == 'tree':
        wanted = _tree_rows(body)
        if any(tree.node_ids <= cited and tree.rows == wanted for tree in trees):
            return body
    # GigaChat may flatten a faithful outline into prose. Restore only an unambiguous,
    # fully matching outline anchored by citations for its root and every branch.
    tokens = OUTLINE_TOKENS.findall(body.casefold())
    title_tokens = OUTLINE_TOKENS.findall(title.casefold())
    matches = set()
    for tree in trees:
        if not tree.label_ids <= cited:
            continue
        outline_tokens = OUTLINE_TOKENS.findall(tree.body.casefold())
        root_tokens = OUTLINE_TOKENS.findall(tree.rows[0][1].casefold())
        if (outline_tokens == tokens or
                (title_tokens == root_tokens and outline_tokens == title_tokens + tokens)):
            matches.add(tree.body)
    return next(iter(matches)) if len(matches) == 1 else None


def _verified_procedure_body(
    title: str, body: str, intent: SlideIntent, source: SourceDocument,
) -> str | None:
    if not PROCEDURE_HEADING.match(title):
        return None
    cited = {ref.id for ref in intent.evidence}
    rows = [
        (ref.id, line.strip())
        for ref, kind, fragment in _source_fragments(source)
        for line in (fragment.splitlines() if kind == 'text' else [''])
        if line.strip() or kind != 'text'
    ]
    matches = set()
    for index, (ref, heading) in enumerate(rows):
        if ref not in cited or heading.casefold() != title.casefold():
            continue
        following = rows[index + 1:index + 10]
        actions = list(takewhile(
            lambda row: row[1].endswith(('.', '!', '?')) and not SOURCE_BULLET.match(row[1]),
            following,
        ))
        if not 2 <= len(actions) <= 4 or any(ref not in cited for ref, _ in actions):
            continue
        steps = [action for _, action in actions]
        prefix = ' '.join(' '.join(steps).split())
        draft = ' '.join(body.split())
        if draft == prefix:
            matches.add('\n'.join(steps))
        elif draft.startswith(prefix + ' ') and len(following) > len(actions) + 1:
            (_, label), *details = following[len(actions):]
            if not CONDITIONS_HEADING.match(label):
                continue
            conditions = [
                line for _, line in takewhile(
                    lambda row: row[0] in cited and row[1].endswith(('.', '!', '?')), details[:2],
                )
            ]
            if conditions:
                # The model may combine the two source sentences with a semicolon.
                tail = draft[len(prefix):].strip().casefold()
                tail = re.sub(r';\s+', '. ', tail)
                for length in range(1, len(conditions) + 1):
                    detail = ' '.join(' '.join(conditions[:length]).split())
                    if tail == re.sub(r';\s+', '. ', detail.casefold()):
                        matches.add('\n'.join(steps) + '\n\n' + label + '\n' + detail)
    return next(iter(matches)) if len(matches) == 1 else None


def _requires_table_selection(table: TableBlock) -> bool:
    return bool(table.rows) and (len(table.rows) > 10 or len(table.rows[0]) > 8)


def _table_material(table: TableBlock, selection: TableSelection | None = None) -> SourceTableMaterial | None:
    rows = table.rows
    if selection:
        columns = sorted(set(selection.columns))
        selected_rows = sorted(set(selection.rows))
        if (not rows or len(selected_rows) != len(selection.rows) or len(columns) != len(selection.columns)
                or selected_rows[0] <= selection.header_rows or selected_rows[-1] > len(rows)
                or selection.header_rows + len(selected_rows) > 10
                or selection.label_column not in columns or columns[-1] > len(rows[0])
                or any(len(row) != len(rows[0]) for row in rows)):
            return None
        indexes = [*range(selection.header_rows), *(number - 1 for number in selected_rows)]
        rows = tuple(tuple(rows[index][column - 1] for column in columns) for index in indexes)
        header = rows[:selection.header_rows]
        label = columns.index(selection.label_column)
        if (any(not any(cell and cell.strip() for cell in col) for col in zip(*header, strict=True))
                or any(not row[label] or not row[label].strip() for row in rows[selection.header_rows:])):
            return None
    # A missing cell can represent a span or incomplete extraction.
    if len(rows) > 10 or any(cell is None for row in rows for cell in row):
        return None
    try:
        return SourceTableMaterial(kind='table', page=table.page, rows=[list(row) for row in rows])
    except ValidationError:
        return None


def _matches_two_column_table(rows, text):
    if len(rows) < 3 or any(len(row) != 2 for row in rows):
        return False
    for label, value in rows[1:]:
        if not label or not value or not re.search(r'\d', value):
            return False
        pair = rf'(?<!\w){re.escape(label)}\s*(?:[|:–—-]\s*)?{re.escape(value)}(?![\w.,]\d|\w)'
        if not re.search(pair, text, re.IGNORECASE):
            return False
    return True


def apply_referenced_tables(document: dict, source: SourceDocument) -> None:
    """Keep unambiguous source tables referenced in visible text."""
    by_number = {}
    for block in source.blocks:
        if isinstance(block, TableBlock) and block.number:
            by_number[block.number] = block if block.number not in by_number else None
    tables = {
        number: material.model_dump(exclude_none=True)
        for number, table in by_number.items()
        if table is not None and (material := _table_material(table)) is not None
    }
    unnumbered = [
        material.model_dump(exclude_none=True)
        for block in source.blocks
        if isinstance(block, TableBlock) and not block.number and not block.caption
        and (material := _table_material(block)) is not None
    ]
    used = [slide['sourceMaterial'] for slide in document['slides'] if 'sourceMaterial' in slide]
    for slide in document['slides']:
        if slide['layout'] != 'text' or 'sourceMaterial' in slide or 'composition' in slide:
            continue
        references = set(TABLE_REFERENCE.findall(slide['title'] + '\n' + slide['body']))
        if len(references) == 1:
            (number,) = references
            material = tables.get(number)
        elif not references:
            matches = [table for table in unnumbered
                       if _matches_two_column_table(table['rows'], slide['body'])]
            material = matches[0] if len(matches) == 1 else None
        else:
            continue
        if material is not None and material not in used:
            slide['sourceMaterial'] = material
            used.append(material)


def source_visual_catalog(source: SourceDocument) -> list[dict]:
    """Expose addressable visuals separately from sampled source prose."""
    visuals = []
    for index, block in enumerate(source.blocks, 1):
        if isinstance(block, TableBlock) and chart_caption_number(block.caption):
            if _chart_comparison(block, '') is None:
                continue
            kind = 'chart'
        elif isinstance(block, TableBlock) and (_table_material(block) is not None
                                               or _requires_table_selection(block)):
            kind = 'table'
        elif isinstance(block, IllustrationBlock) and block.png and block.caption:
            kind = 'equation' if EQUATION_REFERENCE.fullmatch(block.caption) else 'figure'
        else:
            continue
        entry = {'id': f'block-{index}', 'kind': kind}
        if kind == 'table' and _requires_table_selection(block):
            entry['dimensions'] = {'rows': len(block.rows), 'columns': len(block.rows[0])}
        if block.page is not None:
            entry['page'] = block.page
        if block.caption:
            entry['caption'] = block.caption[:220]
        elif isinstance(block, TableBlock) and block.number:
            entry['caption'] = f'Таблица {block.number}'
        visuals.append(entry)
        if len(visuals) == ANCHOR_LIMIT:
            break
    return visuals


def _chart_comparison(table: TableBlock, content: str) -> dict | None:
    if len(table.rows) < 3:
        return None
    header, years, *rows = table.rows
    if len(header) < 3 or not header[1] or len(years) != len(header):
        return None
    periods = years[1:]
    if any(not year or not YEAR_LABEL.fullmatch(year) for year in periods):
        return None
    if tuple(sorted(set(periods))) != periods:
        return None
    mentioned = set(YEAR_LABEL.findall(content))
    selected = [index for index, label in enumerate(years) if label in mentioned]
    first, last = selected if len(selected) == 2 else (1, len(years) - 1)
    if any(len(row) != len(years) or not (row[0] and row[first] and row[last]) for row in rows):
        return None
    return table_comparison_chart([
        TableClaim(fact_id=table.id, group=row[0], metric=header[1],
                   first_period=years[first], first_value=row[first],
                   second_period=years[last], second_value=row[last])
        for row in rows
    ])


def _matches_chart_numbers(chart: dict, periods: set[str], decimals: set[tuple[float, bool]], content: str) -> bool:
    first, last = chart['series']
    if not {first['label'], last['label']} <= periods:
        return False
    percent = chart.get('unit') == '%'
    values = {value for value, is_percent in decimals if is_percent == percent}
    matched = values.intersection(first['values'] + last['values'])
    if len(matched) >= 3:
        return True
    if len(matched) != 2:
        return False
    normalized = ' '.join(content.casefold().split())
    return any(
        {a, b} == matched and re.search(r'(?<!\w)' + re.escape(' '.join(category.casefold().split())) + r'(?!\w)',
                                       normalized)
        for category, a, b in zip(chart['categories'], first['values'], last['values'], strict=True)
    )


def apply_referenced_charts(
    document: dict, source: SourceDocument, already_rendered: Collection[str] = (),
) -> None:
    """Build editable charts from an explicit citation or a unique match of labels and values."""
    by_number = {}
    for block in source.blocks:
        if isinstance(block, TableBlock) and (number := chart_caption_number(block.caption)):
            by_number[number] = block if number not in by_number else None
    used = set(already_rendered)
    eligible = [slide for slide in document['slides']
                if slide['layout'] == 'text' and 'sourceMaterial' not in slide and 'composition' not in slide]
    unreferenced = []
    for slide in eligible:
        content = '\n'.join((slide['title'], slide['body']))
        references = {match.casefold() for match in FIGURE_REFERENCE.findall(
            content + '\n' + slide.get('notes', ''),
        )}
        if not references:
            unreferenced.append((slide, content))
        elif len(references) == 1:
            (number,) = references
            table = by_number.get(number)
            if table is not None and table.id not in used and (chart := _chart_comparison(table, content)):
                slide['composition'] = chart
                used.add(table.id)
    for slide, content in unreferenced:
        periods = set(YEAR_LABEL.findall(content))
        decimals = {(float(number.replace(',', '.')), bool(percent))
                    for number, percent in CHART_DECIMAL.findall(content)}
        if len(periods) < 2 or len(decimals) < 2:
            continue
        matches = [
            (table.id, chart) for table in by_number.values()
            if table is not None and (chart := _chart_comparison(table, content))
            and _matches_chart_numbers(chart, periods, decimals, content)
        ]
        if len(matches) == 1:
            (identifier, chart), = matches
            if identifier not in used:
                slide['composition'] = chart
                used.add(identifier)


def _planned_illustrations(plan: DeckPlan | None, kind: VisualKind, available: Collection[str]) -> dict[str, set[str]]:
    matches = {}
    for item in plan.slides if plan else ():
        selected = [intent for intent in item.intents if intent.visual_kind == kind]
        if selected:
            matches[item.slide_id] = {ref.block_id for intent in selected for ref in intent.evidence
                                      if ref.block_id in available}
    return matches


_EQUATION_RESULT = re.compile(r'[=≈]\s*(\d+[.,]\d+)\s*\(([1-9]\d{0,2})\)')
_EQUATION_VARIABLE = re.compile(r'\b[A-Z][0-9]+\b')


def _equation_result_keys(source, equations):
    keys = []
    for block in source.blocks:
        if not isinstance(block, TextBlock):
            continue
        for match in _EQUATION_RESULT.finditer(block.text):
            value, number = match.groups()
            equation = equations.get(number)
            if equation and equation.page == block.page:
                symbols = set(_EQUATION_VARIABLE.findall(block.text[max(0, match.start() - 100):match.start()]))
                if symbols:
                    keys.append((equation.id, value.replace(',', '.'), symbols))
    return keys


def apply_referenced_equations(document: dict, source: SourceDocument, plan: DeckPlan | None = None) -> None:
    """Attach the original equation, using a plan address or an unambiguous number."""
    equations = {}
    by_id = {}
    for block in source.blocks:
        if not isinstance(block, IllustrationBlock) or not (tag := EQUATION_REFERENCE.fullmatch(block.caption)):
            continue
        number = tag[1]
        equations[number] = block if number not in equations else None
        if block.png and block.page is not None:
            by_id[block.id] = block
    planned = _planned_illustrations(plan, 'equation', by_id)
    result_keys = _equation_result_keys(source, equations) if by_id else ()
    used = set()
    for slide in document['slides']:
        if slide['layout'] != 'text' or 'sourceMaterial' in slide or 'composition' in slide:
            continue
        if (matches := planned.get(slide['id'])) is not None:
            if len(matches) != 1:
                continue
            (identifier,) = matches
            equation = by_id[identifier]
        else:
            content = '\n'.join((slide['title'], slide['body'], slide.get('notes', '')))
            references = set(EQUATION_REFERENCE.findall(content))
            if len(references) == 1:
                (number,) = references
                equation = equations.get(number)
            elif not references:
                values = {value.replace(',', '.') for value, _ in CHART_DECIMAL.findall(slide['body'])}
                symbols = set(_EQUATION_VARIABLE.findall(slide['body']))
                matches = {identifier for identifier, result, variables in result_keys
                           if identifier in by_id and result in values and variables & symbols}
                equation = by_id[next(iter(matches))] if len(matches) == 1 else None
            else:
                continue
        if equation and equation.id in by_id and equation.id not in used:
            slide['sourceMaterial'] = {'kind': 'image', 'page': equation.page, 'png': equation.png}
            used.add(equation.id)


def _figure_heading(value: str) -> str:
    return ' '.join(word for word in re.findall(r'[^\W_]+', value.casefold())
                    if word not in {'people', 'we', 'they'})


FIGURE_RATIO = re.compile(r'(?<![\w.,+−–-])(\d{1,3}(?:[.,]\d+)?)[ \t\u00a0\u202f]*%')


def _figure_ratios(value: str) -> set[str]:
    return {number.replace(',', '.') for number in FIGURE_RATIO.findall(value)}


def apply_referenced_figures(document: dict, source: SourceDocument, plan: DeckPlan | None) -> None:
    """Keep the original raster figure when its address or caption identifies one crop."""
    figures = {
        block.id: block for block in source.blocks
        if isinstance(block, IllustrationBlock) and block.png and block.page is not None and block.caption
        and not EQUATION_REFERENCE.fullmatch(block.caption)
    }
    if not figures:
        return
    identifiers = {
        identifier: (
            set(FIGURE_INDEX.findall(block.caption)),
            {number.casefold() for number in RASTER_FIGURE_NUMBER.findall(block.caption)},
            _figure_heading(block.caption.split('[', 1)[0]),
        )
        for identifier, block in figures.items()
    }
    nearby_text = {
        block.id: [' '.join(neighbor.text.casefold().split())
                   for neighbor in source.blocks[max(0, index - 1):index + 2]
                   if isinstance(neighbor, TextBlock) and neighbor.page == block.page]
        for index, block in enumerate(source.blocks)
        if block.id in figures
    }
    nearby_ratios = {
        identifier: set().union(*(_figure_ratios(text) for text in neighbors))
        for identifier, neighbors in nearby_text.items()
    }
    planned = _planned_illustrations(plan, 'figure', figures)
    used = set()
    for slide in document['slides']:
        if slide['layout'] != 'text' or 'sourceMaterial' in slide or 'composition' in slide:
            continue
        matches = planned.get(slide['id'])
        if matches is None:
            content = '\n'.join((slide['title'], slide['body'], slide.get('notes', '')))
            numbers = {number.casefold() for number in RASTER_FIGURE_NUMBER.findall(content)}
            indexes = set(FIGURE_INDEX.findall(content))
            title = _figure_heading(slide['title'])
            matches = {identifier for identifier, (codes, tags, _) in identifiers.items()
                       if codes & indexes or tags & numbers}
            if len(matches) != 1:
                headings = {identifier for identifier, (_, _, heading) in identifiers.items()
                            if len(heading) >= 7 and (title == heading or title.startswith(heading + ' '))}
                if headings:
                    matches = matches & headings if matches else headings
                elif not matches:
                    # A topic word alone is weak evidence. Require the slide to
                    # share two distinct reported ratios with neighboring prose.
                    words = {word for word in title.split() if len(word) >= 5}
                    ratios = _figure_ratios(slide['body'])
                    matches = {identifier for identifier, (_, _, heading) in identifiers.items()
                               if words.intersection(heading.split())
                               and len(ratios & nearby_ratios[identifier]) >= 2}
                    if not matches and len(ratios) >= 2:
                        body = ' '.join(slide['body'].casefold().split())
                        matches = {identifier for identifier, neighbors in nearby_text.items()
                                   if len(body) >= 100 and body in neighbors}
        if len(matches) != 1:
            continue
        (identifier,) = matches
        if identifier not in used:
            block = figures[identifier]
            slide['sourceMaterial'] = {'kind': 'image', 'page': block.page, 'png': block.png}
            used.add(identifier)


def apply_plan_compositions(
    document: dict, plan: DeckPlan, facts: list[dict], source: SourceDocument,
) -> set[str]:
    """Place text according to the plan and build structured visuals from cited rows."""
    by_id = {fact['id']: fact for fact in facts
             if fact['relation'] == 'metric_comparison' and fact['status'] == 'reported'}
    tables = {block.id: block for block in source.blocks if isinstance(block, TableBlock)}
    trees = tuple(_source_trees(source))
    rendered_charts = set()
    for slide, planned in zip(document['slides'], plan.slides, strict=True):
        if slide['layout'] not in ('text', 'section') or 'sourceMaterial' in slide:
            continue
        kinds = {intent.visual_kind for intent in planned.intents}
        visual_kinds = kinds - {'text'}
        if visual_kinds in ({'table'}, {'chart'}):
            kinds = visual_kinds
        if len(kinds) != 1:
            continue
        (kind,) = kinds
        if kind in ('table', 'chart'):
            visual_intents = [intent for intent in planned.intents if intent.visual_kind == kind]
            cited_tables = {ref.block_id for intent in visual_intents for ref in intent.evidence
                            if ref.block_id in tables}
            if slide['layout'] != 'text' or len(cited_tables) != 1 or 'composition' in slide:
                continue
            (identifier,) = cited_tables
            table = tables[identifier]
            if kind == 'table':
                selections = {intent.table_selection for intent in visual_intents}
                if len(selections) == 1 and (material := _table_material(table, next(iter(selections)))) is not None:
                    slide['sourceMaterial'] = material.model_dump(exclude_none=True)
            elif kind == 'chart' and identifier not in rendered_charts and chart_caption_number(table.caption):
                if chart := _chart_comparison(table, slide['title'] + '\n' + slide['body']):
                    slide['composition'] = chart
                    rendered_charts.add(identifier)
            continue
        if kind in ('text', 'steps') and slide['layout'] == 'text' and len(planned.intents) == 1:
            body = _verified_procedure_body(
                slide['title'], slide['body'], planned.intents[0], source,
            )
            if body is not None and len(body.encode('utf-16-le')) <= 8_000:
                slide.update(textStyle='steps', body=body)
                continue
        if kind in ('text', 'tree'):
            if trees and slide['layout'] == 'text' and len(planned.intents) == 1:
                body = _verified_tree_body(slide['title'], slide['body'], planned.intents[0], trees)
                if body is not None and len(body.encode('utf-16-le')) <= 8_000:
                    slide.update(textStyle='tree', body=body)
            continue
        if kind in TEXT_STYLE_LINES:
            if slide['layout'] == 'text':
                minimum, maximum = TEXT_STYLE_LINES[kind]
                paragraphs = [line for line in slide['body'].splitlines() if line.strip()]
                if minimum <= len(paragraphs) <= maximum:
                    slide['textStyle'] = kind
            continue
        ids = {ref.id for intent in planned.intents for ref in intent.evidence}
        cited = [by_id[identifier] for identifier in ids if identifier in by_id]
        if not cited or len({fact['source']['block_id'] for fact in cited}) != 1:
            continue
        cited.sort(key=lambda fact: fact['source']['row'])
        claims = [TableClaim(
            fact_id=fact['id'], group=fact['subject'], metric=fact['target'], **fact['qualifiers'],
        ) for fact in cited]
        composition = None
        if kind == 'comparison' and len(claims) >= 2:
            composition = table_comparison_chart(claims)
        elif kind == 'metric' and len(claims) == 1:
            claim = claims[0]
            values = [
                {'label': f'{claim.metric} · {claim.group} · {period}', 'value': value}
                for period, value in ((claim.first_period, claim.first_value),
                                      (claim.second_period, claim.second_value))
            ]
            if all(len(item['label'].encode('utf-16-le')) <= 160
                   and len(item['value'].encode('utf-16-le')) <= 40 for item in values):
                composition = MetricComposition(kind='metric', values=values).model_dump()
        if composition:
            if slide['layout'] == 'section':
                slide['layout'] = 'text'
                slide['body'] = slide.pop('subtitle', '')
            slide['composition'] = composition
    return rendered_charts
