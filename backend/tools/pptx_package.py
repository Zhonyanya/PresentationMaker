"""Resolve PresentationMaker PPTX relationships in the order shown in the deck."""

from posixpath import basename, dirname, join, normpath
from xml.etree import ElementTree as ET

NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
REL_ID = '{' + NS['r'] + '}id'
DRAWING = '{' + NS['a'] + '}'


def paragraph_text(paragraph):
    # Formatting can split one word across runs; only an actual break adds a space.
    return ''.join(
        ' ' if element.tag == DRAWING + 'br' else element.text or ''
        for element in paragraph.iter()
        if element.tag in (DRAWING + 'br', DRAWING + 't')
    )


def related_parts(deck, part, kind):
    folder = dirname(part)
    rels = join(folder, '_rels', basename(part) + '.rels')
    relationships = ET.fromstring(deck.read(rels))
    return {
        rel.attrib['Id']: normpath(join(folder, target)).lstrip('/')
        for rel in relationships.findall(REL + 'Relationship')
        if rel.get('Type') == NS['r'] + '/' + kind
        and rel.get('TargetMode') != 'External'
        and (target := rel.attrib['Target'])
    }


def slide_parts(deck):
    part = 'ppt/presentation.xml'
    presentation = ET.fromstring(deck.read(part))
    targets = related_parts(deck, part, 'slide')
    return tuple(
        targets[slide.attrib[REL_ID]]
        for slide in presentation.findall('p:sldIdLst/p:sldId', NS)
    )
