"""Contract-compatible presentation generation; import performs no provider work."""

import copy
from datetime import UTC, datetime

from app.presentations.schemas import Document, normalize_document, validate_revision

from .capabilities import reject_explicit_structure_change
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


def _schema(revision=False, slide_count=None):
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
        for definition in schema.get("$defs", {}).values():
            if "layout" in definition.get("properties", {}):
                definition.setdefault("required", []).append("id")
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
    return schema


def _normalize(result, generation):
    if (generation and isinstance(result, dict) and isinstance(result.get("slides"), list)
            and result["slides"] and all(isinstance(s, dict) for s in result["slides"])):
        result = copy.deepcopy(result)
        if result["slides"][0].get("layout") != "title":
            result["slides"].insert(0, {"layout": "title", "title": result.get("title")})
        if result["slides"][-1].get("layout") != "closing":
            result["slides"].append({"layout": "closing", "title": "Спасибо за внимание"})
    return normalize_document(result, generation=generation, max_bytes=8_000_000)


def generate(*, text, slideCount, job_id, deadline, title=None):
    timeout = remaining_seconds(deadline)
    short_budget = get_prompt_version() == 'v3' and len(text) < 1000
    target_count = min(slideCount, 4) if short_budget else slideCount
    schema = _schema()
    if short_budget:
        schema['properties']['slides']['maxItems'] = target_count
    payload = {"operation": "generate", "text": text, "slideCount": target_count}
    if title is not None:
        payload["title"] = title
    result = request_document(
        system=build_prompt('generate'),
        payload=payload, schema=schema, timeout=timeout,
    )
    remaining_seconds(deadline)
    normalized = _normalize(result, True)
    if short_budget and len(normalized['slides']) > target_count:
        raise ValueError('Generated document exceeds short-source budget')
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
    result = request_document(
        system=build_revision_prompt(),
        payload={"operation": "revise", "document": original, "text": text,
                 "slideCount": slideCount, "instruction": instruction,
                 "target_slide_numbers": target_slide_numbers,
                 "target_slide_ids": target_slide_ids},
        schema=_schema(revision=True, slide_count=len(ids)), timeout=timeout,
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
    if [s["id"] for s in current["slides"]] != ids:
        raise ValueError("Revision changed slide identities or order")
    if target_slide_ids is not None:
        selected = set(target_slide_ids)
        original["slides"] = [
            new if new["id"] in selected else old
            for old, new in zip(original["slides"], current["slides"], strict=True)
        ]
        current = original
    validate_revision(document, current, target_slide_ids)
    return current
