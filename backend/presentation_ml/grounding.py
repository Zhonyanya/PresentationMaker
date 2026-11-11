"""Check literal source evidence; this is not a semantic entailment judge."""

import copy
import re
from collections.abc import Iterable
from dataclasses import dataclass


def attach_source_quotes(candidate, text, *, page_passages=None):
    if not isinstance(candidate, dict) or not isinstance(candidate.get('slides'), list):
        raise ValueError('Invalid source quote document')
    sources = (
        [(None, ' '.join(text.split()))] if page_passages is None else
        [(p.page_number, ' '.join(p.text.split())) for p in page_passages]
    )
    result = copy.deepcopy(candidate)
    for slide in result['slides']:
        if not isinstance(slide, dict):
            raise ValueError('Invalid source quote slide')
        quotes = slide.pop('source_quotes', None)
        if (not isinstance(quotes, list) or len(quotes) > 6
                or (slide.get('layout') not in ('title', 'closing') and not quotes)):
            raise ValueError('Missing source quote evidence')
        citations = []
        for quote in quotes:
            if not isinstance(quote, str):
                raise ValueError('Invalid source quote evidence')
            normalized = ' '.join(quote.split())
            if not 20 <= len(normalized) <= 800 or len(quote) > 800:
                raise ValueError('Invalid source quote evidence')
            matches = [page for page, source in sources if normalized in source]
            if not matches:
                raise ValueError('Invalid source quote evidence')
            if page_passages is None:
                citations.append(quote)
            else:
                pages = ', '.join(str(page) for page in sorted(set(matches)))
                citations.append(f'Стр. {pages} — {quote}')
        if quotes:
            notes = slide.get('notes', '')
            if not isinstance(notes, str):
                raise ValueError('Invalid source quote notes')
            additions = [q for q in dict.fromkeys(citations) if q not in notes]
            slide['notes'] = '\n\n'.join(part for part in (notes, *additions) if part)
    return result


# Order matters: a name inside an explicit organization is part of that organization.
_ENTITY_PATTERN = re.compile(
    r'(?P<organization>\b(?:ООО|ПАО|АО|АНО|НКО|ФГБУ|ИП|ГАОУ|ГБОУ|МБОУ)'
    r'(?:[ \t]+[А-ЯЁ]{2,5}){0,2}\s+«[^»\n]{1,100}»)'
    r'|(?P<date>\b(?:0?[1-9]|[12]\d|3[01])[./](?:0?[1-9]|1[0-2])[./]\d{4}\b'
    r'|\b(?:[1-9]|[12]\d|3[01])\s+'
    r'(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)'
    r'\s+\d{4}(?:\s+года)?\b)'
    r'|(?P<person>\b[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}'
    r'(?:\s+[А-ЯЁ][а-яё]{2,})?\b)',
)


def recognize_entities(text):
    """Return candidate entity labels and literal spans in source order."""
    return [(match.lastgroup, match.group()) for match in _ENTITY_PATTERN.finditer(text)]


def _passage_score(passage):
    # Capitalized word pairs can also be headings or place names.
    entities = {
        (label, value.casefold()) for label, value in recognize_entities(passage)
        if label != 'person'
    }
    numbers = set(re.findall(r'\b\d+(?:[.,]\d+)?', passage))
    return len(entities), len(numbers)


def select_source_passages(text, limit=12):
    """Sample source sections in order, favoring passages with factual anchors."""
    passages = []
    for block in re.split(r'\n\s*\n', text):
        passage = ' '.join(block.split())
        if 20 <= len(passage) <= 800:
            passages.append(passage)
    if len(passages) <= limit:
        return passages

    selected = []
    for index in range(limit):
        start = index * len(passages) // limit
        end = (index + 1) * len(passages) // limit
        selected.append(max(
            passages[start:end],
            key=_passage_score,
        ))
    return selected


@dataclass(frozen=True)
class PagePassage:
    page_number: int
    text: str


_REPORT_OUTCOME = re.compile(
    r'\b(?:по итогам|в результате|результат[ыо]м?|вывод[ыа]?|'
    r'составил[аио]?|вырос(?:ла|ло|ли)?|снизил(?:ся|ась|ось|ись)|'
    r'увеличил(?:ся|ась|ось|ись)|достиг(?:нут[аоы]?|ла|ли)?)\b',
    re.IGNORECASE,
)
_LEGAL_REFERENCE = re.compile(
    r'^(?:в соответствии с|на основании|во исполнение)\b|'
    r'\b(?:постановление|приказ|распоряжение|федеральный закон)\b.*?№',
    re.IGNORECASE,
)


def _report_passage_score(text: str) -> tuple[bool, bool, int]:
    without_dates = _ENTITY_PATTERN.sub(
        lambda match: '' if match.lastgroup == 'date' else match.group(), text,
    )
    numbers = set(re.findall(r'\b\d+(?:[.,]\d+)?', without_dates))
    return bool(_REPORT_OUTCOME.search(text)), not _LEGAL_REFERENCE.search(text), len(numbers)


def select_page_passages(
    pages: Iterable[tuple[int, str]], *, limit: int = 12,
) -> list[PagePassage]:
    """Select literal excerpts across the report, retaining their source pages."""
    if limit < 1:
        raise ValueError('Passage limit must be positive')

    passages = []
    for number, text in pages:
        for block in re.split(r'\n\s*\n', text):
            passage = ' '.join(block.split())
            chunks = [passage] if len(passage) <= 800 else re.split(
                r'(?<=[.!?]) (?=[А-ЯЁA-Z])', passage,
            )
            passages.extend(
                PagePassage(number, chunk) for chunk in chunks if 20 <= len(chunk) <= 800
            )
    if len(passages) <= limit:
        return passages

    return [
        max(
            passages[index * len(passages) // limit:(index + 1) * len(passages) // limit],
            key=lambda passage: _report_passage_score(passage.text),
        )
        for index in range(limit)
    ]
