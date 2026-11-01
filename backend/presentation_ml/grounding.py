"""Check literal source evidence; this is not a semantic entailment judge."""

import copy


def attach_source_quotes(candidate, text):
    if not isinstance(candidate, dict) or not isinstance(candidate.get('slides'), list):
        raise ValueError('Invalid source quote document')
    source = ' '.join(text.split())
    result = copy.deepcopy(candidate)
    for slide in result['slides']:
        if not isinstance(slide, dict):
            raise ValueError('Invalid source quote slide')
        quotes = slide.pop('source_quotes', None)
        if (not isinstance(quotes, list) or len(quotes) > 6
                or (slide.get('layout') not in ('title', 'closing') and not quotes)):
            raise ValueError('Missing source quote evidence')
        for quote in quotes:
            if not isinstance(quote, str):
                raise ValueError('Invalid source quote evidence')
            normalized = ' '.join(quote.split())
            if not 20 <= len(normalized) <= 800 or len(quote) > 800 or normalized not in source:
                raise ValueError('Invalid source quote evidence')
        if quotes:
            notes = slide.get('notes', '')
            if not isinstance(notes, str):
                raise ValueError('Invalid source quote notes')
            additions = [q for q in quotes if q not in notes]
            slide['notes'] = '\n\n'.join(part for part in (notes, *additions) if part)
    return result
