"""Contract-compatible presentation generation; import performs no provider work."""

import copy
from datetime import UTC, datetime
from functools import lru_cache

from app.presentations.schemas import Document, normalize_document, validate_revision

from .capabilities import reject_explicit_structure_change
from .grounding import attach_source_quotes, select_source_passages
from .prompts import build_generation_prompt, build_revision_prompt, get_prompt_version
from .transport import request_document

PRESERVES_SLIDE_IDS = True

def remaining_seconds(deadline):
    end = datetime.fromisoformat(deadline)
    if end.tzinfo is None:
        raise ValueError("Deadline requires timezone")
    remaining = (end - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise TimeoutError("ML deadline expired")
    if remaining <= 10:
        raise RuntimeError("Insufficient ML time budget before publication reserve")
    return remaining - 10


def _schema(revision=False, slide_count=None, grounded=False, slide_ids=None, frozen_title=None):
    schema = Document.model_json_schema()
    definitions = schema.get('$defs', {})
    definitions.get('TextSlide', {}).get('properties', {}).pop('sourceMaterial', None)
    definitions.pop('SourceTableMaterial', None)
    definitions.pop('SourceImageMaterial', None)
    # Optional fields must be omitted, never returned as null.
    def clean(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if "anyOf" in node:
                choices = [v for v in node["anyOf"] if v.get("type") != "null"]
                if len(choices) == 1:
                    node.pop("anyOf")
                    node.update(choices[0])
                else:
                    node["anyOf"] = choices
            for child in list(node.values()):
                clean(child)
        elif isinstance(node, list):
            for child in node:
                clean(child)
    clean(schema)
    if revision:
        if slide_count is not None:
            schema["properties"]["slides"].update(minItems=slide_count, maxItems=slide_count)
        if frozen_title is not None:
            schema['properties']['title']['const'] = frozen_title
        for definition in schema.get("$defs", {}).values():
            if "layout" in definition.get("properties", {}):
                definition.setdefault("required", []).append("id")
                if slide_ids is not None:
                    definition['properties']['id']['enum'] = list(slide_ids)
        definitions = schema.pop("$defs", {})
        schema = {
            "$defs": definitions, "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["applied", "unsupported"]},
                "document": {"anyOf": [schema, {"type": "null"}]},
            },
            "required": ["status", "document"], "additionalProperties": False,
        }
    else:
        for definition in schema.get("$defs", {}).values():
            definition.get("properties", {}).pop("id", None)
            if definition.get('properties', {}).get('layout', {}).get('const') == 'closing':
                definition.setdefault('required', []).append('subtitle')
                definition['properties']['subtitle']['minLength'] = 1
            if grounded and 'layout' in definition.get('properties', {}):
                minimum = (0 if definition['properties']['layout'].get('const')
                           in ('title', 'closing') else 1)
                evidence = {'type': 'array', 'minItems': minimum, 'maxItems': 6,
                            'items': {'type': 'string', 'minLength': 20, 'maxLength': 800}}
                definition['properties'] = {'source_quotes': evidence, **definition['properties']}
                definition.setdefault('required', []).insert(0, 'source_quotes')
    return schema


def _normalize(result, generation):
    if (generation and isinstance(result, dict) and isinstance(result.get("slides"), list)
            and result["slides"] and all(isinstance(s, dict) for s in result["slides"])):
        result = copy.deepcopy(result)
        if result["slides"][0].get("layout") != "title":
            result["slides"].insert(0, {"layout": "title", "title": result.get("title")})
        if result["slides"][-1].get("layout") != "closing":
            result["slides"].append({"layout": "closing", "title": result.get("title")})
    return normalize_document(result, generation=generation, max_bytes=8_000_000)


def _slide_text(slide, include_title=True):
    fragments = [slide['title']] if include_title else []
    for key in ('subtitle', 'caption', 'body'):
        if slide.get(key):
            fragments.append(slide[key])
    fragments.extend(slide.get('bullets', []))
    for title_key, list_key in (('leftTitle', 'left'), ('rightTitle', 'right')):
        if slide.get(title_key):
            fragments.append(slide[title_key])
        fragments.extend(slide.get(list_key, []))
    return '\n'.join(fragments)


def _join_generation_headings(document):
    """Join an internal heading and its untitled content, retaining visible qualifiers."""
    slides = document['slides']
    joined = [slides[0]]
    index = 1
    while index < len(slides) - 1:
        heading = slides[index]
        following = slides[index + 1]
        if (heading['layout'] in ('title', 'section') and heading['title'].strip()
                and following['layout'] in ('text', 'bullets', 'two-column')
                and not following['title'].strip()):
            body = '\n'.join(filter(None, (_slide_text(heading, False),
                                          _slide_text(following, False))))
            notes = '\n\n'.join(s['notes'] for s in (heading, following) if s.get('notes'))
            if len(body) <= 800 and len(notes.encode('utf-16-le')) // 2 <= 10_000:
                slide = {'id': following['id'], 'layout': 'text',
                         'title': heading['title'], 'body': body}
                if notes:
                    slide['notes'] = notes
                joined.append(slide)
                index += 2
                continue
        joined.append(heading)
        index += 1
    joined.append(slides[-1])
    return _normalize(dict(document, slides=joined), True)


def _pack_short_generation(document, target_count):
    """Combine short adjacent sections verbatim; never truncate or regenerate."""
    if len(document['slides']) <= target_count:
        return document
    content = document['slides'][1:-1]
    texts = [_slide_text(slide) for slide in content]
    if target_count == 3:
        groups = [(0, len(content))]
    else:
        split = min(range(1, len(content)), key=lambda i: max(
            len('\n\n'.join(texts[:i])), len('\n\n'.join(texts[i:])),
        ))
        groups = [(0, split), (split, len(content))]
    packed = []
    for start, end in groups:
        body = '\n\n'.join(texts[start:end])
        if len(body) > 800:
            raise ValueError('Generated document exceeds readable short-source budget')
        slide = {'layout': 'text', 'title': content[start]['title'], 'body': body}
        notes = [s['title'] + '\n' + s['notes'] for s in content[start:end] if s.get('notes')]
        if notes:
            slide['notes'] = '\n\n'.join(notes)
        packed.append(slide)
    return _normalize(dict(document, slides=[document['slides'][0], *packed,
                                            document['slides'][-1]]), True)


def _fit_generation_budget(document, target_count):
    """Fit an ordered partition of content without losing text or boundary slots."""
    document = copy.deepcopy(document)
    slides = document['slides']
    if len(slides) <= target_count:
        return document
    content = slides[1:-1]

    @lru_cache(maxsize=None)
    def group(start, stop):
        if stop == start + 1:
            return content[start], 0
        parts = content[start:stop]
        body = '\n\n'.join(_slide_text(slide) for slide in parts)
        notes = '\n\n'.join(slide['notes'] for slide in parts if slide.get('notes'))
        body_length = len(body.encode('utf-16-le')) // 2
        if body_length > 800 or len(notes.encode('utf-16-le')) // 2 > 10_000:
            return None
        merged = {'id': parts[0]['id'], 'layout': 'text',
                  'title': parts[0]['title'], 'body': body}
        if notes:
            merged['notes'] = notes
        return merged, body_length ** 2

    @lru_cache(maxsize=None)
    def partition(start, slots):
        if slots == 0:
            return (0, ()) if start == len(content) else None
        best = None
        for stop in range(start + 1, len(content) - slots + 2):
            candidate = group(start, stop)
            if candidate is None:
                # Larger adjacent groups can only add text and notes.
                break
            tail = partition(stop, slots - 1)
            if tail is None:
                continue
            score = candidate[1] + tail[0]
            if best is None or score < best[0]:
                best = score, ((start, stop), *tail[1])
        return best

    chosen = partition(0, target_count - 2)
    if chosen is None:
        raise ValueError('Generated document exceeds readable slide budget')
    document['slides'] = [slides[0], *(group(a, b)[0] for a, b in chosen[1]), slides[-1]]
    return document


def _fill_generation_closing(document, *, recap_slides):
    """Fill an empty ending from a complete block before budget compaction."""
    closing = document['slides'][-1]
    if closing.get('subtitle', '').strip():
        return
    for slide in reversed(recap_slides):
        replace_title = (not closing['title'].strip()
                         or closing['title'].strip() == document['title'].strip())
        include_title = not replace_title and closing['title'].strip() != slide['title'].strip()
        recap = _slide_text(slide, include_title=include_title).strip()
        # Reuse the whole block so facts keep their qualifications. Never clip.
        if slide['title'].strip() and recap and len(recap.encode('utf-16-le')) // 2 <= 400:
            if replace_title:
                closing['title'] = slide['title']
            closing['subtitle'] = recap
            return
    raise ValueError('Generated document has no readable closing recap')


def generate(*, text, slideCount, job_id, deadline, title=None, page_passages=None):
    timeout = remaining_seconds(deadline)
    version = get_prompt_version()
    if page_passages is not None:
        if version != 'v7' or not page_passages:
            raise ValueError('PDF generation requires v7 and source passages')
        text = '\n\n'.join(passage.text for passage in page_passages)
    short_budget = version in ('v3', 'v4', 'v5', 'v6', 'v7') and len(text) < 1000
    target_count = min(slideCount, 4) if short_budget else slideCount
    schema = _schema(grounded=version == 'v7')
    # The budget always includes cover and closing, not just content slides.
    schema['properties']['slides']['maxItems'] = target_count
    payload = {"operation": "generate", "text": text, "slideCount": target_count}
    if version in ('v5', 'v6', 'v7'):
        sections = []
        for block in text.replace('\r\n', '\n').split('\n\n'):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if (len(lines) > 1 and len(lines[0]) <= 120
                    and not lines[0].endswith(('.', '!', '?', '。'))):
                sections.append(lines[0])
        if sections:
            payload['source_sections'] = sections[:32]
    if page_passages is not None:
        payload['source_passages'] = [
            {'page': passage.page_number, 'text': passage.text} for passage in page_passages
        ]
    elif version == 'v7':
        payload['source_passages'] = select_source_passages(text)
    if title is not None:
        payload["title"] = title
    result = request_document(
        system=build_generation_prompt(),
        payload=payload, schema=schema, timeout=timeout,
    )
    remaining_seconds(deadline)
    if version == 'v7':
        result = attach_source_quotes(result, text, page_passages=page_passages)
    normalized = _join_generation_headings(_normalize(result, True))
    recap_slides = normalized['slides'][1:-1]
    if short_budget:
        normalized = _pack_short_generation(normalized, target_count)
    else:
        normalized = _fit_generation_budget(normalized, target_count)
    # Structural normalization may have inserted missing boundary slides.
    # Reject overflow instead of silently publishing N+1 or discarding content.
    if len(normalized['slides']) > target_count:
        raise ValueError('Generated document exceeds requested slide budget')
    # Detect the synthesized document-title placeholder before an explicit title
    # replaces the model's document title.
    _fill_generation_closing(normalized, recap_slides=recap_slides)
    cover_title = title.strip() if title and title.strip() else normalized['title']
    normalized['title'] = cover_title
    normalized['slides'][0]['title'] = cover_title
    return _normalize(normalized, True)


def revise(*, document, text, slideCount, instruction, target_slide_numbers,
           target_slide_ids, job_id, deadline):
    timeout = remaining_seconds(deadline)
    original = copy.deepcopy(document)
    ids = [s["id"] for s in original["slides"]]
    if (target_slide_numbers is None) != (target_slide_ids is None):
        raise ValueError("Both target lists must be supplied together")
    if target_slide_numbers is not None:
        if (not target_slide_numbers or len(set(target_slide_numbers)) != len(target_slide_numbers)
                or any(type(n) is not int or n < 1 or n > len(ids)
                       for n in target_slide_numbers)
                or [ids[n - 1] for n in target_slide_numbers] != target_slide_ids):
            raise ValueError("Invalid revision targets")
    reject_explicit_structure_change(instruction)
    scoped = target_slide_ids is not None
    frozen_targets = tuple(target_slide_ids) if scoped else None
    expected_ids = frozen_targets if scoped else tuple(ids)
    result = request_document(
        system=build_revision_prompt(scoped=scoped),
        payload={"operation": "revise", "document": copy.deepcopy(original), "text": text,
                 "slideCount": slideCount, "instruction": instruction,
                 "target_slide_numbers": list(target_slide_numbers) if scoped else None,
                 "target_slide_ids": list(frozen_targets) if scoped else None,
                 "response_scope": 'selected_slides' if scoped else 'all_slides'},
        schema=_schema(revision=True, slide_count=len(expected_ids), slide_ids=expected_ids,
                       frozen_title=original['title'] if scoped else None), timeout=timeout,
    )
    remaining_seconds(deadline)
    if (not isinstance(result, dict) or set(result) != {"status", "document"}
            or result["status"] not in ("applied", "unsupported")):
        raise ValueError("Invalid revision response envelope")
    if result["status"] == "unsupported":
        if result["document"] is not None:
            raise ValueError("Unsupported revision must not contain a document")
        raise NotImplementedError("Unsupported presentation operation")
    current = _normalize(result["document"], False)
    current_ids = [s['id'] for s in current['slides']]
    if scoped:
        if len(current_ids) != len(expected_ids) or set(current_ids) != set(expected_ids):
            raise ValueError('Revision changed requested slide identities')
        replacements = {slide['id']: slide for slide in current['slides']}
        original["slides"] = [
            replacements.get(slide['id'], slide) for slide in original['slides']
        ]
        current = original
    elif current_ids != ids:
        raise ValueError("Revision changed slide identities or order")
    validate_revision(document, current, frozen_targets)
    return current
