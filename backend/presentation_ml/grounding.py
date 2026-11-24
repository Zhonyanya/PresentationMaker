"""Check literal source evidence; this is not a semantic entailment judge."""

import copy
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

_CLAUSE_BOUNDARY = re.compile(r'([.!?;](?=\s|$)|\r?\n+)')
_PERCENTAGE = re.compile(
    r'(?<![\w+\-−.])(?P<value>\d{1,3}(?:[.,]\d+)?)\s*'
    r'(?:%|процент(?:ами|ах|ов|а|е)?\b|percent\b)\s+'
    r'(?:of\s+(?:the\s+)?)?(?P<base>[^\W\d_]{3,})\b',
    re.IGNORECASE,
)
_SCOPE = re.compile(
    r'(?:с|со|без|для|из|в|во|на|по|у|with|without|among|at|in|from|within)'
    r'(?:\s+[^\W\d_]+(?:-[^\W\d_]+)?){1,5}',
    re.IGNORECASE,
)
_CHANGE_MODIFIER = re.compile(r'\b(?:на|by)\s*$', re.IGNORECASE)
_NEGATION = re.compile(r'\b(?:не|нет|not|never)\b', re.IGNORECASE)
_CONTEXT_WORD = re.compile(r'\b(?:[А-ЯЁа-яё]{5,}|[A-Za-z]{5,})\b')
_PREFIXED_UNIT = re.compile(
    r'(?<=\d)[ \t\u00a0\u202f]+(?P<unit>(?:[kMGmµкМГм])?'
    r'(?P<base>Вт·ч|Wh|Вт|Дж|Па|W|J|Pa|Hz|Гц))(?![\w·])',
)
_REPORT_CONTEXT = {'pilot', 'project', 'report', 'results', 'study', 'пилотн', 'проект', 'отчета'}


def _percentage_key(match: re.Match[str]) -> tuple[str, str]:
    # Canonical decimal spelling without losing precision to a float conversion.
    whole, _, fraction = match['value'].replace(',', '.').partition('.')
    decimal = fraction.rstrip('0')
    value = str(int(whole)) + ('.' + decimal if decimal else '')
    return value, match['base'].casefold()


def _context_words(value: str) -> set[str]:
    return {
        word if word.isascii() else word[:6].replace('ё', 'е')
        for word in _CONTEXT_WORD.findall(value.casefold())
    }


def _unit_address(clause, match):
    # Keep the entire claim including signs, denominator, and every other value.
    return (' '.join(clause[:match.start('unit')].split()), match['base'],
            ' '.join(clause[match.end('unit'):].split()))


_DENOMINATOR = re.compile(r'\s*(?:/|на\s+|per\s+)(\d[\d \u00a0\u202f]*)\s+([^\W\d_]+)', re.I)
_END_VALUE = re.compile(r'(?<![\d.,])([+−-]?\d+(?:[.,]\d+)?)\s*$')


def _rate_address(clause, match):
    denominator = _DENOMINATOR.match(clause, match.end('unit'))
    value = _END_VALUE.search(clause[:match.start('unit')])
    if not denominator or not value:
        return None
    return (value[1].replace(',', '.'), match['base'],
            ''.join(denominator[1].split()), denominator[2].casefold())


def restore_percentage_scopes(
    document: dict, paragraphs: Iterable[tuple[str, str]], *,
    cited_blocks: dict[str, set[str]] | None = None, include_percentage_scopes: bool = True,
) -> None:
    """Restore omitted scopes and confirm unit prefixes against matching source claims."""
    evidence = defaultdict(list)
    units = defaultdict(set)
    rates = defaultdict(list)
    paragraphs = list(paragraphs)
    for index, (block_id, paragraph) in enumerate(paragraphs):
        following = paragraphs[index + 1][1] if index + 1 < len(paragraphs) else ''
        continuation = (' ' + following.split()[0] if following[:1].islower() else '')
        for clause in _CLAUSE_BOUNDARY.split(paragraph):
            for match in _PREFIXED_UNIT.finditer(clause):
                units[_unit_address(clause, match)].add((match['unit'], block_id))
                key = _rate_address(clause, match)
                if key is None and paragraph.endswith(clause) and re.fullmatch(
                        r'\s*(?:/|на\s+|per\s+)\d[\d \u00a0\u202f]*', clause[match.end('unit'):], re.I):
                    key = _rate_address(clause + continuation, match)
                if key:
                    rates[key].append((match['unit'], block_id, _context_words(clause[:match.start()])))
            for match in _PERCENTAGE.finditer(clause) if include_percentage_scopes else ():
                scope = ' '.join(clause[match.end():].split())
                context = clause[:match.start()]
                # Unqualified occurrences count for ambiguity too.
                if not _SCOPE.fullmatch(scope) or _CHANGE_MODIFIER.search(context) \
                        or _NEGATION.search(context):
                    scope = ''
                key = _percentage_key(match)
                evidence[key].append((scope, _context_words(context), block_id))

    def restore(value: str, maximum: int, allowed_blocks: set[str] | None) -> str:
        clauses = _CLAUSE_BOUNDARY.split(value)
        for index in range(0, len(clauses), 2):
            clause = clauses[index]
            for match in reversed(list(_PREFIXED_UNIT.finditer(clause))):
                options = {unit for unit, block in units.get(_unit_address(clause, match), ())
                           if allowed_blocks is None or block in allowed_blocks}
                if not options and (key := _rate_address(clause, match)):
                    context = _context_words(clause[:match.start()]) - _REPORT_CONTEXT
                    candidates = [(unit, words) for unit, block, words in rates.get(key, ())
                                  if allowed_blocks is None or block in allowed_blocks]
                    if any(context & words for _, words in candidates):
                        options = {unit for unit, _ in candidates}
                if len(options) == 1:
                    clause = clause[:match.start('unit')] + next(iter(options)) + clause[match.end('unit'):]
            clauses[index] = clause
            matches = list(_PERCENTAGE.finditer(clause))
            if len(matches) != 1:
                continue
            (match,) = matches
            context = clause[:match.start()]
            if (clause[match.end():].strip() or _CHANGE_MODIFIER.search(context)
                    or _NEGATION.search(context)):
                continue
            candidates = evidence.get(_percentage_key(match), ())
            scopes = {scope for scope, _, _ in candidates}
            if len(scopes) != 1 or '' in scopes:
                continue
            (scope,) = scopes
            words = _context_words(context)
            if len(words - _REPORT_CONTEXT) >= 2 and any(
                words <= source_words and (allowed_blocks is None or block_id in allowed_blocks)
                for _, source_words, block_id in candidates
            ):
                clauses[index] = clause[:match.end()] + ' ' + scope + clause[match.end():]
        result = ''.join(clauses)
        return result if len(result.encode('utf-16-le')) // 2 <= maximum else value

    if not evidence and not units:
        return
    for slide in document['slides']:
        allowed_blocks = cited_blocks.get(slide['id'], set()) if cited_blocks is not None else None
        for field, maximum in (('body', 4000), ('subtitle', 400)):
            if slide.get(field):
                slide[field] = restore(slide[field], maximum, allowed_blocks)
        for field in ('bullets', 'left', 'right'):
            if slide.get(field):
                slide[field] = [restore(item, 1000, allowed_blocks) for item in slide[field]]


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
