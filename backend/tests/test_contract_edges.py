import copy
import json

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.presentations.schemas import GenerateRequest, normalize_document, validate_revision


@pytest.mark.parametrize("encoding", ["str", "bytes"])
def test_json_transport_uses_utf8_byte_limit(document, encoding):
    raw = json.dumps(document, ensure_ascii=False)
    if encoding == "bytes":
        raw = raw.encode()
    size = len(raw.encode() if isinstance(raw, str) else raw)
    assert normalize_document(raw, generation=True, max_bytes=size) == document
    with pytest.raises(ValueError, match="too large"):
        normalize_document(raw, generation=True, max_bytes=size - 1)


@pytest.mark.parametrize("raw", [None, [], {}, {"slides": {}}, {"slides": [None]}, "{", b"\xff"])
def test_malformed_documents_are_rejected(raw):
    with pytest.raises((ValueError, ValidationError)):
        normalize_document(raw, generation=True, max_bytes=8_000_000)


@pytest.mark.parametrize("edge", ["first", "last", "empty"])
def test_generation_requires_nonempty_slides_and_boundary_layouts(document, edge):
    if edge == "first":
        document["slides"].pop(0)
    elif edge == "last":
        document["slides"].pop()
    else:
        document["slides"] = []
    with pytest.raises(ValueError):
        normalize_document(document, generation=True, max_bytes=8_000_000)


@pytest.mark.parametrize("identifier", [None, "duplicate", " padded ", "   "])
def test_revision_rejects_ambiguous_ids(document, identifier):
    if identifier is None:
        document["slides"][0].pop("id")
    elif identifier == "duplicate":
        document["slides"][0]["id"] = document["slides"][1]["id"]
    else:
        document["slides"][0]["id"] = identifier
    with pytest.raises(ValueError):
        normalize_document(document, generation=False, max_bytes=8_000_000)


@pytest.mark.parametrize("change", ["title", "reorder", "insert", "rename"])
def test_targeted_revision_cannot_change_non_target_structure(document, change):
    revised = copy.deepcopy(document)
    if change == "title":
        revised["title"] = "Changed title"
    elif change == "reorder":
        revised["slides"][0], revised["slides"][1] = revised["slides"][1], revised["slides"][0]
    elif change == "insert":
        revised["slides"].append({**document["slides"][2], "id": "new-slide"})
    else:
        revised["slides"][2]["id"] = "new-identity"
    with pytest.raises(AppError) as exc:
        validate_revision(document, revised, [document["slides"][2]["id"]])
    assert exc.value.code == "INVALID_ML_RESPONSE"


def test_targeted_revision_cannot_remove_selected_slide_or_mutate_input(document):
    before = copy.deepcopy(document)
    revised = copy.deepcopy(document)
    removed = revised["slides"].pop(2)
    with pytest.raises(AppError) as exc:
        validate_revision(document, revised, [removed["id"]])
    assert exc.value.code == "INVALID_ML_RESPONSE"
    assert document == before
    normalized = normalize_document(document, generation=True, max_bytes=8_000_000)
    normalized["slides"][0]["title"] = "Changed result"
    assert document == before


def test_unrestricted_revision_allows_content_changes_without_mutating_input(document):
    before = copy.deepcopy(document)
    revised = copy.deepcopy(document)
    revised["title"] = "New title"
    revised["slides"][2]["body"] = "Changed body"
    revised["slides"][3]["bullets"] = ["Changed bullet"]
    normalized = normalize_document(revised, generation=False, max_bytes=8_000_000)
    validate_revision(document, normalized, None)
    assert normalized == revised
    assert document == before


@pytest.mark.parametrize("scope", ["all", "empty", "selected"])
@pytest.mark.parametrize(
    "change", ["rename", "replace_all", "swap_ids", "move", "insert", "delete"]
)
def test_revision_requires_original_ordered_ids(document, scope, change):
    before = copy.deepcopy(document)
    revised = copy.deepcopy(document)
    slides = revised["slides"]
    if change == "rename":
        slides[2]["id"] = "replacement-id"
    elif change == "replace_all":
        for index, slide in enumerate(slides):
            slide["id"] = f"replacement-{index}"
    elif change == "swap_ids":
        slides[2]["id"], slides[3]["id"] = slides[3]["id"], slides[2]["id"]
    elif change == "move":
        slides.insert(4, slides.pop(2))
    elif change == "insert":
        slides.insert(3, {**slides[2], "id": "new-slide"})
    else:
        slides.pop(2)
    targets = {"all": None, "empty": [], "selected": [document["slides"][2]["id"]]}[scope]
    normalized = normalize_document(revised, generation=False, max_bytes=8_000_000)
    with pytest.raises(AppError) as exc:
        validate_revision(document, normalized, targets)
    assert exc.value.status == 502
    assert exc.value.code == "INVALID_ML_RESPONSE"
    assert document == before
    assert normalized == revised


def test_generation_title_must_be_absent_or_string():
    body = {"text": "x" * 100, "slideCount": 3}
    assert GenerateRequest.model_validate(body).title is None
    assert GenerateRequest.model_validate({**body, "title": "  Title  "}).title == "Title"
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({**body, "title": None})
