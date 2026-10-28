import sys
import types

import pytest

from app.core.errors import AppError
from app.ml.adapter import ModuleAdapter


def test_sync_generate_receives_count_and_context(monkeypatch, document):
    module = types.ModuleType("presentation_ml")
    received = {}

    def generate(**inputs):
        received.update(inputs)
        return document

    module.generate = generate
    monkeypatch.setitem(sys.modules, "presentation_ml", module)
    result = ModuleAdapter().invoke(
        "generate", {"text": "text", "slideCount": 17, "job_id": "job", "deadline": "deadline"}
    )
    assert received["slideCount"] == 17
    assert received["job_id"] == "job" and result == document


def test_async_revision_and_missing_identity_capability(monkeypatch, document):
    module = types.ModuleType("presentation_ml")

    async def revise(**inputs):
        assert inputs["document"] == document
        assert inputs["target_slide_ids"] == [document["slides"][2]["id"]]
        return document

    module.revise = revise
    monkeypatch.setitem(sys.modules, "presentation_ml", module)
    adapter = ModuleAdapter()
    inputs = {"document": document, "target_slide_ids": [document["slides"][2]["id"]]}
    with pytest.raises(AppError) as exc:
        adapter.invoke("revise", inputs)
    assert exc.value.code == "ML_CAPABILITY_UNAVAILABLE"
    module.PRESERVES_SLIDE_IDS = True
    assert adapter.invoke("revise", inputs) == document


def test_unsupported_operation_not_replaced_with_generation(monkeypatch):
    module = types.ModuleType("presentation_ml")
    module.PRESERVES_SLIDE_IDS = True

    def revise(**inputs):
        raise NotImplementedError

    module.revise = revise
    monkeypatch.setitem(sys.modules, "presentation_ml", module)
    with pytest.raises(AppError) as exc:
        ModuleAdapter().invoke("revise", {})
    assert exc.value.code == "ML_CAPABILITY_UNAVAILABLE"
