"""Compare source table rows with the saved comparison and its PowerPoint export."""

import re
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from presentation_ml.source_document import build_source_payload
from presentation_ml.source_reply import table_claim_from_fact, table_comparison_chart
from tools.pptx_package import NS, REL_ID, paragraph_text, related_parts, slide_parts


class ChartSource(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    source_block: str = Field(min_length=1)
    periods: list[str] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def valid_periods(self):
        if len(set(self.periods)) != 2 or not all(period.strip() for period in self.periods):
            raise ValueError('Comparison requires two distinct period labels')
        return self


class ChartCheck(ChartSource):
    slide: int = Field(ge=1)
    rows: list[int] = Field(min_length=1, max_length=6)
    allow_table: bool = False

    @model_validator(mode='after')
    def valid_rows(self):
        if min(self.rows) < 3 or len(set(self.rows)) != len(self.rows):
            raise ValueError('Comparison rows must be distinct and start at row 3')
        return self


def _points(element, path):
    nodes = element.findall(path, NS)
    values = {
        int(item.attrib['idx']): item.findtext('c:v', namespaces=NS)
        for item in nodes
    }
    if sorted(values) != list(range(len(nodes))) or None in values.values():
        raise ValueError('Chart cache points must have contiguous indexes and values')
    return [values[index] for index in range(len(values))]


def _chart_issues(plot, chart, expected):
    series = chart.findall('c:ser', NS)
    actual_periods = [_points(item, 'c:tx//c:pt') for item in series]
    actual_categories = [_points(item, 'c:cat//c:pt') for item in series]
    actual_values = [[float(value) for value in _points(item, 'c:val//c:pt')] for item in series]
    labels = chart.findall('.//c:dLbls', NS)
    default_format = chart.find('c:dLbls/c:numFmt', NS)
    series_formats = [item.find('c:dLbls/c:numFmt', NS) for item in series]
    formats = [item if item is not None else default_format for item in series_formats]
    format_pattern = r'0(?:\.([#0]+))?' + (r'"%"' if expected.get('unit') else '')
    matches = [re.fullmatch(format_pattern, item.get('formatCode', ''))
               if item is not None else None for item in formats]
    axis = plot.find('c:valAx/c:numFmt', NS)
    axis_format = axis.get('formatCode', '') if axis is not None else ''
    expected_values = [item['values'] for item in expected['series']]
    required_places = max(
        -Decimal(str(value)).normalize().as_tuple().exponent
        for row in expected_values for value in row
    )
    issues = []
    if actual_periods != [[item['label']] for item in expected['series']]:
        issues.append('periods')
    if actual_categories != [expected['categories']] * len(expected['series']):
        issues.append('categories')
    if actual_values != expected_values:
        issues.append('values')
    if not labels or any(label.find('c:showVal[@val="1"]', NS) is None for label in labels):
        issues.append('values_hidden')
    if not matches or not all(matches) or not re.fullmatch(format_pattern, axis_format):
        issues.append('unit')
    if matches and all(matches) and min(len(match.group(1) or '') for match in matches) < (
        required_places
    ):
        issues.append('display_precision')
    return issues


def _table_rows(table):
    return [
        [' '.join(' '.join(paragraph_text(p) for p in cell.findall('a:txBody/a:p', NS)).split())
         for cell in row.findall('a:tc', NS)]
        for row in table.findall('a:tr', NS)
    ]


def _table_issues(slide, expected):
    candidates = [
        rows for table in slide.findall('p:cSld/p:spTree//a:tbl', NS)
        if (rows := _table_rows(table)) and rows[0] and rows[0][0] == 'Группа'
    ]
    if not candidates:
        return ['missing_chart_or_table']
    if len(candidates) != 1:
        return ['table_count']
    header, *rows = candidates[0]
    if len(header) != 3 or len(rows) != len(expected['categories']) or any(
        len(row) != 3 for row in rows
    ):
        return ['table_shape']
    issues = []
    if header[1:] != [item['label'] for item in expected['series']]:
        issues.append('periods')
    if [row[0] for row in rows] != expected['categories']:
        issues.append('categories')
    cells = [row[1:] for row in rows]
    is_percent = expected.get('unit') == '%'
    if any(cell.endswith('%') != is_percent for row in cells for cell in row):
        issues.append('unit')
    if any(not re.fullmatch(r'(?:\d+|\d{1,3}(?: \d{3})+)(?:,\d+)?%?', cell)
           for row in cells for cell in row):
        return [*issues, 'values']
    numbers = [[float(cell.rstrip('%').replace(' ', '').replace(',', '.')) for cell in row]
               for row in cells]
    if [list(column) for column in zip(*numbers, strict=True)] != [
        item['values'] for item in expected['series']
    ]:
        issues.append('values')
    return issues


def _export_issues(deck, slide_part, expected, allow_table):
    slide = ET.fromstring(deck.read(slide_part))
    references = slide.findall('p:cSld/p:spTree//c:chart', NS)
    if not references:
        return _table_issues(slide, expected) if allow_table else ['missing_chart']
    if len(references) != 1:
        return ['chart_count']
    targets = related_parts(deck, slide_part, 'chart')
    chart_part = targets[references[0].attrib[REL_ID]]
    plot = ET.fromstring(deck.read(chart_part)).find('c:chart/c:plotArea', NS)
    chart = plot.find('c:barChart', NS) if plot is not None else None
    return _chart_issues(plot, chart, expected) if chart is not None else ['chart_type']


def _document_issues(slides, number, expected):
    actual = slides[number - 1].get('composition', {}) if number <= len(slides) else {}
    if actual.get('kind') != 'comparison':
        return ['missing_comparison']
    issues = ['categories'] if actual['categories'] != expected['categories'] else []
    for field, issue in [('label', 'periods'), ('values', 'values')]:
        if [item[field] for item in actual['series']] != [
            item[field] for item in expected['series']
        ]:
            issues.append(issue)
    if actual.get('unit') != expected.get('unit'):
        issues.append('unit')
    return issues


def _chart_from_source(check, facts):
    addresses = [(check.source_block, row, *check.periods) for row in check.rows]
    if any(address not in facts for address in addresses):
        return None
    return table_comparison_chart([table_claim_from_fact(facts[address]) for address in addresses])


def _check_coverage(coverage, facts, results):
    reports = []
    for scope in coverage:
        expected = {
            row for block, row, first, second in facts
            if block == scope.source_block and [first, second] == scope.periods
        }
        assigned = set()
        passed = set()
        for result in results:
            if result['source_block'] != scope.source_block or result['periods'] != scope.periods:
                continue
            assigned.update(result['rows'])
            if result['first_mismatch'] is None:
                passed.update(result['rows'])
        reports.append({
            **scope.model_dump(),
            'source_match': bool(expected),
            'expected_rows': sorted(expected),
            'unassigned_rows': sorted(expected - assigned),
            'failed_rows': sorted((expected & assigned) - passed),
        })
    return reports


def inspect_charts(path, source, document, checks, coverage):
    payload = build_source_payload(source, limit=None, relations=frozenset({'metric_comparison'}))
    facts = {
        (fact['source']['block_id'], fact['source']['row'],
         fact['qualifiers']['first_period'], fact['qualifiers']['second_period']): fact
        for fact in payload['source_facts']
    }
    results = []
    with ZipFile(path) as deck:
        parts = slide_parts(deck)
        for check in checks:
            expected = _chart_from_source(check, facts)
            document_issues = []
            pptx_issues = []
            first_mismatch = 'source'
            if expected is not None:
                document_issues = _document_issues(document['slides'], check.slide, expected)
                pptx_issues = (
                    _export_issues(deck, parts[check.slide - 1], expected, check.allow_table)
                    if check.slide <= len(parts) else ['missing_slide']
                )
                first_mismatch = next((stage for stage, issues in (
                    ('document', document_issues), ('pptx', pptx_issues),
                ) if issues), None)
            results.append({
                **check.model_dump(),
                'source_match': expected is not None,
                'document_issues': document_issues,
                'pptx_issues': pptx_issues,
                'first_mismatch': first_mismatch,
            })
    return results, _check_coverage(coverage, facts, results)
