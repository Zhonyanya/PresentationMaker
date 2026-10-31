"""Provider selection without initializing network clients."""

import os
from typing import Protocol


class JsonProvider(Protocol):
    def complete_json(self, *, system: str, payload: dict, schema: dict,
                      timeout: float) -> object: ...


def get_provider() -> JsonProvider:
    name = os.getenv('PM_ML_PROVIDER', 'gigachat').strip().lower()
    if name == 'gigachat':
        from .gigachat import GigaChatProvider

        return GigaChatProvider()
    raise NotImplementedError('Unsupported ML provider')
