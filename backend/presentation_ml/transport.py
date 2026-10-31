"""Dispatch exactly one request through the provider-neutral boundary."""

from .providers import get_provider


def request_document(*, system, payload, schema, timeout):
    return get_provider().complete_json(system=system, payload=payload,
                                        schema=schema, timeout=timeout)
