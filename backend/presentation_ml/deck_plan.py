"""Internal slide intents and their addresses in the source report."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.presentations.schemas import MetricComposition, text
from app.presentations.source_blocks import SourceDocument, TextBlock, source_text

from .source_reply import TableClaim, table_comparison_chart

ANCHOR_LIMIT = 32
TEXT_FRAGMENT_LIMIT = 1200
VisualKind = Literal['text', 'lead', 'blocks', 'steps', 'comparison', 'metric']
TEXT_STYLE_LINES = {'lead': (1, 5), 'blocks': (2, 3), 'steps': (2, 4)}


class ProposedIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    goal: text(160, 1, trim=True)
    takeaway: text(400, 1, trim=True)
    evidence_ids: Annotated[list[text(32, 1)], Field(max_length=6)]
    visual_intent: text(200, 1, trim=True)
    visual_kind: VisualKind = 'text'


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


def plan_schema(schema: dict, slide_count: int) -> None:
    """Place the plan before the slides in the single provider response."""
    intent = ProposedIntent.model_json_schema()
    fields = intent['properties']
    for field in ('goal', 'takeaway', 'visual_intent'):
        fields[field]['minLength'] = 1
    fields['visual_kind'].pop('default')
    intent['required'].append('visual_kind')
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
) -> tuple[str, list[dict], dict[str, EvidenceAddress]]:
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
    return '\n\n'.join(parts).rstrip(), anchors, references


def _requires_evidence(slide: dict) -> bool:
    layout = slide.get('layout')
    if layout == 'title':
        fields = ('subtitle', 'caption')
    elif layout in ('section', 'closing'):
        fields = ('subtitle',)
    else:
        return True
    return any(isinstance(slide.get(field), str) and slide[field].strip() for field in fields)


def read_intents(result: dict, references: dict[str, EvidenceAddress]) -> tuple[SlideIntent, ...]:
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
        if not ids and _requires_evidence(slide):
            raise ValueError('Missing plan evidence for content slide')
        if len(ids) != len(set(ids)) or any(identifier not in references for identifier in ids):
            raise ValueError('Unknown or duplicate plan evidence')
        intents.append(SlideIntent(
            proposal.goal, proposal.takeaway, tuple(references[i] for i in ids),
            proposal.visual_intent, proposal.visual_kind,
        ))
    return tuple(intents)


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


def apply_plan_compositions(document: dict, plan: DeckPlan, facts: list[dict]) -> None:
    """Place text according to the plan and build structured visuals from cited rows."""
    by_id = {fact['id']: fact for fact in facts
             if fact['relation'] == 'metric_comparison' and fact['status'] == 'reported'}
    for slide, planned in zip(document['slides'], plan.slides, strict=True):
        if slide['layout'] not in ('text', 'section') or 'sourceMaterial' in slide:
            continue
        kinds = {intent.visual_kind for intent in planned.intents}
        if len(kinds) != 1:
            continue
        (kind,) = kinds
        if kind in TEXT_STYLE_LINES:
            if slide['layout'] == 'text':
                minimum, maximum = TEXT_STYLE_LINES[kind]
                paragraphs = [line for line in slide['body'].splitlines() if line.strip()]
                if minimum <= len(paragraphs) <= maximum:
                    slide['textStyle'] = kind
            continue
        if kind == 'text':
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
