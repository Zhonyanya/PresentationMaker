"""Page-aware extraction for text-layer PDF reports."""

import re
from base64 import b64encode
from dataclasses import dataclass, replace
from io import BytesIO
from textwrap import TextWrapper
from typing import BinaryIO
from uuid import uuid4

import pdfplumber


@dataclass(frozen=True)
class SourceTable:
    bounds: tuple[float, float, float, float]
    rows: tuple[tuple[str | None, ...], ...]

    @property
    def has_tabular_content(self) -> bool:
        # PDF ruling lines can also surround prose. Require cells with text
        # side by side in more than one row before removing anything from prose.
        return sum(
            sum(bool(cell and cell.strip()) for cell in row) >= 2 for row in self.rows
        ) >= 2

    @property
    def fits_slide(self) -> bool:
        fits_contract = (
            self.has_complete_grid and len(self.rows) <= 10 and len(self.rows[0]) <= 8
            and all(
                len(cell.encode('utf-16-le')) <= 600
                for row in self.rows for cell in row if cell is not None
            )
        )
        if not fits_contract:
            return False

        # Match the default frontend content box and its minimum table font.
        content_width, content_height = 11.7333, 4.65  # inches
        font_size, padding = 9, 4  # points
        cell_width = content_width * 72 / len(self.rows[0]) - 2 * padding
        wrapper = TextWrapper(width=int(cell_width / (font_size * 0.53)), break_on_hyphens=False)
        row_lines = (
            max(
                sum(max(1, len(wrapper.wrap(line))) for line in (cell or '').split('\n'))
                for cell in row
            )
            for row in self.rows
        )
        height = sum(lines * font_size * 1.2 + 2 * padding for lines in row_lines)
        return height <= content_height * 72

    @property
    def has_complete_grid(self) -> bool:
        return (
            len(self.rows) >= 2
            and len(self.rows[0]) >= 2
            and all(
                len(row) == len(self.rows[0]) and all(cell is not None for cell in row)
                for row in self.rows
            )
        )

    def split_for_slides(self, limit: int) -> tuple["SourceTable", ...]:
        if self.fits_slide:
            return (self,)
        if limit < 2 or not self.has_complete_grid:
            return ()
        header, *body = self.rows
        if not all(cell and cell.strip() for cell in header):
            return ()

        parts = []
        rows = (header,)
        for row in body:
            candidate = replace(self, rows=(*rows, row))
            if candidate.fits_slide:
                rows = candidate.rows
                continue
            part = replace(self, rows=rows)
            if not part.fits_slide or len(parts) + 1 >= limit:
                return ()
            parts.append(part)
            rows = (header, row)
        last = replace(self, rows=rows)
        return (*parts, last) if last.fits_slide else ()


@dataclass(frozen=True)
class SourceFigure:
    bounds: tuple[float, float, float, float]
    reference: str


@dataclass(frozen=True)
class SourcePage:
    number: int
    text: str
    tables: tuple[SourceTable, ...]
    images: tuple[tuple[float, float, float, float], ...]
    figures: tuple[SourceFigure, ...] = ()


def _contains(outer, inner):
    x0, top, x1, bottom = outer
    ix0, itop, ix1, ibottom = inner
    return x0 <= ix0 <= ix1 <= x1 and top <= itop <= ibottom <= bottom


def _bounds(obj):
    return tuple(obj[key] for key in ('x0', 'top', 'x1', 'bottom'))


_CAPTION = re.compile(
    r'^[ \t]*((?:диаграмма|рисунок|рис\.|схема|график)[ \t]*(?:№[ \t]*)?\d+)\b[^\n]*',
    re.I | re.M,
)


def _captioned_figure(page, frame):
    x0, top, x1, bottom = frame
    px0, ptop, px1, pbottom = page.bbox
    left, right = max(px0, x0 - 12), min(px1, x1 + 12)
    above = max(ptop, top - 85)
    if above < top:
        matches = page.crop((left, above, right, top)).search(_CAPTION, return_chars=False)
        if matches:
            caption = matches[-1]
            return SourceFigure(
                (left, caption['top'], right, min(pbottom, bottom + 3)),
                _CAPTION.match(caption['text'])[1],
            )
    below = min(pbottom, bottom + 36)
    if bottom < below:
        matches = page.crop((left, bottom, right, below)).search(_CAPTION, return_chars=False)
        if matches:
            caption = matches[0]
            return SourceFigure(
                (left, max(ptop, top - 3), right, caption['bottom']),
                _CAPTION.match(caption['text'])[1],
            )
    return None


def _framed_figures(page):
    """Find captioned figures, including charts composed of raster layers."""
    figures = {}
    for rect in page.rects:
        if rect['width'] < 160 or rect['height'] < 60:
            continue
        frame = _bounds(rect)
        has_vectors = sum(_contains(frame, _bounds(curve)) for curve in page.curves) >= 8
        has_raster = any(
            image['width'] * image['height'] >= rect['width'] * rect['height'] / 4
            and _contains(frame, _bounds(image))
            for image in page.images
        )
        if not (has_vectors or has_raster):
            continue
        figure = _captioned_figure(page, frame)
        if figure:
            figures[tuple(round(value, 1) for value in figure.bounds)] = figure
    return tuple(figures.values())


def _page_illustrations(page, seen_images):
    figures = list(_framed_figures(page))
    images = []
    for image in page.images:
        bounds = _bounds(image)
        if min(image['width'], image['height']) < 32:
            continue
        if not _contains(page.bbox, bounds) or any(
            _contains(figure.bounds, bounds) for figure in figures
        ):
            continue
        figure = _captioned_figure(page, bounds)
        if figure:
            figures.append(figure)
            continue
        object_id = image['stream'].objid
        if object_id is None or object_id not in seen_images:
            images.append(bounds)
            if object_id is not None:
                seen_images.add(object_id)
    return tuple(figures), tuple(images)


def read_pdf(source: BinaryIO, *, max_pages: int = 250) -> tuple[SourcePage, ...]:
    """Extract positioned materials without flattening table cells into prose."""
    result = []
    seen_images = set()
    with pdfplumber.open(source) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError('PDF exceeds the page limit')
        for page in pdf.pages:
            candidates = (
                SourceTable(table.bbox, tuple(tuple(row) for row in table.extract()))
                for table in page.find_tables()
                if len(table.rows) >= 2 and len(table.columns) >= 2
            )
            tables = tuple(table for table in candidates if table.has_tabular_content)
            figures, images = _page_illustrations(page, seen_images)
            excluded = (*[table.bounds for table in tables], *(figure.bounds for figure in figures))
            prose = page.filter(
                lambda obj, excluded=excluded: obj['object_type'] != 'char' or not any(
                    x0 <= (obj['x0'] + obj['x1']) / 2 <= x1
                    and top <= (obj['top'] + obj['bottom']) / 2 <= bottom
                    for x0, top, x1, bottom in excluded
                ),
            )
            result.append(SourcePage(
                page.page_number, prose.extract_text(), tables, images, figures,
            ))
            page.close()
    return tuple(result)


def render_pdf_region(
    source: BinaryIO,
    page_number: int,
    bounds: tuple[float, float, float, float],
) -> bytes:
    """Render a source area as PNG, preserving its appearance for slide placement."""
    with pdfplumber.open(source) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise ValueError('PDF page does not exist')
        page = pdf.pages[page_number - 1]
        x0, top, x1, bottom = bounds
        px0, ptop, px1, pbottom = page.bbox
        if not (px0 <= x0 < x1 <= px1 and ptop <= top < bottom <= pbottom):
            raise ValueError('PDF region is outside the page')
        # Limit the longest rendered edge to bound memory use for oversized pages.
        resolution = min(144, 72 * 1800 / max(page.width, page.height))
        image = page.crop(bounds).to_image(resolution=resolution)
        output = BytesIO()
        image.save(output, format='PNG', quantize=False)
        return output.getvalue()


def source_material_slide(
    source: BinaryIO, page: SourcePage, *, table_index: int | None = None,
    image_index: int | None = None, figure_index: int | None = None,
) -> dict:
    """Build a source slide, retaining native cells where the grid fits."""
    if sum(index is not None for index in (table_index, image_index, figure_index)) != 1:
        raise ValueError('Select one source material')
    body = ''
    if table_index is not None:
        table = page.tables[table_index]
        rows = table.rows
        if table.fits_slide:
            material = {'kind': 'table', 'rows': [list(row) for row in rows]}
        else:
            material = _image_material(source, page.number, table.bounds)
        title = f'Таблица · стр. {page.number}'
    elif figure_index is not None:
        figure = page.figures[figure_index]
        material = _image_material(source, page.number, figure.bounds)
        title = f'{figure.reference} · стр. {page.number}'
        prose = re.sub(rf'^\s*{page.number}[ \t]*\r?\n', '', page.text)
        body = _figure_context(prose, figure.reference)
    else:
        material = _image_material(source, page.number, page.images[image_index])
        title = f'Иллюстрация · стр. {page.number}'
    return {
        'id': str(uuid4()), 'layout': 'text', 'title': title, 'body': body,
        'sourceMaterial': {**material, 'page': page.number},
    }


def _figure_context(text: str, reference: str) -> str:
    kind, number = re.fullmatch(r'(.+?)[ \t]*(?:№[ \t]*)?(\d+)', reference).groups()
    variants = {
        'диаграмма': r'диаграмм[а-яё]*', 'рисунок': r'рисун(?:ок|к[а-яё]*)|рис\.',
        'рис.': r'рисун(?:ок|к[а-яё]*)|рис\.', 'схема': r'схем[а-яё]*', 'график': r'график[а-яё]*',
    }
    mention = re.compile(rf'\b(?:{variants[kind.casefold()]})\s*(?:№\s*)?{number}\b', re.I)
    sentences = re.split(r'(?<!\bрис)(?<=[.!?]) (?=[А-ЯЁA-Z])', ' '.join(text.split()))
    return next((sentence for sentence in sentences if 25 <= len(sentence) <= 160
                 and mention.search(sentence)), '')


def source_table_slides(
    source: BinaryIO, page: SourcePage, table_index: int, limit: int,
) -> list[dict]:
    parts = page.tables[table_index].split_for_slides(limit)
    if len(parts) < 2:
        return [source_material_slide(source, page, table_index=table_index)]
    split_page = replace(page, tables=parts)
    slides = []
    for index in range(len(parts)):
        slide = source_material_slide(source, split_page, table_index=index)
        slide['title'] += f' · {index + 1}/{len(parts)}'
        slides.append(slide)
    return slides


def _image_material(source, page_number, bounds):
    source.seek(0)
    png = render_pdf_region(source, page_number, bounds)
    if len(png) > 1_124_985:
        raise ValueError('Source image exceeds the slide size limit')
    return {'kind': 'image', 'png': 'data:image/png;base64,' + b64encode(png).decode('ascii')}
