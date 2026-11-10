"""Build a source-grounded deck from a text-layer PDF."""

from typing import BinaryIO
from uuid import uuid4

from app.presentations.pdf_source import read_pdf, source_material_slide
from app.presentations.schemas import Document
from presentation_ml.grounding import select_page_passages


def build_pdf_document(source: BinaryIO, title: str, slide_count: int) -> dict:
    if not 3 <= slide_count <= 20:
        raise ValueError('PDF slide count must be between 3 and 20')

    pages = read_pdf(source)
    tables = [(page, index) for page in pages for index in range(len(page.tables))]
    first_editable = next((item for item in tables if item[0].tables[item[1]].fits_slide), None)
    if first_editable is not None:
        tables.remove(first_editable)
        tables.insert(0, first_editable)
    images = [
        ('figure', page, index) for page in pages for index in range(len(page.figures))
    ] + [('image', page, index) for page in pages for index in range(len(page.images))]
    available = slide_count - 1
    material_budget = available // 2
    selected = []
    # Alternate material types so a table-heavy report can still show illustrations.
    for index in range(max(len(tables), len(images))):
        if index < len(tables):
            selected.append(('table', *tables[index]))
        if index < len(images):
            selected.append(images[index])
        if len(selected) >= material_budget:
            break
    selected = selected[:material_budget]
    excerpts = select_page_passages(
        ((page.number, page.text) for page in pages), limit=available - len(selected),
    )
    content = [
        (p.page_number, {
            'id': str(uuid4()),
            'layout': 'text',
            'title': f'Материалы доклада · стр. {p.page_number}',
            'body': p.text,
            'notes': f'Источник: PDF, стр. {p.page_number}',
        })
        for p in excerpts
    ]
    for kind, page, index in selected:
        kwargs = {f'{kind}_index': index}
        content.append((page.number, source_material_slide(source, page, **kwargs)))
    if not content:
        raise ValueError('PDF has no extractable content')
    content.sort(key=lambda item: item[0])
    cover = {'id': str(uuid4()), 'layout': 'title', 'title': title}
    return Document.model_validate({
        'title': title, 'slides': [cover, *(slide for _, slide in content)],
    }).model_dump(exclude_none=True)
