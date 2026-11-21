"""Verify structured table claims before rendering them as slide text."""

import re

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


def table_comparison_chart(claims: list[TableClaim]) -> dict | None:
    """Use one chart only for distinct groups with the same metric, periods and units."""
    if not 1 <= len(claims) <= 6:
        return None
    categories = [claim.group for claim in claims]
    measures = {(claim.metric, claim.first_period, claim.second_period) for claim in claims}
    if (len(set(categories)) != len(categories)
            or any(len(name.encode('utf-16-le')) // 2 > 64 for name in categories)
            or len(measures) != 1):
        return None
    first, second = (
        [''.join(value.split()) for value in column]
        for column in ([c.first_value for c in claims], [c.second_value for c in claims])
    )
    values = first + second
    is_percent = first[0].endswith('%')
    if any(value.endswith('%') != is_percent
           or not re.fullmatch(r'\+?\d+(?:[.,]\d{1,3})?%?', value)
           or re.fullmatch(r'\+?[1-9]\d{0,2}[.,]\d{3}%?', value) for value in values):
        return None
    rows = [[float(value.rstrip('%').replace(',', '.')) for value in column]
            for column in (first, second)]
    if any(value > 1_000_000_000 for row in rows for value in row):
        return None
    return {
        'kind': 'comparison', 'categories': categories,
        'series': [
            {'label': claims[0].first_period, 'values': rows[0]},
            {'label': claims[0].second_period, 'values': rows[1]},
        ],
        **({'unit': '%'} if is_percent else {}),
    }


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
