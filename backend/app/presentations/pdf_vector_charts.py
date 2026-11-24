"""Read printed data from captioned PDF bar charts with a vector text layer."""

from bisect import bisect_right
from collections import Counter
from itertools import pairwise
import re
from statistics import median


_FIGURE = re.compile(r'^\s*(?:рисунок|figure)\s+(\d+(?:\.\d+)+[а-яa-z]?)\s*[–—-]\s*', re.I)
_YEAR = re.compile(r'(?:19|20)\d{2}')
_NUMBER = re.compile(r'\d+(?:[.,]\d+)?%?')


def chart_caption_number(caption):
    match = _FIGURE.match(caption)
    return match[1].casefold() if match else None


def _box(item):
    return tuple(item[key] for key in ('x0', 'top', 'x1', 'bottom'))


def _inside(item, box):
    x0, top, x1, bottom = _box(item)
    return box[0] <= x0 <= x1 <= box[2] and box[1] <= top <= bottom <= box[3]


def _x(item):
    return (item['x0'] + item['x1']) / 2


def _y(item):
    return (item['top'] + item['bottom']) / 2


def _frame_caption(page, frame):
    x0, _, x1, bottom = frame
    above = min(page.bbox[3], bottom + 34)
    if bottom >= above:
        return None
    bounds = max(page.bbox[0], x0 - 28), bottom, min(page.bbox[2], x1 + 28), above
    lines = page.crop(bounds).extract_text_lines()
    if not lines or lines[0]['top'] - bottom > 13:
        return None
    first = lines[0]
    match = _FIGURE.match(first['text'])
    if match is None:
        return None
    # A wrapped caption stays close to its first line and uses the same body size.
    ends = [first]
    if len(lines) > 1 and lines[1]['top'] - first['bottom'] <= 5:
        ends.append(lines[1])
    caption = ' '.join(line['text'].strip() for line in ends)
    return match[1], caption, ends[-1]['bottom']


def _chart_values(words, bars, legend, years, baseline):
    boundaries = [(left + right) / 2 for left, right in pairwise(_x(year) for year in years)]
    candidates = [word for word in words if word['bottom'] <= baseline + 1
                  and _NUMBER.fullmatch(word['text'])]
    stacked = any(abs(bar['bottom'] - baseline) > 2 for bar in bars)
    readings = {}
    ratios = []
    claimed = set()
    for bar in bars:
        height = bar['height']
        top = bar['top']
        expected = (_y(bar) if height > 10 else top) if stacked else top - 5
        nearby = [(abs(_y(word) - expected), index, word) for index, word in enumerate(candidates)
                  if abs(_x(word) - _x(bar)) <= max(4, bar['width'] * 0.25)
                  and abs(_y(word) - expected) <= (max(8, height * 0.23) if stacked else 8)]
        if not nearby:
            return None
        _, index, word = min(nearby, key=lambda candidate: candidate[:2])
        value = word['text'].rstrip('%')
        measure = float(value.replace(',', '.'))
        key = bar['non_stroking_color'], bisect_right(boundaries, _x(bar))
        if not measure or index in claimed or key in readings:
            return None
        claimed.add(index)
        readings[key] = value
        ratios.append(height / measure)
    # All bars must use one scale. This rejects swapped labels and unsupported axes.
    scale = median(ratios)
    if any(abs(ratio - scale) > max(0.07 * scale, 0.025) for ratio in ratios):
        return None
    return [
        [readings.get((marker['non_stroking_color'], period)) for period in range(len(years))]
        for marker in legend
    ]


def _filled_shapes(shapes):
    for shape in shapes:
        if not shape['fill']:
            continue
        paint = shape['non_stroking_color']
        if isinstance(paint, (int, float)):
            paint = (paint,)
        if (not isinstance(paint, (tuple, list)) or len(paint) not in (1, 3, 4)
                or any(not isinstance(channel, (int, float)) or not 0 <= channel <= 1 for channel in paint)):
            continue
        white_score = 1 - max(paint) if len(paint) == 4 else min(paint)
        yield {**shape, 'non_stroking_color': tuple(paint), 'white_score': white_score}


def _bar_chart_rows(page, bounds, rects, objects, caption):
    bars = [bar for bar in rects if bar['width'] >= 12 and bar['height'] >= 2
            and bar['white_score'] < 0.94 and _inside(bar, bounds)]
    counts = Counter(bar['non_stroking_color'] for bar in bars)
    if not 2 <= len(counts) <= 6 or len(set(counts.values())) != 1:
        return None
    baseline = max(bar['bottom'] for bar in bars)
    legend = sorted((item for item in objects if _inside(item, bounds)
                     and item['top'] > baseline and 2 <= item['width'] <= 12
                     and 2 <= item['height'] <= 12 and item['non_stroking_color'] in counts), key=_x)
    if len(legend) != len(counts) or len({m['non_stroking_color'] for m in legend}) != len(counts):
        return None
    legend_top = min(marker['top'] for marker in legend)
    words = page.crop(bounds).extract_words(x_tolerance=1.5, y_tolerance=2)
    years = sorted((word for word in words if baseline <= _y(word) <= legend_top
                    and _YEAR.fullmatch(word['text'])), key=_x)
    labels = [word['text'] for word in years]
    if not 2 <= len(labels) <= 8 or len(labels) != next(iter(counts.values())):
        return None
    if labels != sorted(set(labels)):
        return None
    values = _chart_values(words, bars, legend, years, baseline)
    if values is None or any(None in row for row in values):
        return None
    marker_limits = [marker['x0'] for marker in legend[1:]] + [bounds[2]]
    groups = []
    for marker, right in zip(legend, marker_limits, strict=True):
        left = marker['x1']
        top = max(bounds[1], marker['top'] - 4)
        bottom = min(bounds[3], marker['bottom'] + 5)
        if left >= right or top >= bottom:
            return None
        name = ' '.join(page.crop((left, top, right, bottom)).extract_text().split())
        groups.append(name)
    if not all(groups) or len(set(groups)) != len(groups):
        return None
    unit = '%' if '%' in caption else ''
    metric = _FIGURE.sub('', caption, count=1)
    return (('Категория', metric, *[None] * (len(labels) - 1)), (None, *labels),
            *((name, *(value + unit for value in row)) for name, row in zip(groups, values, strict=True)))


def read_vector_bar_charts(page):
    """Yield chart bounds, caption and a source table only when all labels are recovered."""
    rects = list(_filled_shapes(page.rects))
    objects = [*rects, *_filled_shapes(page.curves)]
    for frame in objects:
        if frame['white_score'] <= 0.97 or frame['width'] < 160 or frame['height'] < 60:
            continue
        bounds = _box(frame)
        if not _inside(frame, page.bbox) or (captioned := _frame_caption(page, bounds)) is None:
            continue
        number, caption, bottom = captioned
        if rows := _bar_chart_rows(page, bounds, rects, objects, caption):
            yield (*bounds[:3], bottom), number, caption, rows
