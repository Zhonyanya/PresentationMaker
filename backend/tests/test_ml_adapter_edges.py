import copy
import sys
from types import ModuleType

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.ml.adapter import FixtureAdapter, ModuleAdapter, get_adapter


def test_missing_ml_module_is_unavailable(monkeypatch):
    monkeypatch.setattr(get_settings(), "ml_module", "_pm_nonexistent_test_ml_module")
    with pytest.raises(AppError) as exc:
        ModuleAdapter()
    assert (exc.value.status, exc.value.code) == (503, "ML_UNAVAILABLE")


@pytest.mark.parametrize("operation", ["generate", "revise"])
@pytest.mark.parametrize("function", [None, "not callable"])
def test_missing_ml_callable_does_not_fall_back(monkeypatch, operation, function):
    module = ModuleType("presentation_ml")
    module.PRESERVES_SLIDE_IDS = True
    setattr(module, operation, function)
    monkeypatch.setattr(get_settings(), "ml_module", module.__name__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(AppError) as exc:
        ModuleAdapter().invoke(operation, {})
    assert exc.value.code == "ML_CAPABILITY_UNAVAILABLE"


def test_async_unsupported_operation_has_same_public_error(monkeypatch):
    module = ModuleType("presentation_ml")

    async def generate(**inputs):
        raise NotImplementedError("private model details")

    module.generate = generate
    monkeypatch.setattr(get_settings(), "ml_module", module.__name__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(AppError) as exc:
        ModuleAdapter().invoke("generate", {})
    assert exc.value.code == "ML_CAPABILITY_UNAVAILABLE"
    assert "private" not in exc.value.message


def test_adapter_selection_is_explicit(monkeypatch):
    monkeypatch.setattr(get_settings(), "ml_adapter", "fixture")
    assert isinstance(get_adapter(), FixtureAdapter)
    monkeypatch.setattr(get_settings(), "ml_adapter", "module")
    module = ModuleType("presentation_ml")
    monkeypatch.setattr(get_settings(), "ml_module", module.__name__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert isinstance(get_adapter(), ModuleAdapter)


@pytest.mark.parametrize("targets", [None, ["fixture-text", "fixture-columns"]])
def test_fixture_revision_does_not_mutate_snapshot(document, targets):
    before = copy.deepcopy(document)
    revised = FixtureAdapter().invoke("revise", {
        "document": document, "target_slide_ids": targets,
    })
    assert document == before
    selected = targets or [document["slides"][0]["id"]]
    for old, new in zip(document["slides"], revised["slides"], strict=True):
        assert old["id"] == new["id"]
        if old["id"] in selected:
            assert old.get("notes") != new["notes"]
            assert {k: v for k, v in new.items() if k != "notes"} == {
                k: v for k, v in old.items() if k != "notes"
            }
        else:
            assert new == old
