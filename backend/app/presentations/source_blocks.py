"""Shared source document for imported reports and the ML boundary."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, TypeAdapter

MAX_SOURCE_TEXT = 120_000
MAX_PAGINATED_SOURCE_TEXT = 240_000

BlockID = Annotated[str, Field(strict=True, min_length=1, max_length=128)]
SourceString = Annotated[str, Field(strict=True)]
Page = Annotated[int, Field(strict=True, ge=1, le=250)]


@dataclass(frozen=True)
class TextBlock:
    id: BlockID
    text: SourceString
    page: Page | None = None
    kind: Literal['text'] = 'text'


@dataclass(frozen=True)
class TableBlock:
    id: BlockID
    rows: tuple[tuple[SourceString | None, ...], ...]
    page: Page | None = None
    number: SourceString | None = None
    comparable: Annotated[bool, Field(strict=True)] = True
    kind: Literal['table'] = 'table'
    caption: SourceString = ''


@dataclass(frozen=True)
class IllustrationBlock:
    id: BlockID
    locator: SourceString
    caption: SourceString = ''
    page: Page | None = None
    png: Annotated[
        str, Field(strict=True, max_length=120_000,
                   pattern=r'^data:image/png;base64,iVBORw0KGgo[A-Za-z0-9+/]+={0,2}$'),
    ] | None = None
    kind: Literal['illustration'] = 'illustration'


@dataclass(frozen=True)
class SourceDocument:
    __pydantic_config__ = ConfigDict(strict=False, revalidate_instances='always')

    blocks: Annotated[tuple[
        Annotated[TextBlock | TableBlock | IllustrationBlock, Field(discriminator='kind')], ...
    ], Field(min_length=1, max_length=10_000)]


def source_text(source: SourceDocument) -> str:
    """Project all readable content in order for the existing text-based ML contract."""
    parts = []
    for block in source.blocks:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, TableBlock):
            if block.caption:
                parts.append(block.caption)
            elif block.number:
                parts.append(f'Таблица {block.number}')
            parts.append('\n'.join('\t'.join(cell or '' for cell in row) for row in block.rows))
        elif block.caption:
            parts.append(block.caption)
    return '\n\n'.join(parts).strip()


def validate_source(source: SourceDocument) -> SourceDocument:
    ids = {block.id for block in source.blocks}
    if len(ids) != len(source.blocks) or any(not identifier.strip() for identifier in ids):
        raise ValueError('Source block identifiers must be unique and nonblank')
    content = source_text(source)
    limit = MAX_PAGINATED_SOURCE_TEXT if all(block.page is not None for block in source.blocks) else MAX_SOURCE_TEXT
    if not content or len(content.encode('utf-16-le')) // 2 > limit:
        raise ValueError('Source content is empty or too long')
    if sum(len(block.png or '') for block in source.blocks
           if isinstance(block, IllustrationBlock)) > 512_000:
        raise ValueError('Embedded source images exceed the source limit')
    fields = [*ids, content]
    for block in source.blocks:
        if isinstance(block, IllustrationBlock):
            fields.append(block.locator)
        elif isinstance(block, TableBlock) and block.number is not None:
            fields.append(block.number)
    for value in fields:
        if '\x00' in value:
            raise ValueError('NUL is not supported in source text')
        value.encode('utf-8')
    return source


SourceInput = Annotated[SourceDocument, AfterValidator(validate_source)]
SOURCE_ADAPTER = TypeAdapter(SourceInput)
