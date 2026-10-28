import copy
import json

import jsonschema
import pytest
from conftest import ROOT
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.presentations.schemas import (
    GenerateRequest,
    ReviseRequest,
    normalize_document,
    validate_revision,
)


def normalize(value, generation=True, limit=8_000_000):
    return normalize_document(value, generation=generation, max_bytes=limit)


def test_fixture_matches_both_contracts(document):
    schema = json.loads((ROOT / "docs/generate-response.schema.json").read_text())
    result = normalize(document)
    jsonschema.validate(result, schema)
    assert len({slide["layout"] for slide in result["slides"]}) == 6
    assert normalize(result) == result


def test_generation_ids_and_defaults(document):
    del document["slides"][0]["id"]
    document["slides"][2]["id"] = document["slides"][1]["id"]
    del document["slides"][3]["bullets"]
    del document["slides"][4]["left"]
    result = normalize(document)
    assert len({s["id"] for s in result["slides"]}) == 6
    assert result["slides"][3]["bullets"] == []
    assert result["slides"][4]["left"] == []
    assert normalize(result) == result


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["slides"][0].update(layout="html"),
        lambda d: d["slides"][0].update(title=12),
        lambda d: d["slides"][0].update(title="я" * 201),
        lambda d: d["slides"][0].update(subtitle=None),
        lambda d: d["slides"][0].update(title="😀" * 101),
        lambda d: d["slides"][3].update(bullets=["a"] * 13),
        lambda d: d["slides"][3].update(bullets=["a" * 1001]),
        lambda d: d["slides"][4].update(leftTitle="a" * 121),
        lambda d: d["slides"][2].update(body="a" * 4001),
        lambda d: d["slides"][2].update(notes="a" * 10001),
        lambda d: d.update(slides=d["slides"] * 11),
    ],
)
def test_invalid_result_rejected(document, change):
    change(document)
    with pytest.raises((ValidationError, ValueError)):
        normalize(document)


def test_limits_and_unknown_fields(document):
    document["title"] = "я" * 200
    document["extra"] = {"ignored": True}
    document["slides"][0].update(notes="я" * 10000, subtitle="я" * 400, unknown=None)
    result = normalize(document)
    assert "extra" not in result and "unknown" not in result["slides"][0]
    with pytest.raises(ValueError):
        normalize(document, limit=100)


@pytest.mark.parametrize("slide_count", [None, 2, 21, "8", True, 8.5])
def test_required_slide_count(slide_count):
    body = {"text": "я" * 100}
    if slide_count is not None:
        body["slideCount"] = slide_count
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate(body)


def test_request_trim_and_unicode():
    request = GenerateRequest.model_validate({"text": " " + "😀" * 50 + " ", "slideCount": 3})
    assert request.text == "😀" * 50
    GenerateRequest.model_validate({"text": "я" * 60000, "slideCount": 20})
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({"text": "я" * 60001, "slideCount": 20})


def test_revision_identity_and_scope(document):
    previous = copy.deepcopy(document)
    document["slides"][2]["body"] = "Изменено"
    validate_revision(previous, normalize(document, False), [previous["slides"][2]["id"]])
    document["slides"][3]["title"] = "Вне области"
    with pytest.raises(AppError):
        validate_revision(previous, document, [previous["slides"][2]["id"]])
    document["slides"][0].pop("id")
    with pytest.raises(ValueError):
        normalize(document, False)


@pytest.mark.parametrize("numbers", [[0], [1, 1], [-1], [], [True]])
def test_invalid_targets(numbers):
    with pytest.raises(ValidationError):
        ReviseRequest(
            instruction="Команда", base_document_token="token", target_slide_numbers=numbers
        )


def test_no_hidden_production_fixture():
    with pytest.raises(ValidationError):
        Settings(environment="production", ml_adapter="fixture", allowed_origins=["https://a.test"])
