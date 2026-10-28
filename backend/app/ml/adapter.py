"""Integration boundary only. No model, prompts or command interpretation here."""

import asyncio
import copy
import importlib
import inspect
import json
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError


class ModuleAdapter:
    def __init__(self):
        try:
            self.module = importlib.import_module(get_settings().ml_module)
        except ImportError as exc:
            raise AppError(503, "ML_UNAVAILABLE", "ML-модуль недоступен.") from exc

    def invoke(self, kind: str, inputs: dict):
        function = getattr(self.module, kind, None)
        if not callable(function):
            raise AppError(503, "ML_CAPABILITY_UNAVAILABLE", "ML не поддерживает эту операцию.")
        if kind == "revise" and not getattr(self.module, "PRESERVES_SLIDE_IDS", False):
            raise AppError(
                503, "ML_CAPABILITY_UNAVAILABLE", "ML не подтвердил сохранение ID слайдов."
            )
        try:
            result = function(**inputs)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
        except NotImplementedError as exc:
            raise AppError(
                503, "ML_CAPABILITY_UNAVAILABLE", "ML не поддерживает эту операцию."
            ) from exc
        return result


class FixtureAdapter:
    """Explicit transport/test fixture, not real generation or semantic revision."""

    def invoke(self, kind: str, inputs: dict):
        settings = get_settings()
        time.sleep(settings.fixture_delay)
        if settings.fixture_failure:
            raise AppError(502, "GENERATION_FAILED", "Тестовая ошибка ML.")
        if kind == "generate":
            return json.loads((Path(__file__).parent / "fixtures" / "all-layouts.json").read_text())
        # Deterministic fixture only: preserves identities and modifies an explicit target's notes.
        document = copy.deepcopy(inputs["document"])
        targets = inputs.get("target_slide_ids") or [document["slides"][0]["id"]]
        for slide in document["slides"]:
            if slide["id"] in targets:
                slide["notes"] = "Тестовая правка фикстуры; команда не интерпретировалась."
        return document


def get_adapter():
    if get_settings().ml_adapter == "fixture":
        return FixtureAdapter()
    return ModuleAdapter()
