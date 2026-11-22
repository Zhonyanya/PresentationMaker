"""Internal slide intents and their addresses in the source report."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import groupby, takewhile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.presentations.schemas import MetricComposition, text
from app.presentations.source_blocks import SourceDocument, TextBlock, source_text

from .source_reply import TableClaim, table_comparison_chart

ANCHOR_LIMIT = 32
TEXT_FRAGMENT_LIMIT = 1200
VisualKind = Literal['text', 'lead', 'blocks', 'steps', 'tree', 'comparison', 'metric']
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


class ProposedIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    goal: text(160, 1, trim=True)
    takeaway: text(400, 1, trim=True)
    evidence_ids: Annotated[list[text(32, 1)], Field(max_length=10)]
    visual_intent: text(200, 1, trim=True)
    visual_kind: VisualKind = 'text'
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
    for field in ('goal', 'takeaway', 'visual_intent'):
        fields[field]['minLength'] = 1
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
            yield ref, block.kind, source_text(SourceDocument((block,)))


def plan_evidence(
    source: SourceDocument, facts: list[dict],
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
            if 30 <= len(paragraph.encode('utf-16-le')) // 2 <= 360 and re.search(r'\d', paragraph):
                verbatim[f'block-{index}'] = paragraph
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
        proposal = ProposedIntent.model_validate(raw)
        ids = proposal.evidence_ids
        chosen = proposal.verbatim_block_ids
        if not ids and not chosen and _requires_evidence(slide):
            raise ValueError('Missing plan evidence for content slide')
        if len(ids) != len(set(ids)) or any(identifier not in references for identifier in ids):
            raise ValueError('Unknown or duplicate plan evidence')
        if len(chosen) != len(set(chosen)) or not set(chosen) <= verbatim.keys():
            raise ValueError('Unknown or repeated verbatim block reference')
        evidence = tuple(references[i] for i in dict.fromkeys(ids + chosen))
        intents.append(SlideIntent(
            proposal.goal, proposal.takeaway, evidence,
            proposal.visual_intent, proposal.visual_kind, tuple(chosen),
        ))
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
        if _requires_evidence(slide) and not any(intent.evidence for intent in intents):
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


def apply_plan_compositions(
    document: dict, plan: DeckPlan, facts: list[dict], source: SourceDocument,
) -> None:
    """Place text according to the plan and build structured visuals from cited rows."""
    by_id = {fact['id']: fact for fact in facts
             if fact['relation'] == 'metric_comparison' and fact['status'] == 'reported'}
    trees = tuple(_source_trees(source))
    for slide, planned in zip(document['slides'], plan.slides, strict=True):
        if slide['layout'] not in ('text', 'section') or 'sourceMaterial' in slide:
            continue
        kinds = {intent.visual_kind for intent in planned.intents}
        if len(kinds) != 1:
            continue
        (kind,) = kinds
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
