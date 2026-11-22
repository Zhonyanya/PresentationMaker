"""Check the geometry of editable tables and charts in PresentationMaker PPTX files."""

from xml.etree import ElementTree as ET
from zipfile import ZipFile

from tools.pptx_package import NS, slide_parts

# Allow integer rounding of individually exported grid columns and rows.
_GRID_TOLERANCE_EMU = 10
_SLIDE_TOLERANCE_EMU = 9_144  # 0.01 inch


def _pair(parent, xpath, names, *, size=False):
    node = parent.find(xpath, NS)
    if node is None:
        raise ValueError(f'Missing geometry element: {xpath}')
    values = tuple(int(node.attrib[name]) for name in names)
    if size and min(values) <= 0:
        raise ValueError('Geometry dimensions must be positive')
    return values


def _grid_size(table):
    columns = [int(el.attrib['w']) for el in table.findall('a:tblGrid/a:gridCol', NS)]
    rows = [int(el.attrib['h']) for el in table.findall('a:tr', NS)]
    if not columns or not rows or min(columns + rows) <= 0:
        raise ValueError('Table geometry needs positive row and column sizes')
    return sum(columns), sum(rows)


def _extends_outside(x, y, width, height, slide_width, slide_height):
    margin = _SLIDE_TOLERANCE_EMU
    return (
        x < -margin or y < -margin
        or x + width > slide_width + margin or y + height > slide_height + margin
    )


def inspect_geometry(path):
    issues = []
    object_counts = {'table': 0, 'chart': 0}
    with ZipFile(path) as deck:
        presentation = ET.fromstring(deck.read('ppt/presentation.xml'))
        slide_width, slide_height = _pair(presentation, 'p:sldSz', ('cx', 'cy'), size=True)
        for slide_number, part in enumerate(slide_parts(deck), 1):
            slide = ET.fromstring(deck.read(part))
            frames = slide.findall('p:cSld/p:spTree/p:graphicFrame', NS)
            for frame_number, frame in enumerate(frames, 1):
                table = frame.find('a:graphic/a:graphicData/a:tbl', NS)
                if table is None and frame.find('a:graphic/a:graphicData/c:chart', NS) is None:
                    continue
                kind = 'table' if table is not None else 'chart'
                object_counts[kind] += 1
                location = {'slide': slide_number, 'frame': frame_number, 'kind': kind}
                x, y = _pair(frame, 'p:xfrm/a:off', ('x', 'y'))
                width, height = _pair(frame, 'p:xfrm/a:ext', ('cx', 'cy'), size=True)
                if table is not None:
                    grid_width, grid_height = _grid_size(table)
                    for axis, frame_size, grid_size in (
                        ('width', width, grid_width), ('height', height, grid_height),
                    ):
                        if abs(frame_size - grid_size) > _GRID_TOLERANCE_EMU:
                            issues.append({
                                **location, 'code': f'table-grid-{axis}',
                                'frame_emu': frame_size, 'grid_emu': grid_size,
                            })
                    width, height = grid_width, grid_height
                if _extends_outside(x, y, width, height, slide_width, slide_height):
                    issues.append({
                        **location, 'code': 'outside-slide', 'box_emu': [x, y, width, height],
                    })

    return {'object_counts': object_counts, 'issues': issues}
