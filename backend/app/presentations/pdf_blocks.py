"""Adapt extracted PDF pages to the common source document."""

from typing import BinaryIO

from app.presentations.source_blocks import (
    SOURCE_ADAPTER,
    IllustrationBlock,
    SourceDocument,
    TableBlock,
    TextBlock,
)

from .pdf_source import SourcePage, read_pdf


def read_pdf_source(source: BinaryIO) -> SourceDocument:
    document = pdf_blocks(read_pdf(source))
    return SOURCE_ADAPTER.validate_python(document)


def pdf_blocks(pages: tuple[SourcePage, ...]) -> SourceDocument:
    blocks = []
    for page in pages:
        prefix = f'p{page.number}'
        if page.text:
            blocks.append(TextBlock(f'{prefix}-text', page.text, page.number))
        for index, table in enumerate(page.tables, 1):
            blocks.append(TableBlock(
                f'{prefix}-table-{index}', table.rows, page.number, table.number,
            ))
        illustrations = [
            (figure.bounds, figure.caption or figure.reference) for figure in page.figures
        ]
        illustrations.extend((bounds, '') for bounds in page.images)
        for index, (bounds, caption) in enumerate(illustrations, 1):
            locator = ','.join(str(value) for value in bounds)
            blocks.append(IllustrationBlock(
                f'{prefix}-figure-{index}', locator, caption, page.number,
            ))
    return SourceDocument(tuple(blocks))
