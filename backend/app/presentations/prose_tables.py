"""Read parallel measurements from prose while keeping their reported units and scope."""

import re

from .source_blocks import MAX_SOURCE_TEXT, SourceDocument, TableBlock, TextBlock, source_text


_NUMBER = r'[+−-]?(?:\d{1,3}(?:[ \u00a0\u202f.,]\d{3})+|\d+)(?:[.,]\d+)?'
_UNIT = r'(?P<unit>[^(),;:\n]{1,64})'
_SCOPE = r'(?P<scope>[^()%:;\n]{3,110}?)'
_SHARE = r'(?P<share>\d{1,3}(?:[.,]\d+)?)[ \u00a0\u202f]*%'
_ITEM = re.compile(
    rf'\s*(?P<label>[^(),;:\n]{{2,72}}?)\s+[–—-]\s+'
    rf'(?P<value>{_NUMBER})\s+{_UNIT}\s*\(\s*{_SCOPE}\s+[–—-]\s+{_SHARE}\s*\)',
)
_SEPARATOR = re.compile(r'\s*(?:[,;]\s*(?:(?:и|and)\s+)?|\s+(?:и|and)\s+)')
_TOTAL = re.compile(
    rf'\b(?:общее число|всего|total)\b[^:!?\n]{{0,159}}?\s+'
    rf'(?P<value>{_NUMBER})\s+{_UNIT}\s*,\s*(?:из них|of which)\s+'
    rf'{_SCOPE}\s+[–—-]\s+{_SHARE}(?:[.!?]|$)',
    re.I,
)
_BREAKDOWN = re.compile(r'\b(?:распредел\w*|разбивк\w*|в том числе|breakdown|broken down)\b', re.I)
_CYRILLIC = re.compile(r'[а-яё]', re.I)


def _words(value: str) -> str:
    return ' '.join(value.split())


def _read_rows(text: str, start: int) -> list[re.Match]:
    matches = []
    while match := _ITEM.match(text, start):
        matches.append(match)
        end = match.end()
        if end == len(text) or text[end:].lstrip().startswith(('.', '!', '?')):
            return matches
        separator = _SEPARATOR.match(text, end)
        if separator is None or len(matches) == 8:
            return []
        start = separator.end()
    return []


def _total_row(before: str, unit: str, scope: str, label: str) -> tuple[str, str, str] | None:
    matches = list(_TOTAL.finditer(before[-650:]))
    if not matches:
        return None
    last = matches[-1]
    context = before[-650:][last.end():]
    if (len(context) > 130 or not _BREAKDOWN.search(context)
            or _words(last['unit']) != unit
            or _words(last['scope']).casefold() != scope.casefold()):
        return None
    return label, _words(last['value']), last['share'] + '%'


def parallel_count_table(text: str) -> tuple[tuple[str, ...], ...] | None:
    """Accept one complete enumeration with the same measurement and share basis."""
    for colon in re.finditer(':', text):
        matches = _read_rows(text, colon.end())
        if len(matches) < 2:
            continue
        labels = [_words(item['label']) for item in matches]
        units = {_words(item['unit']) for item in matches}
        scopes = {_words(item['scope']).casefold() for item in matches}
        if len(set(label.casefold() for label in labels)) != len(labels) or len(units) != 1 or len(scopes) != 1:
            continue
        unit = _words(matches[0]['unit'])
        scope = _words(matches[0]['scope'])
        native = bool(_CYRILLIC.search(scope))
        header = ('Группа', f'Значение, {unit}', f'Доля ({scope})') if native else (
            'Group', f'Value, {unit}', f'Share ({scope})',
        )
        rows = tuple((label, _words(item['value']), item['share'] + '%')
                     for label, item in zip(labels, matches, strict=True))
        total = _total_row(text[:colon.start()], unit, scope, 'Всего' if native else 'Total')
        return (header, *rows, total) if total else (header, *rows)
    return None


def with_parallel_tables(source: SourceDocument) -> SourceDocument:
    """Expose tables alongside their source paragraphs within the input budget."""
    available = MAX_SOURCE_TEXT - len(source_text(source).encode('utf-16-le')) // 2
    identifiers = {block.id for block in source.blocks}
    additions = []
    for block in source.blocks:
        if not isinstance(block, TextBlock):
            continue
        paragraphs = re.split(r'\r?\n[ \t]*\r?\n+', block.text)
        for index, paragraph in enumerate(paragraphs, 1):
            identifier = f'{block.id[:100]}-table-{index}'
            if identifier in identifiers or len(source.blocks) + len(additions) >= 10_000:
                continue
            rows = parallel_count_table(paragraph)
            if not rows:
                continue
            table = TableBlock(identifier, rows, block.page, comparable=False, caption=' · '.join(rows[0][1:]))
            size = 2 + len(source_text(SourceDocument((table,))).encode('utf-16-le')) // 2
            if size <= available:
                additions.append(table)
                identifiers.add(identifier)
                available -= size
    return SourceDocument((*source.blocks, *additions)) if additions else source
