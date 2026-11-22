"""Check exported PPTX text and optionally trace facts from earlier snapshots."""

import argparse
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from tools.pptx_package import NS, paragraph_text, slide_parts


def _normalize(value):
    return ' '.join(value.casefold().split())


def _read_slide_paragraphs(path):
    with ZipFile(path) as deck:
        return [
            [
                _normalize(paragraph_text(paragraph))
                for paragraph in ET.fromstring(deck.read(part)).findall('p:cSld/p:spTree//a:p', NS)
            ]
            for part in slide_parts(deck)
        ]


def _fragment_pattern(fragment):
    query = _normalize(fragment)
    if not query:
        raise ValueError('Expected text fragments must not be empty')
    start = r'(?<!\d)(?<!\d[,.])' if query[0].isdecimal() else ''
    end = r'(?!\d|[,.]\d)' if query[-1].isdecimal() else ''
    return re.compile(start + re.escape(query) + end)


def _matching_locations(fragments, locations, *, exact=False, context=()):
    matching = {_normalize(fragment) for fragment in fragments} if exact else set()
    patterns = [] if exact else [_fragment_pattern(fragment) for fragment in fragments]
    qualifiers = [_fragment_pattern(fragment) for fragment in context]

    def matches(paragraph):
        found = paragraph in matching if exact else any(
            pattern.search(paragraph) for pattern in patterns
        )
        return found and (
            not qualifiers or any(pattern.search(paragraph) for pattern in qualifiers)
        )

    return [
        location for location, paragraphs in locations
        if any(matches(paragraph) for paragraph in paragraphs)
    ]


def _find_matches(fragments, slides):
    locations = list(enumerate(slides, 1))
    return {fragment: _matching_locations([fragment], locations) for fragment in fragments}


def inspect_pptx(path, case):
    return _inspect_slide_text(_read_slide_paragraphs(path), case)


def _inspect_slide_text(slides, case):
    mode = case.get('slide_count_mode', 'exact')
    if mode not in ('exact', 'maximum'):
        raise ValueError('Slide count mode must be exact or maximum')
    expected = _find_matches(case.get('anchors', []), slides)
    forbidden = _find_matches(case.get('forbidden_fragments', []), slides)
    return {
        'actual_slides': len(slides),
        'slide_count_delta': len(slides) - case['slideCount'],
        'matches': {fragment: pages for fragment, pages in expected.items() if pages},
        'missing_anchors': [fragment for fragment, pages in expected.items() if not pages],
        'forbidden_matches': {fragment: pages for fragment, pages in forbidden.items() if pages},
        'textless_slides': [number for number, texts in enumerate(slides, 1) if not any(texts)],
    }


def _read_source(path):
    from app.presentations.source_blocks import SOURCE_ADAPTER

    return SOURCE_ADAPTER.validate_json(path.read_bytes())


def _source_locations(source):
    from app.presentations.source_blocks import SourceDocument, TableBlock, source_text

    locations = []
    for block in source.blocks:
        text = source_text(SourceDocument((block,)))
        fields = [text, *text.splitlines()]
        if isinstance(block, TableBlock):
            fields.extend(cell for row in block.rows for cell in row if cell)
        locations.append((block.id, [_normalize(field) for field in fields]))
    return locations


def _slide_fields(slide):
    for key in ('title', 'subtitle', 'caption', 'body', 'leftTitle', 'rightTitle'):
        if key in slide:
            yield from re.split(r'\n\s*\n', slide[key])
            if '\n' in slide[key]:
                yield from slide[key].splitlines()
    for key in ('bullets', 'left', 'right'):
        yield from slide.get(key, [])
    material = slide.get('sourceMaterial', {})
    if material.get('kind') == 'table':
        for row in material['rows']:
            yield from row
    composition = slide.get('composition', {})
    for metric in composition.get('values', []):
        yield metric['label']
        yield metric['value']
    for caveat in composition.get('items', []):
        yield caveat['title']
        yield caveat['detail']


def _read_document(path):
    from app.presentations.schemas import normalize_document

    return normalize_document(path.read_bytes(), generation=True, max_bytes=8_000_000)


def _document_locations(document):
    return [
        (number, [_normalize(field) for field in _slide_fields(slide)])
        for number, slide in enumerate(document['slides'], 1)
    ]


def _validate_facts(facts):
    if not isinstance(facts, list):
        raise ValueError('Facts must be a list')
    ids = set()
    for fact in facts:
        if not isinstance(fact, dict) or not all(
            isinstance(fact.get(key), str) and fact[key].strip() for key in ('id', 'source')
        ):
            raise ValueError('A fact requires an ID and source text')
        if fact['id'] in ids:
            raise ValueError('Fact IDs must be unique within a case')
        ids.add(fact['id'])
        if fact.get('match', 'fragment') not in ('fragment', 'exact'):
            raise ValueError('Fact matching mode must be fragment or exact')
        if fact.get('placement', 'any') not in ('any', 'interior'):
            raise ValueError('Fact placement must be any or interior')
        phrases = fact.get('slide_phrases', [fact['source']])
        if not isinstance(phrases, list) or not phrases or not all(
            isinstance(phrase, str) and phrase.strip() for phrase in phrases
        ):
            raise ValueError('Slide phrases must be a nonempty list of text fragments')
        context = fact.get('slide_context', [])
        if not isinstance(context, list) or not all(
            isinstance(phrase, str) and phrase.strip() for phrase in context
        ):
            raise ValueError('Slide context must be a list of text fragments')


def _trace_facts(facts, source, document, exported):
    exported = list(enumerate(exported, 1))
    traced = []
    for fact in facts:
        exact = fact.get('match') == 'exact'
        source_blocks = _matching_locations([fact['source']], source, exact=exact)
        slide_phrases = fact.get('slide_phrases', [fact['source']])
        context = fact.get('slide_context', [])
        document_slides = _matching_locations(slide_phrases, document, exact=exact, context=context)
        pptx_slides = _matching_locations(slide_phrases, exported, exact=exact, context=context)
        stages = [('source', source_blocks), ('document', document_slides), ('pptx', pptx_slides)]
        result = {
            'id': fact['id'],
            'source_blocks': source_blocks,
            'document_slides': document_slides,
            'pptx_slides': pptx_slides,
            'first_missing': next((stage for stage, matches in stages if not matches), None),
        }
        if context:
            for stage, locations, scoped in (
                ('document', document, document_slides), ('pptx', exported, pptx_slides),
            ):
                bare_matches = _matching_locations(slide_phrases, locations, exact=exact)
                result[f'{stage}_unscoped_slides'] = sorted(set(bare_matches) - set(scoped))
        if fact.get('placement') == 'interior':
            doc_interior = [number for number in document_slides if 1 < number < len(document)]
            pptx_interior = [number for number in pptx_slides if 1 < number < len(exported)]
            presentation_locations = (
                ('document', document_slides, doc_interior),
                ('pptx', pptx_slides, pptx_interior),
            )
            result.update(
                placement='interior',
                document_interior_slides=doc_interior,
                pptx_interior_slides=pptx_interior,
                first_misplaced=next((
                    stage for stage, all_slides, interior in presentation_locations
                    if all_slides and not interior
                ), None),
            )
        traced.append(result)
    return traced


def _inspect_case(case, args):
    case_id = case['id']
    facts = case.get('facts', [])
    charts = case.get('charts', [])
    coverage = case.get('chart_coverage', [])
    deck_path = args.pptx_dir / (case_id + '.pptx')
    stage = 'facts'
    try:
        _validate_facts(facts)
        stage = 'pptx'
        slides = _read_slide_paragraphs(deck_path)
        result = _inspect_slide_text(slides, case)
        if 'geometry' in case:
            from tools.pptx_geometry import inspect_geometry

            stage = 'geometry'
            if not isinstance(case['geometry'], bool):
                raise ValueError('Geometry must be a boolean')
            if case['geometry']:
                result['geometry'] = inspect_geometry(deck_path)
        if facts or charts or coverage:
            stage = 'source'
            source = _read_source(args.source_dir / (case_id + '.json'))
            stage = 'document'
            document = _read_document(args.document_dir / (case_id + '.json'))
            result['document_slide_count'] = len(document['slides'])
        if facts:
            stage = 'facts'
            result['facts'] = _trace_facts(
                facts, _source_locations(source), _document_locations(document), slides,
            )
        if 'charts' in case or 'chart_coverage' in case:
            from tools.pptx_chart_acceptance import ChartCheck, ChartSource, inspect_charts

            stage = 'charts'
            if not isinstance(charts, list) or not isinstance(coverage, list):
                raise ValueError('Charts and chart coverage must be lists')
            checks = [ChartCheck.model_validate(item) for item in charts]
            coverage_checks = [ChartSource.model_validate(item) for item in coverage]
            if checks or coverage_checks:
                stage = 'pptx'
                checked, covered = inspect_charts(
                    deck_path, source, document, checks, coverage_checks,
                )
                result['charts'] = checked
                if coverage_checks:
                    result['chart_coverage'] = covered
    except (OSError, BadZipFile, ET.ParseError, KeyError, ValueError) as exc:
        error = {'id': case_id, 'status': 'error', 'error_type': type(exc).__name__}
        if any(key in case for key in ('facts', 'charts', 'chart_coverage', 'geometry')):
            error['stage'] = stage
        return error

    delta = result['slide_count_delta']
    count_mismatch = delta > 0 if case.get('slide_count_mode') == 'maximum' else delta != 0
    has_findings = bool(result['missing_anchors'] or result['forbidden_matches'] or count_mismatch)
    if facts or charts or coverage:
        has_findings |= result['document_slide_count'] != len(slides)
    has_findings |= any(fact['first_missing'] or fact.get('first_misplaced')
                        for fact in result.get('facts', []))
    has_findings |= any(chart['first_mismatch'] for chart in result.get('charts', []))
    has_findings |= bool(result.get('geometry', {}).get('issues'))
    has_findings |= any(
        not scope['source_match'] or scope['unassigned_rows'] or scope['failed_rows']
        for scope in result.get('chart_coverage', [])
    )
    return {'id': case_id, 'status': 'review' if has_findings else 'ok', **result}


def _fact_state(fact):
    missing = fact['first_missing']
    misplaced = fact.get('first_misplaced')
    for stage in ('source', 'document', 'pptx'):
        if missing == stage:
            return f'missing:{stage}'
        if misplaced == stage:
            return f'misplaced:{stage}'
    return 'present'


def _compare_case(baseline, current):
    comparison = {'baseline_status': baseline['status']}
    if baseline['status'] == 'error' or current['status'] == 'error':
        comparison['status'] = 'unavailable'
        if baseline['status'] == 'error':
            comparison['baseline_error'] = {
                key: value for key, value in baseline.items() if key in ('error_type', 'stage')
            }
        return comparison

    before_facts = {fact['id']: _fact_state(fact) for fact in baseline.get('facts', [])}
    fact_changes = []
    for fact in current.get('facts', []):
        before = before_facts[fact['id']]
        after = _fact_state(fact)
        if before == after:
            continue
        direction = 'changed'
        if after == 'present':
            direction = 'improvement'
        elif before == 'present':
            direction = 'regression'
        fact_changes.append({'id': fact['id'], 'before': before, 'after': after,
                             'direction': direction})

    before_forbidden = baseline['forbidden_matches'].keys()
    after_forbidden = current['forbidden_matches'].keys()
    comparison.update(
        status='compared',
        baseline_actual_slides=baseline['actual_slides'],
        fact_changes=fact_changes,
        new_forbidden=sorted(after_forbidden - before_forbidden),
        resolved_forbidden=sorted(before_forbidden - after_forbidden),
    )
    if 'geometry' in baseline:
        comparison['geometry_issue_counts'] = {
            'before': len(baseline['geometry']['issues']),
            'after': len(current['geometry']['issues']),
        }
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True,
                        help='JSON cases with id, slideCount and optional text fragments')
    parser.add_argument('--pptx-dir', type=Path, required=True,
                        help='Directory containing one <id>.pptx per case')
    parser.add_argument('--source-dir', type=Path,
                        help='Directory containing extracted SourceDocument <id>.json snapshots')
    parser.add_argument('--document-dir', type=Path,
                        help='Directory containing generated presentation <id>.json snapshots')
    parser.add_argument('--baseline-pptx-dir', type=Path,
                        help='Optional directory containing the previous exports with the same IDs')
    parser.add_argument('--baseline-document-dir', type=Path,
                        help='Directory containing the previous generated presentation snapshots')
    parser.add_argument('--output', type=Path, required=True, help='JSON report file')
    args = parser.parse_args(argv)

    cases = json.loads(args.cases.read_text(encoding='utf-8'))
    ids = [case['id'] for case in cases]
    if not ids or len({value.casefold() for value in ids}) != len(ids):
        parser.error('Cases must have unique IDs and contain at least one item')
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value) for value in ids):
        parser.error('Case IDs may contain letters, digits, hyphens and underscores')

    snapshot_checks = ('facts', 'charts', 'chart_coverage')
    needs_snapshots = any(case.get(key) for case in cases for key in snapshot_checks)
    if needs_snapshots and not (args.source_dir and args.document_dir):
        parser.error('Cases with facts or charts require --source-dir and --document-dir')
    if args.baseline_document_dir and not args.baseline_pptx_dir:
        parser.error('--baseline-document-dir requires --baseline-pptx-dir')
    if args.baseline_pptx_dir and needs_snapshots and not args.baseline_document_dir:
        parser.error('Comparing cases with facts or charts requires --baseline-document-dir')

    report = [_inspect_case(case, args) for case in cases]
    if args.baseline_pptx_dir:
        baseline_args = argparse.Namespace(
            pptx_dir=args.baseline_pptx_dir,
            document_dir=args.baseline_document_dir,
            source_dir=args.source_dir,
        )
        for case, current in zip(cases, report, strict=True):
            current['comparison'] = _compare_case(_inspect_case(case, baseline_args), current)

    contents = json.dumps(report, ensure_ascii=False, indent=2)
    args.output.write_text(contents + '\n', encoding='utf-8')
    return int(any(
        case['status'] != 'ok' or case.get('comparison', {}).get('status') == 'unavailable'
        for case in report
    ))


if __name__ == '__main__':
    raise SystemExit(main())
