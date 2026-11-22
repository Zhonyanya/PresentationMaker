"""Adapt extracted PDF pages to the common source document."""

from typing import BinaryIO

from app.presentations.source_blocks import (
    SOURCE_ADAPTER,
    IllustrationBlock,
    SourceDocument,
    TableBlock,
    TextBlock,
)

from .pdf_source import SourcePage, SourceParagraph, read_pdf, reading_regions


def read_pdf_source(source: BinaryIO) -> SourceDocument:
    document = pdf_blocks(read_pdf(source))
    return SOURCE_ADAPTER.validate_python(document)


def pdf_blocks(pages: tuple[SourcePage, ...]) -> SourceDocument:
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
            )))
        illustrations = [
            (figure.bounds, figure.caption or figure.reference) for figure in page.figures
        ]
        illustrations.extend((bounds, '') for bounds in page.images)
        for index, (bounds, caption) in enumerate(illustrations, 1):
            locator = ','.join(str(value) for value in bounds)
            positioned.append((bounds[1], bounds[0], bounds[2], False, IllustrationBlock(
                f'{prefix}-figure-{index}', locator, caption, page.number,
            )))
        blocks.extend(block for region in reading_regions(positioned, page.column_breaks)
                      for block in region)
    return SourceDocument(tuple(blocks))
