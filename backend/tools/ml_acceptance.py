"""Opt-in, sequential synthetic ML baseline with reusable results and review hints."""

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.presentations.schemas import normalize_document

CASES = Path(__file__).resolve().parents[1] / 'tests/fixtures/ml_quality_cases.json'


@contextmanager
def capture_candidate(path):
    """Opt-in private diagnostic for this sequential synthetic CLI, never server logs."""
    import presentation_ml

    original = presentation_ml.request_document

    def request(**kwargs):
        result = original(**kwargs)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    presentation_ml.request_document = request
    try:
        yield
    finally:
        presentation_ml.request_document = original


def safe_error_details(exc):
    """Classify connection failures without storing URLs, payloads or exception text."""
    chain = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return {
        'error_type': type(exc).__name__,
        'cause_types': [type(error).__name__ for error in chain[1:]],
        'tls_verification_error': any('CERTIFICATE_VERIFY_FAILED' in str(error)
                                      for error in chain),
    }


def inspect_document(document, case):
    normalized = normalize_document(document, generation=True, max_bytes=8_000_000)
    fragments = []
    long_slides = []
    for number, slide in enumerate(normalized['slides'], 1):
        visible = [slide['title']]
        content = []
        for key in ('body', 'subtitle', 'caption', 'leftTitle', 'rightTitle'):
            if slide.get(key):
                content.append(slide[key])
        for key in ('bullets', 'left', 'right'):
            content.extend(slide.get(key, []))
        visible.extend(content)
        if sum(len(value) for value in visible) > 800:
            long_slides.append(number)
        if slide['layout'] not in ('title', 'closing'):
            fragments.extend(content)
    all_visible = '\n'.join(
        str(value) for slide in normalized['slides'] for key, value in slide.items()
        if key not in ('id', 'layout', 'notes')
    ).casefold()
    repeated = Counter(' '.join(t.split()) for t in fragments if t.strip())
    return {
        'contract_valid': True,
        'actual_slides': len(normalized['slides']),
        'slide_count_delta': len(normalized['slides']) - case['slideCount'],
        'missing_anchors': [a for a in case.get('anchors', []) if a.casefold() not in all_visible],
        'forbidden_fragments': [a for a in case.get('forbidden_fragments', [])
                                if a.casefold() in all_visible],
        'repeated_content': [text for text, count in repeated.items() if count > 1],
        'long_slide_numbers': long_slides,
        'human_review_required': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly allow paid provider calls')
    parser.add_argument('--output', type=Path, required=True,
                        help='Private result directory, preferably outside the repository')
    parser.add_argument('--case', action='append', dest='case_ids')
    parser.add_argument('--save-candidates', action='store_true',
                        help='Privately save raw model JSON; only for explicitly synthetic cases')
    args = parser.parse_args()
    if args.live and not args.case_ids:
        parser.error('--live requires explicit --case selections to bound provider usage')
    from presentation_ml.prompts import build_generation_prompt, get_prompt_version

    profile = {
        'provider': os.getenv('PM_ML_PROVIDER', 'gigachat'),
        'model': os.getenv('GIGACHAT_MODEL', ''),
        'scope': os.getenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS'),
        'prompt_version': get_prompt_version(),
        'prompt_sha256': hashlib.sha256(build_generation_prompt().encode()).hexdigest(),
        'generation_policy': 'total-slide-budget-v2-adjacent-verbatim-pack',
        'normalization_policy': 'document-cover-title-closing-heading-join-v5',
        'source_sections_policy': ('headings-v1' if get_prompt_version() in ('v5', 'v6', 'v7')
                                   else 'none'),
        'grounding_policy': 'source-quotes-v1' if get_prompt_version() == 'v7' else 'none',
    }
    cases = json.loads(CASES.read_text(encoding='utf-8'))
    if args.case_ids:
        known = {c['id'] for c in cases}
        if set(args.case_ids) - known:
            parser.error('Unknown case ID')
        cases = [c for c in cases if c['id'] in args.case_ids]
    if args.save_candidates and any(case.get('synthetic') is not True for case in cases):
        parser.error('--save-candidates requires synthetic=true for every selected case')
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        fingerprint = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()
        target = args.output / (case['id'] + '.json')
        if target.exists():
            saved = json.loads(target.read_text(encoding='utf-8'))
            if saved.get('source_hash') != fingerprint:
                raise RuntimeError('Cached input changed; choose a new result directory')
            if saved.get('status') != 'ok':
                raise RuntimeError('Prior attempt failed; choose a new directory to retry')
            if args.live and saved['report'].get('generation_profile') != profile:
                raise RuntimeError('Generation profile changed; choose a new result directory')
            report = dict(inspect_document(saved['document'], case), status='ok', cached=True,
                          seconds=saved['report'].get('seconds'),
                          model=saved['report'].get('model'),
                          generation_profile=saved['report'].get('generation_profile'))
        elif not args.live:
            report = {'status': 'not_run', 'cached': False}
        else:
            from presentation_ml import generate

            # Write intent first: interruption must not silently cause a paid repeat.
            target.write_text(json.dumps({'status': 'started', 'source_hash': fingerprint}),
                              encoding='utf-8')
            start = time.monotonic()
            try:
                from contextlib import nullcontext

                capture = (capture_candidate(target.with_suffix('.candidate.json'))
                           if args.save_candidates else nullcontext())
                with capture:
                    document = generate(
                        text=case['text'], title=case.get('title'), slideCount=case['slideCount'],
                        job_id=str(uuid4()),
                        deadline=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                    )
                report = dict(inspect_document(document, case), status='ok', cached=False,
                              seconds=round(time.monotonic() - start, 2),
                              model=os.getenv('GIGACHAT_MODEL', ''), generation_profile=profile)
                saved = {'status': 'ok', 'source_hash': fingerprint, 'report': report,
                         'document': document}
            except Exception as exc:
                report = {'status': 'error', **safe_error_details(exc), 'cached': False,
                          'seconds': round(time.monotonic() - start, 2),
                          'generation_profile': profile,
                          'candidate_saved': target.with_suffix('.candidate.json').is_file()}
                saved = {'status': 'error', 'source_hash': fingerprint, 'report': report}
            target.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
        results.append({'id': case['id'], **report})
        print(json.dumps({
            'id': case['id'], 'status': report['status'], 'cached': report['cached'],
            'seconds': report.get('seconds'), 'actual_slides': report.get('actual_slides'),
            'missing_anchor_count': len(report.get('missing_anchors', [])),
            'repeated_fragment_count': len(report.get('repeated_content', [])),
            'forbidden_fragment_count': len(report.get('forbidden_fragments', [])),
        }), flush=True)
    (args.output / 'summary.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(r['status'] == 'error' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
