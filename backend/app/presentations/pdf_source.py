"""Page-aware extraction for text-layer PDF reports."""

import re
from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO
from uuid import uuid4

import pdfplumber


@dataclass(frozen=True)
class SourceTable:
    bounds: tuple[float, float, float, float]
    rows: tuple[tuple[str | None, ...], ...]

    @property
    def fits_slide(self) -> bool:
        return (
            self.has_complete_grid and len(self.rows) <= 10 and len(self.rows[0]) <= 8
            and all(
                len(cell.encode('utf-16-le')) <= 600
                for row in self.rows for cell in row if cell is not None
            )
        )

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


@dataclass(frozen=True)
class SourcePage:
    number: int
    text: str
    tables: tuple[SourceTable, ...]
    images: tuple[tuple[float, float, float, float], ...]
    figures: tuple[tuple[float, float, float, float], ...] = ()


def _vector_figures(page):
    """Find framed vector figures with a nearby source caption."""
    figures = {}
    for rect in page.rects:
        if rect['width'] < 160 or rect['height'] < 60:
            continue
        x0, top, x1, bottom = (rect[key] for key in ('x0', 'top', 'x1', 'bottom'))
        if sum(
            x0 <= c['x0'] <= c['x1'] <= x1 and top <= c['top'] <= c['bottom'] <= bottom
            for c in page.curves
        ) < 8:
            continue
        px0, ptop, px1, pbottom = page.bbox
        bounds = (
            max(px0, x0 - 12), max(ptop, top - 85),
            min(px1, x1 + 12), min(pbottom, bottom + 3),
        )
        caption = page.crop((*bounds[:3], top)).extract_text()
        if re.search(r'(?im)^\s*(?:диаграмма|рисунок|схема|график)\s*\d+', caption):
            figures[tuple(round(value, 1) for value in bounds)] = bounds
    return tuple(figures.values())


def read_pdf(source: BinaryIO, *, max_pages: int = 250) -> tuple[SourcePage, ...]:
    """Extract positioned materials without flattening table cells into prose."""
    result = []
    with pdfplumber.open(source) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError('PDF exceeds the page limit')
        for page in pdf.pages:
            tables = tuple(
                SourceTable(table.bbox, tuple(tuple(row) for row in table.extract()))
                for table in page.find_tables()
                if len(table.rows) >= 2 and len(table.columns) >= 2
            )
            images = tuple(
                (image['x0'], image['top'], image['x1'], image['bottom'])
                for image in page.images
            )
            figures = _vector_figures(page)
            excluded = (*[table.bounds for table in tables], *figures)
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
    if table_index is not None:
        table = page.tables[table_index]
        rows = table.rows
        if table.fits_slide:
            material = {'kind': 'table', 'rows': [list(row) for row in rows]}
        else:
            material = _image_material(source, page.number, table.bounds)
        title = f'Таблица · стр. {page.number}'
    elif figure_index is not None:
        material = _image_material(source, page.number, page.figures[figure_index])
        title = f'Диаграмма или схема · стр. {page.number}'
    else:
        material = _image_material(source, page.number, page.images[image_index])
        title = f'Иллюстрация · стр. {page.number}'
    return {
        'id': str(uuid4()), 'layout': 'text', 'title': title, 'body': '',
        'sourceMaterial': {**material, 'page': page.number},
    }


def _image_material(source, page_number, bounds):
    source.seek(0)
    png = render_pdf_region(source, page_number, bounds)
    if len(png) > 1_124_985:
        raise ValueError('Source image exceeds the slide size limit')
    return {'kind': 'image', 'png': 'data:image/png;base64,' + b64encode(png).decode('ascii')}
