"""Adapt extracted PDF pages to the common source document."""

from base64 import b64encode
from io import BytesIO
from typing import BinaryIO

from PIL import Image

from app.presentations.source_blocks import (
    SOURCE_ADAPTER,
    IllustrationBlock,
    SourceDocument,
    TableBlock,
    TextBlock,
)

from .pdf_source import SourcePage, SourceParagraph, _contains, read_pdf, reading_regions, render_pdf_region
from .pdf_vector_charts import chart_caption_number
from .prose_tables import with_parallel_tables


def _fit_png(png: bytes, limit: int) -> str | None:
    prefix = 'data:image/png;base64,'
    if len(png) <= (limit - len(prefix)) // 4 * 3:
        return prefix + b64encode(png).decode('ascii')
    with Image.open(BytesIO(png)) as source:
        image = source.convert('RGB')
    for scale in (1, 0.8, 0.65, 0.5):
        size = tuple(max(1, round(dimension * scale)) for dimension in image.size)
        resized = image.resize(size, Image.Resampling.LANCZOS) if scale < 1 else image
        output = BytesIO()
        resized.quantize(colors=256).save(output, format='PNG', optimize=True)
        if output.tell() <= (limit - len(prefix)) // 4 * 3:
            return prefix + b64encode(output.getvalue()).decode('ascii')
    return None


def read_pdf_source(source: BinaryIO) -> SourceDocument:
    pages = read_pdf(source)
    images = {}
    remaining = 512_000
    # Give equations first use of the image budget. Figures with extracted data
    # stay available as tables and do not compete for space with raster figures.
    equations = ((page.number, bounds) for page in pages for _, bounds in page.equations)
    figures = (
        (page.number, figure.bounds) for page in pages for figure in page.figures
        if figure.caption and not any(
            chart_caption_number(table.caption)
            and (_contains(table.bounds, figure.bounds) or _contains(figure.bounds, table.bounds))
            for table in page.tables
        )
    )
    for targets in (equations, figures):
        for page_number, bounds in targets:
            if remaining < 1_000:
                break
            source.seek(0)
            try:
                data = _fit_png(render_pdf_region(source, page_number, bounds), min(120_000, remaining))
            except (ValueError, OSError):
                continue
            if data is not None:
                images[page_number, bounds] = data
                remaining -= len(data)
    document = with_parallel_tables(pdf_blocks(pages, images))
    return SOURCE_ADAPTER.validate_python(document)


def pdf_blocks(pages: tuple[SourcePage, ...], images=None) -> SourceDocument:
    blocks = []
    for page in pages:
        prefix = f'p{page.number}'
        positioned = []
        paragraphs = page.paragraphs or ((SourceParagraph(0, 0, page.text),) if page.text else ())
        for index, paragraph in enumerate(paragraphs, 1):
            identifier = f'{prefix}-text' if index == 1 else f'{prefix}-text-{index}'
            positioned.append((paragraph.top, paragraph.left, paragraph.right or paragraph.left,
                               paragraph.starts_band,
                               TextBlock(identifier, paragraph.text, page.number)))
        for index, table in enumerate(page.tables, 1):
            positioned.append((table.bounds[1], table.bounds[0], table.bounds[2], False, TableBlock(
                f'{prefix}-table-{index}', table.rows, page.number, table.number,
                caption=table.caption,
            )))
        illustrations = [
            (figure.bounds, figure.caption or figure.reference) for figure in page.figures
        ]
        illustrations.extend((bounds, '') for bounds in page.images)
        for index, (bounds, caption) in enumerate(illustrations, 1):
            locator = ','.join(str(value) for value in bounds)
            positioned.append((bounds[1], bounds[0], bounds[2], False, IllustrationBlock(
                f'{prefix}-figure-{index}', locator, caption, page.number,
                png=(images or {}).get((page.number, bounds)) if caption else None,
            )))
        for index, (number, bounds) in enumerate(page.equations, 1):
            png = (images or {}).get((page.number, bounds))
            locator = ','.join(str(value) for value in bounds)
            positioned.append((bounds[1], bounds[0], bounds[2], False, IllustrationBlock(
                f'{prefix}-equation-{index}', locator, f'Формула ({number})', page.number, png=png,
            )))
        blocks.extend(block for region in reading_regions(positioned, page.column_breaks)
                      for block in region)
    return SourceDocument(tuple(blocks))
