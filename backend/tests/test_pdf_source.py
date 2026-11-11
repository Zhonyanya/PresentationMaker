from base64 import b64decode
from dataclasses import replace
from io import BytesIO
from struct import unpack
from types import SimpleNamespace

import pytest

from app.presentations.pdf_document import build_pdf_document
from app.presentations.pdf_source import (
    SourceFigure,
    _captioned_figure,
    _framed_figures,
    _page_illustrations,
    read_pdf,
    source_material_slide,
)


def grid_pdf(
    right_column: tuple[str, ...], left_column: tuple[str, ...] = ("First line", "Second line"),
) -> BytesIO:
    """A ruled grid with text placed independently in each cell."""
    rows = len(right_column)
    top = 60 + 50 * rows
    commands = [f"20 60 260 {50 * rows} re S 150 60 m 150 {top} l S"]
    commands.extend(f"20 {y} m 280 {y} l S" for y in range(110, top, 50))
    for index, (left, right) in enumerate(zip(left_column, right_column, strict=True)):
        y = top - 26 - index * 50
        commands.append(f"BT /F1 12 Tf 30 {y} Td ({left}) Tj ET")
        commands.append(f"BT /F1 12 Tf 160 {y} Td ({right}) Tj ET")
    drawing = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 {top + 40}] ".encode()
        + b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(drawing)} >>\nstream\n".encode() + drawing + b"\nendstream",
    ]
    pdf = BytesIO(b"%PDF-1.4\n")
    pdf.seek(0, 2)
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(pdf.tell())
        pdf.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = pdf.tell()
    pdf.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.write(f"{offset:010d} 00000 n \n".encode())
    pdf.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    pdf.seek(0)
    return pdf


@pytest.mark.parametrize("right_column", [("", ""), ("Label", "")])
def test_ruled_prose_stays_in_page_text(right_column):
    (page,) = read_pdf(grid_pdf(right_column))
    assert not page.tables
    assert "First line" in page.text
    assert "Second line" in page.text


def test_populated_grid_is_extracted_as_table():
    (page,) = read_pdf(grid_pdf(("Count", "23")))
    assert page.tables[0].rows == (("First line", "Count"), ("Second line", "23"))
    assert "First line" not in (page.text or "")


def test_dense_grid_uses_the_crop_fallback():
    source = grid_pdf(("Count", "23"))
    (page,) = read_pdf(source)
    cell = "Detailed results and limitations " * 8
    table = replace(page.tables[0], rows=((cell,) * 8,) * 10)
    assert table.has_complete_grid
    assert not table.fits_slide
    slide = source_material_slide(source, replace(page, tables=(table,)), table_index=0)
    material = slide["sourceMaterial"]
    assert material["kind"] == "image"
    assert material["page"] == 1
    png = b64decode(material["png"].split(",", 1)[1])
    width, height = unpack(">II", png[16:24])
    assert width / height == pytest.approx(260 / 100)


def test_framed_chart_can_contain_overlapping_raster_layers():
    frame = dict(x0=20, top=100, x1=420, bottom=330, width=400, height=230)
    images = [
        dict(x0=45, top=145, x1=360, bottom=300, width=315, height=155),
        dict(x0=65, top=142, x1=380, bottom=300, width=315, height=158),
    ]
    page = SimpleNamespace(
        rects=[frame], curves=[], images=images, bbox=(0, 0, 450, 550),
        crop=lambda bounds: SimpleNamespace(
            extract_text=lambda: "Обрывок предыдущей строки\nДиаграмма 1",
            search=lambda *args, **kwargs: [{"top": 52, "bottom": 64, "text": "Диаграмма 1"}],
        ),
    )
    assert _framed_figures(page) == (SourceFigure((8, 52, 432, 333), "Диаграмма 1"),)


def test_figure_uses_sentence_that_refers_to_its_number(monkeypatch):
    source = grid_pdf(("Count", "23"))
    (page,) = read_pdf(source)
    page = replace(
        page,
        figures=(SourceFigure((20, 40, 280, 140), "Диаграмма 1"),),
        text="1\nДиаграмма 1 показывает рост охвата. На диаграмме 10 показан прогноз.",
    )
    monkeypatch.setattr("app.presentations.pdf_source.render_pdf_region", lambda *args: b"png")
    slide = source_material_slide(source, page, figure_index=0)
    assert slide["body"] == "Диаграмма 1 показывает рост охвата."
    assert slide["sourceMaterial"]["page"] == 1


def test_caption_below_a_picture_is_included():
    page = SimpleNamespace(
        bbox=(0, 0, 450, 550),
        crop=lambda bounds: SimpleNamespace(
            search=lambda *args, **kwargs: (
                [{"top": 308, "bottom": 320, "text": "Рисунок 2 — Схема"}]
                if bounds[1] == 300 else []
            ),
        ),
    )
    assert _captioned_figure(page, (20, 100, 420, 300)) == SourceFigure(
        (8, 97, 432, 320), "Рисунок 2",
    )


def test_illustrations_skip_small_icons_and_reused_raster_objects():
    def image(width, object_id):
        return dict(x0=20, top=100, x1=20 + width, bottom=100 + width,
                    width=width, height=width, stream=SimpleNamespace(objid=object_id))

    page = SimpleNamespace(
        bbox=(0, 0, 450, 550), rects=[], curves=[], images=[image(10, 1), image(140, 2)],
        crop=lambda bounds: SimpleNamespace(search=lambda *args, **kwargs: []),
    )
    seen = set()
    assert _page_illustrations(page, seen) == ((), ((20, 100, 160, 240),))
    assert _page_illustrations(page, seen) == ((), ())


def test_long_table_repeats_header_within_slide_budget():
    header = ("Indicator", "Count")
    body = tuple((f"Measure {number}", str(number)) for number in range(12))
    left, right = zip(header, *body, strict=True)
    source = grid_pdf(right, left)
    deck = build_pdf_document(source, "Report", 5)
    materials = [slide["sourceMaterial"] for slide in deck["slides"] if "sourceMaterial" in slide]
    assert len(materials) == 2
    assert all(material["kind"] == "table" and material["rows"][0] == list(header)
               for material in materials)
    assert [tuple(row) for material in materials for row in material["rows"][1:]] == list(body)
