"""Find numbered display equations without reconstructing the math from text."""

from itertools import pairwise
import re


_TAG = re.compile(r'\(([1-9]\d{0,2})\)')
_MATH_FONT = re.compile(r'(?:^|\+)(?:CMMI|CMSY|CMEX|STIX.*Math|CambriaMath)', re.I)
_ROMAN_MATH = re.compile(r'(?:^|\+)CM(?:R|BX)\d', re.I)
_OPERATOR = re.compile(r'[=≈∝≠→∑∫≤≥]')
_PROSE_WORD = re.compile(r'[^\W\d_]{4,}')


def _math_run(glyphs, height):
    splits = [
        index for index, (left, right) in enumerate(pairwise(glyphs), 1)
        if right['x0'] - left['x1'] >= height * 2
    ]
    for start in reversed([0, *splits]):
        run = glyphs[start:]
        words = ''.join(
            char['text'] + (' ' if following['x0'] - char['x1'] > height * 0.25 else '')
            for char, following in pairwise(run)
        ) + run[-1]['text']
        prose = len(_PROSE_WORD.findall(words))
        math = sum(bool(_MATH_FONT.search(char['fontname'])) for char in run)
        operator = _OPERATOR.search(words)
        math_dominates = math >= 8 and math * 2 > len(run)
        if (math >= 4 and prose <= 2) or (operator and (not prose or math_dominates)):
            return run
    return ()


def numbered_equations(page):
    """Yield the number and crop for isolated math preceding an equation tag."""
    glyphs = [char for char in page.chars if char['upright'] and char['text'].strip()]
    px0, ptop, px1, pbottom = page.bbox
    for tag in page.search(_TAG, return_chars=False):
        height = tag['bottom'] - tag['top']
        if height <= 0 or tag['x1'] < px0 + (px1 - px0) * 0.43:
            continue
        same_line = sorted(
            (char for char in glyphs if char['x1'] <= tag['x0']
             and tag['top'] <= (char['top'] + char['bottom']) / 2 <= tag['bottom']),
            key=lambda char: char['x0'],
        )
        if not same_line or tag['x0'] - same_line[-1]['x1'] < height * 1.3:
            continue
        if not (body := _math_run(same_line, height)):
            continue
        left, right = body[0]['x0'], max(char['x1'] for char in body)
        # Superscripts, subscripts and the ends of fractions can sit beyond the baseline.
        nearby = [
            char for char in glyphs
            if left - 5 <= char['x0'] and char['x1'] <= right + 5
            and tag['top'] - height * 0.75 <= (char['top'] + char['bottom']) / 2
            <= tag['bottom'] + height * 0.75
            and (_MATH_FONT.search(char['fontname']) or _ROMAN_MATH.search(char['fontname']))
        ]
        crop = (
            max(px0, min(char['x0'] for char in (*body, *nearby)) - 4),
            max(ptop, min(tag['top'], *(char['top'] for char in (*body, *nearby))) - 2),
            min(px1, tag['x1'] + 4),
            min(pbottom, max(tag['bottom'], *(char['bottom'] for char in (*body, *nearby))) + 2),
        )
        yield tag['groups'][0], crop
