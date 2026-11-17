"""Verify structured table claims before rendering them as slide text."""

from pydantic import BaseModel, ConfigDict


class TableClaim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    fact_id: str
    group: str
    metric: str
    first_period: str
    first_value: str
    second_period: str
    second_value: str


def verified_table_claim(payload: dict, reply: object) -> dict:
    """Resolve one model claim against the exact fact packet sent to the model."""
    claim = TableClaim.model_validate(reply)
    fact = next((item for item in payload['source_facts'] if item['id'] == claim.fact_id), None)
    if fact is None or fact['relation'] != 'metric_comparison' or fact['status'] != 'reported':
        raise ValueError('Unknown or incompatible table fact')
    expected = {
        'fact_id': fact['id'], 'group': fact['subject'], 'metric': fact['target'],
        **fact['qualifiers'],
    }
    if claim.model_dump() != expected:
        raise ValueError('Table claim differs from source evidence')
    return {
        'title': claim.metric,
        'body': '\n'.join((
            claim.group,
            f'{claim.first_period} — {claim.first_value}',
            f'{claim.second_period} — {claim.second_value}',
        )),
        'source': dict(fact['source']),
    }
