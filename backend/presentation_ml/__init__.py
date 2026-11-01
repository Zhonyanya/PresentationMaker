"""Contract-compatible presentation generation; import performs no provider work."""

import copy
from datetime import UTC, datetime

from app.presentations.schemas import Document, normalize_document, validate_revision

from .capabilities import reject_explicit_structure_change
from .grounding import attach_source_quotes
from .prompts import build_prompt, build_revision_prompt, get_prompt_version
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


def generate(*, text, slideCount, job_id, deadline, title=None):
    timeout = remaining_seconds(deadline)
    version = get_prompt_version()
    short_budget = version in ('v3', 'v4', 'v5', 'v6', 'v7') and len(text) < 1000
    target_count = min(slideCount, 4) if short_budget else slideCount
    schema = _schema(grounded=version == 'v7')
    if short_budget:
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
    if title is not None:
        payload["title"] = title
    result = request_document(
        system=build_prompt('generate'),
        payload=payload, schema=schema, timeout=timeout,
    )
    remaining_seconds(deadline)
    if version == 'v7':
        result = attach_source_quotes(result, text)
    normalized = _join_generation_headings(_normalize(result, True))
    if short_budget:
        normalized = _pack_short_generation(normalized, target_count)
    return normalized


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
