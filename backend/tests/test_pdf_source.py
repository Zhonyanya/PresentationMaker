from base64 import b64decode
from dataclasses import replace
from io import BytesIO
from struct import unpack
from types import SimpleNamespace

import pytest

from app.presentations.pdf_blocks import pdf_blocks, read_pdf_source
from app.presentations.pdf_document import build_pdf_document
from app.presentations.pdf_source import (
    SourceFigure,
    SourcePage,
    _captioned_figure,
    _column_breaks,
    _framed_figures,
    _page_illustrations,
    read_pdf,
    reading_regions,
    source_material_slide,
)
from app.presentations.schemas import GenerateRequest
from app.presentations.source_blocks import SOURCE_ADAPTER, TextBlock, source_text


def grid_pdf(
    right_column: tuple[str, ...], left_column: tuple[str, ...] = ("First line", "Second line"),
    *, add_prose: bool = False,
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
    if add_prose:
        commands.extend([
            f"BT /F1 16 Tf 30 {top + 72} Td (Method) Tj ET",
            f"BT /F1 12 Tf 30 {top + 43} Td (Results use a complete year.) Tj ET",
            f"BT /F1 12 Tf 30 {top + 27} Td (Cancelled sessions were excluded.) Tj ET",
            "BT /F1 12 Tf 30 30 Td (Phone bookings were not measured.) Tj ET",
            "BT /F1 12 Tf 30 14 Td (- Walk-ins were still accepted.) Tj ET",
        ])
    return positioned_pdf(commands, 300, top + (100 if add_prose else 40))


def positioned_pdf(
    commands: list[str], width: int, height: int, *, font_encoding: str = "",
) -> BytesIO:
    drawing = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] ".encode()
        + b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica {font_encoding} >>".encode(),
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


@pytest.mark.parametrize("captioned", [True, False])
def test_three_horizontal_rules_require_a_caption_and_keep_table_cells(captioned):
    commands = [f"20 {y} m 280 {y} l S" for y in (180, 161, 110)]
    if captioned:
        commands.append("BT /F1 12 Tf 20 198 Td (Table 6: Energy use) Tj ET")
    for y, row in [(168, ("Scenario", "Wh per image", "MWh per day")),
                   (149, ("Baseline", "1.35", "135")),
                   (135, ("New", "0.563", "56")),
                   (121, ("Growth", "0.563", "570"))]:
        for x, value in zip((28, 118, 201), row, strict=True):
            commands.append(f"BT /F1 10 Tf {x} {y} Td ({value}) Tj ET")
    commands.append("BT /F1 12 Tf 28 80 Td (Unrelated document prose.) Tj ET")
    (page,) = read_pdf(positioned_pdf(commands, 300, 235))
    assert "Unrelated document prose." in page.text
    if not captioned:
        assert not page.tables
        assert "Baseline" in page.text
        return
    (table,) = page.tables
    assert table.number == "6"
    assert table.rows == (("Scenario", "Wh per image", "MWh per day"),
                          ("Baseline", "1.35", "135"), ("New", "0.563", "56"),
                          ("Growth", "0.563", "570"))
    assert "Baseline" not in page.text


def test_pdf_source_round_trips_as_a_generation_request():
    parsed = read_pdf_source(grid_pdf(("Count", "23")))
    source = SOURCE_ADAPTER.dump_python(parsed, mode="json", exclude_none=True)
    generation = GenerateRequest.model_validate({"source": source, "slideCount": 5})
    (table,) = generation.source.blocks
    assert (table.id, table.page, table.rows[1]) == ("p1-table-1", 1, ("Second line", "23"))


def test_equation_with_named_functions_keeps_the_math_run():
    from app.presentations.pdf_equations import _math_run

    glyphs = [
        {'text': char, 'x0': i * 5, 'x1': i * 5 + 4, 'fontname': 'CMMI9'}
        for i, char in enumerate('alpha=beta+gamma')
    ]
    assert _math_run(glyphs, 9) == glyphs
    assert not _math_run([dict(glyph, fontname='Arial') for glyph in glyphs], 9)


def test_pdf_preserves_numbered_display_equation_without_grabbing_inline_reference():
    pdf = positioned_pdf([
        "BT /F1 10 Tf 25 238 Td (The model is described by the following equation.) Tj ET",
        "BT /F1 11 Tf 99 195 Td (E = V * 1.35) Tj ET",
        "BT /F1 11 Tf 253 195 Td (\\(16\\)) Tj ET",
        "BT /F1 10 Tf 25 166 Td (The data are shown above \\(16\\).) Tj ET",
    ], 300, 270)
    blocks = read_pdf_source(pdf).blocks
    (equation,) = [block for block in blocks if block.kind == "illustration"]
    assert equation.caption == "Формула (16)"
    assert equation.page == 1
    assert equation.png.startswith('data:image/png;base64,iVBORw0KGgo')


@pytest.mark.parametrize("misprinted", [False, True])
@pytest.mark.parametrize(("white", "group_a", "group_b"), [
    ("1 1 1 rg", "0.25 0.35 0.55 rg", "0.85 0.45 0.15 rg"),
    ("1 g", "0 g", "0.55 g"),
    ("0 0 0 0 k", "0.25 0.35 0.55 0 k", "0.05 0.45 0.75 0 k"),
])
def test_vector_bar_chart_recovers_printed_values_only_when_consistent_with_bar_heights(
    misprinted, white, group_a, group_b,
):
    commands = [f"{white} 35 120 280 170 re f"]
    for color, bars, legend_x, legend in (
        (group_a, ((93, 41.5), (206, 43.6)), 65, "Public"),
        (group_b, ((119, 49.8), (232, 51.9)), 175, "Private"),
    ):
        for x, value in bars:
            height = 2 * value
            commands.append(f"{color} {x} 160 26 {height} re f")
            label = 91.5 if misprinted and x == 93 else value
            commands.append(f"0 0 0 rg BT /F1 8 Tf {x+3} {165+height} Td ({label}) Tj ET")
        commands += [f"{color} {legend_x} 129 5 5 re f",
                     f"0 0 0 rg BT /F1 9 Tf {legend_x+8} 129 Td ({legend}) Tj ET"]
    commands += ["BT /F1 9 Tf 109 145 Td (2020) Tj ET", "BT /F1 9 Tf 222 145 Td (2024) Tj ET",
                 "BT /F1 10 Tf 65 105 Td (Figure 2.1.6 - Share by sector, %) Tj ET"]
    document = read_pdf_source(positioned_pdf(commands, 350, 310))
    tables = [block for block in document.blocks if block.kind == "table"]
    if misprinted:
        assert not tables
        return
    (table,) = tables
    assert table.caption.startswith("Figure 2.1.6")
    assert table.rows[1:] == ((None, "2020", "2024"), ("Public", "41.5%", "43.6%"),
                              ("Private", "49.8%", "51.9%"))


def test_pdf_source_keeps_paragraphs_and_tables_in_reading_order():
    parsed = read_pdf_source(grid_pdf(("Count", "23"), add_prose=True))
    assert [block.kind for block in parsed.blocks] == ["text", "text", "table", "text", "text"]
    heading, method, table, limitation, access = parsed.blocks
    assert heading.text == "Method"
    assert method.text == "Results use a complete year. Cancelled sessions were excluded."
    assert table.id == "p1-table-1"
    assert limitation.text == "Phone bookings were not measured."
    assert access.text == "- Walk-ins were still accepted."
    assert all(block.page == 1 for block in parsed.blocks)
    assert len({block.id for block in parsed.blocks if isinstance(block, TextBlock)}) == 4
    text = source_text(parsed)
    assert text.index("Cancelled sessions") < text.index("Second line")
    assert text.index("Second line") < text.index("Phone bookings")


@pytest.mark.parametrize("remote_heading", ["Remote site", "USA"])
def test_pdf_source_reads_parallel_prose_columns_independently(remote_heading):
    commands = [
        "BT /F1 20 Tf 36 280 Td (Methods and limitations across the two sites) Tj ET",
    ]
    for x, heading, details in [
        (36, "Central site", [
            "Keep the original records.", "Limit corrections to two days.",
            "Use a separate note for exceptions.",
        ]),
        (316, remote_heading, [
            "Save a digital copy first.", "Retain copies for one calendar year.",
            "List the return date in the register.",
        ]),
    ]:
        commands.append(f"BT /F1 16 Tf {x} 230 Td ({heading}) Tj ET")
        for index, line in enumerate(details):
            commands.append(f"BT /F1 12 Tf {x} {200 - 16 * index} Td ({line}) Tj ET")
    commands.extend([
        "BT /F1 16 Tf 36 128 Td (Limitations) Tj ET",
        "BT /F1 12 Tf 36 100 Td "
        "(The joint review covers both sites separately and assumes a complete reporting period.) "
        "Tj ET",
    ])
    source = read_pdf_source(positioned_pdf(commands, 600, 320))
    assert [block.text for block in source.blocks] == [
        "Methods and limitations across the two sites",
        "Central site",
        "Keep the original records. Limit corrections to two days. "
        "Use a separate note for exceptions.",
        remote_heading,
        "Save a digital copy first. Retain copies for one calendar year. "
        "List the return date in the register.",
        "Limitations",
        "The joint review covers both sites separately and assumes a complete reporting period.",
    ]


def test_parallel_counts_and_funding_shares_can_become_an_exact_table():
    from app.presentations.prose_tables import parallel_count_table

    text = (
        'Общее число зачисленных в 2024 году составило 1 298,1 тыс. человек, из них за счет '
        'бюджетных средств – 43,6%. По уровням подготовки данные распределились следующим '
        'образом: бакалавриат – 829,7 тыс. человек (за счет бюджетных средств – 41,5%), '
        'специалитет – 208,3 тыс. человек (за счет бюджетных средств – 44,1%), '
        'магистратура – 260 тыс. человек (за счет бюджетных средств – 49,8%).'
    )
    table = parallel_count_table(text)
    assert table == (
        ('Группа', 'Значение, тыс. человек', 'Доля (за счет бюджетных средств)'),
        ('бакалавриат', '829,7', '41,5%'),
        ('специалитет', '208,3', '44,1%'),
        ('магистратура', '260', '49,8%'),
        ('Всего', '1 298,1', '43,6%'),
    )
    inconsistent = text.replace('средств – 44,1%', 'средств другого бюджета – 44,1%')
    assert parallel_count_table(inconsistent) is None


def test_parallel_measures_preserve_english_units_and_decline_unknown_total_scope():
    from app.presentations.prose_tables import parallel_count_table

    text = (
        'The total output was 4,321.5 MWh, of which commercial users accounted for – 40%. '
        'Breakdown by district: North – 2,100.5 MWh (industrial users – 51%), '
        'and South – 2,221 MWh (industrial users – 55%).'
    )
    assert parallel_count_table(text) == (
        ('Group', 'Value, MWh', 'Share (industrial users)'),
        ('North', '2,100.5', '51%'),
        ('South', '2,221', '55%'),
    )
    assert parallel_count_table(text.replace('2,221 MWh', '2,221 kWh')) is None


def test_generously_spaced_body_lines_keep_numeric_qualifiers_in_the_same_paragraph():
    commands = [
        "BT /F1 12 Tf 50 250 Td (Applications from all locations are reported together) Tj ET",
        "BT /F1 12 Tf 20 229 Td (including the central site where 18,3 percent were) Tj ET",
        "BT /F1 12 Tf 20 208 Td (accepted during the observation period.) Tj ET",
        "BT /F1 12 Tf 50 187 Td (The next section covers staffing.) Tj ET",
    ]
    (page,) = read_pdf(positioned_pdf(commands, 400, 300))
    assert [p.text for p in page.paragraphs] == [
        ("Applications from all locations are reported together including the central site "
         "where 18,3 percent were accepted during the observation period."),
        "The next section covers staffing.",
    ]


def test_column_breaks_use_the_shared_gutter_instead_of_an_early_line_end():
    gaps = [[(1, edge, 784)] for edge in (644, 663, 685, 727, 729, 731, 735)]
    (gutter,) = _column_breaks(gaps)
    assert 735 < gutter < 784


def test_column_caption_overhang_keeps_adjacent_paragraph_together():
    regions = reading_regions([
        (10, 280, 510, False, 'The method changed'),
        (14, 36, 248, False, 'Figure caption'),
        (22, 280, 510, False, 'and lowered the recorded count.'),
        (34, 36, 510, False, 'Full-width note'),
    ], (240,))

    assert list(regions) == [
        ['Figure caption'],
        ['The method changed', 'and lowered the recorded count.'],
        ['Full-width note'],
    ]


def test_pdf_source_preserves_multichar_glyphs_when_splitting_a_line():
    commands = []
    for y, left, right in [
        (260, r"of\336ce here", "Remote site"),
        (240, "First report", "Paper totals"),
        (220, "Second report", "Other totals"),
    ]:
        commands.extend([
            f"BT /F1 12 Tf 36 {y} Td ({left}) Tj ET",
            f"BT /F1 12 Tf 316 {y} Td ({right}) Tj ET",
        ])
    pdf = positioned_pdf(commands, 600, 320, font_encoding="/Encoding /MacRomanEncoding")
    (page,) = read_pdf(pdf)
    assert page.text.splitlines() == [
        "office here", "First report", "Second report",
        "Remote site", "Paper totals", "Other totals",
    ]


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
    assert _framed_figures(page) == (SourceFigure((8, 52, 432, 333), "Диаграмма 1", "Диаграмма 1"),)


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


def test_preview_opens_an_indexed_figure_title_ending_in_a_year(monkeypatch):
    source = grid_pdf(("Count", "23"))
    (page,) = read_pdf(source)
    page = replace(page, figures=(SourceFigure((20, 40, 280, 140),
                                              "Travel in 2025", "Travel in 2025 [STAT0101]"),))
    monkeypatch.setattr("app.presentations.pdf_source.render_pdf_region", lambda *args: b"png")
    slide = source_material_slide(source, page, figure_index=0)
    assert slide["title"] == "Travel in 2025 · стр. 1"
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
    figure = _captioned_figure(page, (20, 100, 420, 300))
    assert figure == SourceFigure((8, 97, 432, 320), "Рисунок 2", "Рисунок 2 — Схема")
    (block,) = pdf_blocks((SourcePage(1, "", (), (), (figure,)),)).blocks
    assert block.caption == "Рисунок 2 — Схема"


def test_indexed_raster_chart_is_kept_with_its_title_and_original_pixels(monkeypatch):
    image = dict(x0=36, top=145, x1=225, bottom=289, width=189, height=144,
                 stream=SimpleNamespace(objid=1))
    logo = dict(x0=42, top=18, x1=102, bottom=60, width=60, height=42,
                stream=SimpleNamespace(objid=2))

    def crop(bounds):
        return SimpleNamespace(search=lambda *args, **kwargs: (
            [{"x0": 38, "top": 110, "bottom": 121, "text": "Average trips [STAT0101]"}]
            if bounds[3] == 145 and args[0].search("Average trips [STAT0101]") else []
        ))

    page = SimpleNamespace(
        bbox=(0, 0, 400, 600), rects=[], curves=[], images=[logo, image], crop=crop,
    )
    figures, images = _page_illustrations(page, set())
    (figure,) = figures
    assert images == ((42, 18, 102, 60),)
    assert figure.caption == "Average trips [STAT0101]"
    assert figure.bounds == (36, 110, 225, 289)
    parsed = SourcePage(1, "The survey changed in 2025.", (), images, figures)
    monkeypatch.setattr("app.presentations.pdf_blocks.read_pdf", lambda *_: (parsed,))
    png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                    "AAAAC0lEQVR42mP8/x8AAusB9Wl2Rx8AAAAASUVORK5CYII=")
    monkeypatch.setattr("app.presentations.pdf_blocks.render_pdf_region", lambda *args: png)
    document = read_pdf_source(BytesIO())
    blocks = [block for block in document.blocks if block.kind == "illustration"]
    assert [block.caption for block in blocks] == ["", "Average trips [STAT0101]"]
    assert blocks[0].png is None
    assert b64decode(blocks[1].png.split(",")[1]) == png


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
