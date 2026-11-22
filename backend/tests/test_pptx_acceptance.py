import json
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from tools import pptx_acceptance

DRAWING = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PRESENTATION = 'http://schemas.openxmlformats.org/presentationml/2006/main'
OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def write_deck(path, *, graphics='', extra_paragraphs=''):
    def slide(paragraphs, extra=''):
        return (
            f'<p:sld xmlns:p="{PRESENTATION}" xmlns:a="{DRAWING}">'
            f'<p:cSld><p:spTree><p:sp><p:txBody>{paragraphs}'
            f'</p:txBody></p:sp>{extra}</p:spTree></p:cSld></p:sld>'
        )

    with ZipFile(path, 'w') as deck:
        deck.writestr('ppt/presentation.xml', (
            f'<p:presentation xmlns:p="{PRESENTATION}" xmlns:r="{OFFICE_REL}">'
            '<p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
            '<p:sldId id="257" r:id="rId1"/></p:sldIdLst>'
            '<p:sldSz cx="12000000" cy="6800000"/></p:presentation>'
        ))
        deck.writestr('ppt/_rels/presentation.xml.rels', (
            f'<Relationships xmlns="{PACKAGE_REL}">'
            f'<Relationship Id="rId1" Type="{OFFICE_REL}/slide" Target="slides/slide2.xml"/>'
            f'<Relationship Id="rId2" Type="{OFFICE_REL}/slide" Target="/ppt/slides/slide8.xml"/>'
            '</Relationships>'
        ))
        deck.writestr('ppt/slides/slide8.xml', slide(
            '<a:p><a:r><a:t>Общий итог</a:t></a:r></a:p>'
            '<a:p><a:r><a:t>127 участников</a:t></a:r></a:p>'
        ))
        deck.writestr('ppt/slides/slide2.xml', slide(
            '<a:p><a:r><a:t>Контрольная </a:t></a:r><a:r><a:t>группа</a:t></a:r>'
            '<a:br/><a:r><a:t>отсутствовала</a:t></a:r></a:p>'
            '<a:p><a:r><a:t>98,7%</a:t></a:r></a:p>'
            f'<a:p><a:r><a:t>{escape(extra_paragraphs)}</a:t></a:r></a:p>', graphics,
        ))
        deck.writestr('ppt/slides/slide1.xml', slide(
            '<a:p><a:r><a:t>График согласован</a:t></a:r></a:p>'
        ))
        deck.writestr('ppt/notesSlides/notesSlide1.xml', slide(
            '<a:p><a:r><a:t>Бюджет утверждён</a:t></a:r></a:p>'
        ))


def test_pptx_uses_referenced_slides_and_never_matches_part_of_a_number(tmp_path):
    path = tmp_path / 'example.pptx'
    write_deck(path)
    result = pptx_acceptance.inspect_pptx(path, {
        'slideCount': 3,
        'anchors': [
            'общий итог', '127', '27', 'контрольная группа отсутствовала', '98,7%',
            '7%', '98', 'График согласован', 'Бюджет утверждён',
        ],
        'forbidden_fragments': ['127 участников'],
    })
    assert result['matches'] == {
        'общий итог': [1], '127': [1], 'контрольная группа отсутствовала': [2], '98,7%': [2],
    }
    assert result['missing_anchors'] == ['27', '7%', '98', 'График согласован', 'Бюджет утверждён']
    assert result['forbidden_matches'] == {'127 участников': [1]}
    assert result['slide_count_delta'] == -1


def test_cli_can_run_a_batch_and_fails_for_missing_deck(tmp_path):
    write_deck(tmp_path / 'present.pptx')
    cases_path = tmp_path / 'cases.json'
    cases_path.write_text(json.dumps([
        {'id': 'present', 'anchors': ['127'], 'slideCount': 2},
        {'id': 'missing', 'anchors': ['12'], 'slideCount': 2},
    ]), encoding='utf-8')
    report_path = tmp_path / 'report.json'

    result = pptx_acceptance.main([
        '--cases', str(cases_path), '--pptx-dir', str(tmp_path), '--output', str(report_path),
    ])
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert result == 1
    assert [(case['id'], case['status']) for case in report] == [
        ('present', 'ok'), ('missing', 'error'),
    ]
    assert report[1]['error_type'] == 'FileNotFoundError'


def test_cli_can_check_native_table_and_chart_geometry(tmp_path):
    table = (
        '<a:tbl><a:tblGrid><a:gridCol w="1500000"/><a:gridCol w="1500000"/></a:tblGrid>'
        '<a:tr h="800000"/><a:tr h="1200000"/></a:tbl>'
    )
    chart = '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"/>'

    def frame(body, x, width):
        return (
            f'<p:graphicFrame><p:xfrm><a:off x="{x}" y="1500000"/>'
            f'<a:ext cx="{width}" cy="2000000"/></p:xfrm>'
            f'<a:graphic><a:graphicData>{body}</a:graphicData></a:graphic></p:graphicFrame>'
        )

    write_deck(
        tmp_path / 'graphics.pptx', graphics=frame(table, 600000, 2000000)
        + frame(chart, 11000000, 2000000),
    )
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([
        {'id': 'graphics', 'slideCount': 2, 'geometry': True},
    ]), encoding='utf-8')
    report_path = tmp_path / 'report.json'
    assert pptx_acceptance.main([
        '--cases', str(cases), '--pptx-dir', str(tmp_path), '--output', str(report_path),
    ]) == 1
    result, = json.loads(report_path.read_text(encoding='utf-8'))
    geometry = result['geometry']
    assert geometry['object_counts'] == {'table': 1, 'chart': 1}
    assert [(row['slide'], row['kind'], row['code']) for row in geometry['issues']] == [
        (2, 'table', 'table-grid-width'), (2, 'chart', 'outside-slide'),
    ]


def test_cli_respects_an_explicit_maximum_slide_budget(tmp_path):
    write_deck(tmp_path / 'short.pptx')
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([
        {'id': 'short', 'slideCount': 3, 'slide_count_mode': 'maximum'},
    ]), encoding='utf-8')
    report_path = tmp_path / 'report.json'
    assert pptx_acceptance.main([
        '--cases', str(cases), '--pptx-dir', str(tmp_path), '--output', str(report_path),
    ]) == 0
    result, = json.loads(report_path.read_text(encoding='utf-8'))
    assert result['actual_slides'] == 2 and result['slide_count_delta'] == -1
    assert result['status'] == 'ok'


def test_cli_compares_facts_when_both_decks_have_review_findings(tmp_path):
    folders = {}
    for name in ('before', 'after', 'source', 'before_doc', 'after_doc'):
        folders[name] = tmp_path / name
        folders[name].mkdir()
    write_deck(folders['before'] / 'trial.pptx', extra_paragraphs='Опрос не проводился.')
    write_deck(folders['after'] / 'trial.pptx', extra_paragraphs='График согласован.')
    blocks = {'blocks': [
        {'id': 'survey', 'kind': 'text', 'text': 'Опрос не проводился.'},
        {'id': 'schedule', 'kind': 'text', 'text': 'График согласован.'},
    ]}
    (folders['source'] / 'trial.json').write_text(
        json.dumps(blocks, ensure_ascii=False), encoding='utf-8',
    )
    for folder, evidence in (
        ('before_doc', 'Опрос не проводился.'), ('after_doc', 'График согласован.'),
    ):
        deck = {'title': 'Пилот', 'slides': [
            {'layout': 'title', 'title': 'Пилот'},
            {'layout': 'closing', 'title': 'Итоги', 'subtitle': evidence},
        ]}
        (folders[folder] / 'trial.json').write_text(
            json.dumps(deck, ensure_ascii=False), encoding='utf-8',
        )
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{
        'id': 'trial', 'slideCount': 2, 'forbidden_fragments': ['Опрос', 'График'], 'facts': [
        {'id': 'survey', 'source': 'Опрос не проводился.'},
        {'id': 'schedule', 'source': 'График согласован.'},
    ]}]), encoding='utf-8')
    report = tmp_path / 'report.json'
    assert pptx_acceptance.main([
        '--cases', str(cases), '--pptx-dir', str(folders['after']),
        '--source-dir', str(folders['source']), '--document-dir', str(folders['after_doc']),
        '--baseline-pptx-dir', str(folders['before']), '--baseline-document-dir',
        str(folders['before_doc']), '--output', str(report),
    ]) == 1
    result, = json.loads(report.read_text(encoding='utf-8'))
    comparison = result['comparison']
    assert result['status'] == comparison['baseline_status'] == 'review'
    assert comparison['status'] == 'compared'
    assert comparison['new_forbidden'] == ['График']
    assert comparison['resolved_forbidden'] == ['Опрос']
    assert comparison['fact_changes'] == [
        {
            'id': 'survey', 'before': 'present', 'after': 'missing:document',
            'direction': 'regression',
        },
        {
            'id': 'schedule', 'before': 'missing:document', 'after': 'present',
            'direction': 'improvement',
        },
    ]


def test_cli_keeps_current_result_when_baseline_is_missing(tmp_path):
    baseline_dir = tmp_path / 'baseline'
    baseline_dir.mkdir()
    write_deck(tmp_path / 'trial.pptx')
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'id': 'trial', 'slideCount': 2}]), encoding='utf-8')
    report = tmp_path / 'report.json'
    assert pptx_acceptance.main([
        '--cases', str(cases), '--pptx-dir', str(tmp_path),
        '--baseline-pptx-dir', str(baseline_dir), '--output', str(report),
    ]) == 1
    result, = json.loads(report.read_text(encoding='utf-8'))
    assert result['status'] == 'ok'
    assert result['comparison'] == {
        'status': 'unavailable',
        'baseline_status': 'error',
        'baseline_error': {'error_type': 'FileNotFoundError'},
    }


def test_traces_a_fact_across_source_document_and_pptx(tmp_path):
    write_deck(tmp_path / 'trial.pptx')
    source_dir = tmp_path / 'source'
    document_dir = tmp_path / 'document'
    source_dir.mkdir()
    document_dir.mkdir()
    source = {'blocks': [
        {'kind': 'text', 'id': 'method', 'page': 2, 'text': 'Сравнение без контроля.'},
        {'kind': 'table', 'id': 'counts', 'page': 4, 'rows': [['Всего', '127 участников']]},
        {'kind': 'text', 'id': 'survey', 'text': 'Опрос не проводился. Бюджет утверждён.'},
        {'kind': 'text', 'id': 'summary', 'text': 'Общий итог'},
    ]}
    document = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Общий итог'},
        {
            'layout': 'closing', 'title': '127 участников',
            'subtitle': 'Контрольная группа отсутствовала. Бюджет утверждён. 98,7%',
            'notes': 'Опрос не проводился.',
        },
    ]}
    manifest = [{'id': 'trial', 'slideCount': 2, 'facts': [
        {'id': 'control', 'source': 'без контроля', 'slide_phrases': [
            'без контроля', 'контрольная группа отсутствовала',
        ]},
        {'id': 'count', 'source': 'Всего 127 участников', 'slide_phrases': ['127 участников']},
        {'id': 'survey', 'source': 'Опрос не проводился'},
        {'id': 'budget', 'source': 'Бюджет утверждён'},
        {'id': 'rate', 'source': '98,7%'},
        {'id': 'literal', 'source': 'итог', 'match': 'exact'},
        {'id': 'cell', 'source': '127 участников', 'match': 'exact'},
        {'id': 'interior', 'source': '127 участников', 'placement': 'interior'},
        {'id': 'scoped', 'source': 'без контроля', 'slide_phrases': ['98,7%'],
         'slide_context': ['контрольная группа']},
    ]}]
    for path, value in [
        (source_dir / 'trial.json', source),
        (document_dir / 'trial.json', document),
        (tmp_path / 'cases.json', manifest),
    ]:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    report_path = tmp_path / 'report.json'
    argv = [
        '--cases', str(tmp_path / 'cases.json'), '--pptx-dir', str(tmp_path),
        '--source-dir', str(source_dir), '--document-dir', str(document_dir),
        '--output', str(report_path),
    ]
    assert pptx_acceptance.main(argv) == 1
    result, = json.loads(report_path.read_text(encoding='utf-8'))
    assert result['status'] == 'review'
    assert result['facts'] == [
        {'id': 'control', 'source_blocks': ['method'], 'document_slides': [2],
         'pptx_slides': [2], 'first_missing': None},
        {'id': 'count', 'source_blocks': ['counts'], 'document_slides': [2],
         'pptx_slides': [1], 'first_missing': None},
        {'id': 'survey', 'source_blocks': ['survey'], 'document_slides': [],
         'pptx_slides': [], 'first_missing': 'document'},
        {'id': 'budget', 'source_blocks': ['survey'], 'document_slides': [2],
         'pptx_slides': [], 'first_missing': 'pptx'},
        {'id': 'rate', 'source_blocks': [], 'document_slides': [2],
         'pptx_slides': [2], 'first_missing': 'source'},
        {'id': 'literal', 'source_blocks': [], 'document_slides': [],
         'pptx_slides': [], 'first_missing': 'source'},
        {'id': 'cell', 'source_blocks': ['counts'], 'document_slides': [2],
         'pptx_slides': [1], 'first_missing': None},
        {'id': 'interior', 'source_blocks': ['counts'], 'document_slides': [2],
         'pptx_slides': [1], 'first_missing': None, 'placement': 'interior',
         'document_interior_slides': [], 'pptx_interior_slides': [],
         'first_misplaced': 'document'},
        {'id': 'scoped', 'source_blocks': ['method'], 'document_slides': [2],
         'pptx_slides': [], 'first_missing': 'pptx', 'document_unscoped_slides': [],
         'pptx_unscoped_slides': [2]},
    ]

    (document_dir / 'trial.json').unlink()
    assert pptx_acceptance.main(argv) == 1
    assert json.loads(report_path.read_text(encoding='utf-8')) == [
        {'id': 'trial', 'status': 'error', 'stage': 'document', 'error_type': 'FileNotFoundError'},
    ]


@pytest.mark.parametrize('facts', [
    [{'id': 'rate', 'source': '98,7%', 'slide_phrases': '98,7%'}],
    [{'id': 'rate', 'source': '98,7%', 'slide_phrases': []}],
    [{'id': 'rate', 'source': '98,7%', 'slide_context': 'участники'}],
    [{'id': 'rate', 'source': '98,7%'}, {'id': 'rate', 'source': '15%'}],
])
def test_invalid_fact_manifest_is_an_input_error(tmp_path, facts):
    cases_path = tmp_path / 'cases.json'
    cases_path.write_text(json.dumps([{'id': 'trial', 'slideCount': 2, 'facts': facts}]))
    report_path = tmp_path / 'report.json'
    assert pptx_acceptance.main([
        '--cases', str(cases_path), '--pptx-dir', str(tmp_path), '--output', str(report_path),
        '--source-dir', str(tmp_path), '--document-dir', str(tmp_path),
    ]) == 1
    assert json.loads(report_path.read_text(encoding='utf-8')) == [
        {'id': 'trial', 'status': 'error', 'stage': 'facts', 'error_type': 'ValueError'},
    ]
