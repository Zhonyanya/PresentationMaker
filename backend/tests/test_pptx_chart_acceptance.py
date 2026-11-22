import json
from zipfile import ZipFile

import pytest
from test_pptx_acceptance import (
    DRAWING,
    OFFICE_REL,
    PACKAGE_REL,
    PRESENTATION,
    write_deck,
)

from tools.pptx_acceptance import main

CHART = 'http://schemas.openxmlformats.org/drawingml/2006/chart'


def _points(values):
    return ''.join(f'<c:pt idx="{index}"><c:v>{value}</c:v></c:pt>'
                   for index, value in enumerate(values))


def _chart(values, format_code):
    categories = _points(['Север', 'Юг'])

    def series(period, row):
        return (
            '<c:ser>'
            f'<c:tx><c:strRef><c:strCache>{_points([period])}</c:strCache></c:strRef></c:tx>'
            f'<c:cat><c:strRef><c:strCache>{categories}</c:strCache></c:strRef></c:cat>'
            f'<c:val><c:numRef><c:numCache>{_points(row)}</c:numCache></c:numRef></c:val>'
            '</c:ser>'
        )

    return (
        f'<c:chartSpace xmlns:c="{CHART}"><c:chart><c:plotArea><c:barChart>'
        f'{series("2024", values[0])}{series("2025", values[1])}'
        f'<c:dLbls><c:numFmt formatCode="{format_code}"/><c:showVal val="1"/></c:dLbls>'
        f'</c:barChart><c:valAx><c:numFmt formatCode="{format_code}"/></c:valAx>'
        '</c:plotArea></c:chart></c:chartSpace>'
    )


def _write_chart_deck(path, values, format_code, table=False):
    with ZipFile(path, 'w') as output:
        skeleton = path.with_name('skeleton.pptx')
        write_deck(skeleton)
        with ZipFile(skeleton) as original:
            for part in original.namelist():
                data = original.read(part)
                if part == 'ppt/presentation.xml':
                    data = data.replace(
                        b'</p:sldIdLst>', b'<p:sldId id="258" r:id="rId3"/></p:sldIdLst>',
                    )
                elif part == 'ppt/_rels/presentation.xml.rels':
                    data = data.replace(b'</Relationships>', (
                        f'<Relationship Id="rId3" Type="{OFFICE_REL}/slide" '
                        'Target="slides/slide1.xml"/></Relationships>'
                    ).encode())
                if part != 'ppt/slides/slide2.xml':
                    output.writestr(part, data)
        if table:
            rows = [['Группа', '2024', '2025'], ['Север', *values[0]], ['Юг', *values[1]]]
            body = '<a:tbl>' + ''.join(
                '<a:tr>' + ''.join(
                    f'<a:tc><a:txBody><a:p><a:r><a:t>{cell}</a:t></a:r></a:p></a:txBody></a:tc>'
                    for cell in row
                ) + '</a:tr>'
                for row in rows
            ) + '</a:tbl>'
        else:
            body = '<c:chart r:id="rId6"/>'
            output.writestr('ppt/slides/_rels/slide2.xml.rels', (
                f'<Relationships xmlns="{PACKAGE_REL}">'
                f'<Relationship Id="rId6" Type="{OFFICE_REL}/chart" '
                'Target="../charts/chart9.xml"/></Relationships>'
            ))
        output.writestr('ppt/slides/slide2.xml', (
            f'<p:sld xmlns:p="{PRESENTATION}" xmlns:a="{DRAWING}" xmlns:c="{CHART}" '
            f'xmlns:r="{OFFICE_REL}"><p:cSld><p:spTree><p:graphicFrame>'
            f'<a:graphic><a:graphicData>{body}</a:graphicData></a:graphic>'
            '</p:graphicFrame></p:spTree></p:cSld></p:sld>'
        ))
        output.writestr('ppt/charts/chart1.xml', _chart([[99, 99], [99, 99]], format_code))
        output.writestr('ppt/charts/chart9.xml', _chart(values, format_code))


@pytest.mark.parametrize(('scenario', 'first_mismatch', 'issue'), [
    ('aligned', None, None),
    ('wrong-source-row', 'source', None),
    ('changed-document', 'document', 'values'),
    ('swapped-series', 'pptx', 'values'),
    ('missing-percent', 'pptx', 'unit'),
    ('rounded-label', 'pptx', 'display_precision'),
    ('table-fallback', None, None),
    ('table-wrong-value', 'pptx', 'values'),
    ('coverage-gap', None, None),
])
def test_chart_matches_source_rows(tmp_path, scenario, first_mismatch, issue):
    chart = {
        'kind': 'comparison', 'unit': '%', 'categories': ['Север', 'Юг'],
        'series': [{'label': '2024', 'values': [12.5, 25]}, {'label': '2025', 'values': [18, 24]}],
    }
    values = [[18, 24], [12.5, 25]] if scenario == 'swapped-series' else [[12.5, 25], [18, 24]]
    format_code = {
        'missing-percent': '0.#',
        'rounded-label': '0&quot;%&quot;',
    }.get(scenario, '0.#&quot;%&quot;')
    is_table = scenario.startswith('table-')
    if is_table:
        values = [['12,5%', '18%'], ['25%', '0%' if scenario == 'table-wrong-value' else '24%']]
    _write_chart_deck(tmp_path / 'trial.pptx', values, format_code, table=is_table)
    source_dir = tmp_path / 'source'
    document_dir = tmp_path / 'document'
    source_dir.mkdir()
    document_dir.mkdir()
    if scenario == 'changed-document':
        chart['series'][0]['values'][0] = 99
    source = {'blocks': [{'kind': 'table', 'id': 'table-1', 'rows': [
        ['Группа', 'Доля', None],
        [None, '2024', '2025'],
        ['Север', '12,5%', '18%'],
        ['Юг', '25%', '24%'],
    ]}]}
    if scenario == 'coverage-gap':
        source['blocks'][0]['rows'].append(['Центр', '30%', '32%'])
    document = {'title': 'Пилот', 'slides': [
        {'layout': 'title', 'title': 'Пилот'},
        {'layout': 'text', 'title': 'Доля', 'body': '', 'composition': chart},
        {'layout': 'closing', 'title': 'Итоги'},
    ]}
    manifest = [{'id': 'trial', 'slideCount': 3, 'charts': [{
        'slide': 2, 'source_block': 'table-1',
        'rows': [3, 5 if scenario == 'wrong-source-row' else 4],
        'periods': ['2024', '2025'],
        'allow_table': is_table,
    }]}]
    if scenario == 'coverage-gap':
        manifest[0]['chart_coverage'] = [{'source_block': 'table-1', 'periods': ['2024', '2025']}]
    for path, value in [
        (source_dir / 'trial.json', source),
        (document_dir / 'trial.json', document),
        (tmp_path / 'cases.json', manifest),
    ]:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    report_path = tmp_path / 'report.json'
    code = main([
        '--cases', str(tmp_path / 'cases.json'), '--pptx-dir', str(tmp_path),
        '--source-dir', str(source_dir), '--document-dir', str(document_dir),
        '--output', str(report_path),
    ])
    assert code == int(first_mismatch is not None or scenario == 'coverage-gap')
    result, = json.loads(report_path.read_text(encoding='utf-8'))
    check, = result['charts']
    assert check['first_mismatch'] == first_mismatch
    assert check['document_issues'] == ([issue] if first_mismatch == 'document' else [])
    assert check['pptx_issues'] == ([issue] if first_mismatch == 'pptx' else [])
    if scenario == 'coverage-gap':
        coverage, = result['chart_coverage']
        assert coverage['expected_rows'] == [3, 4, 5]
        assert coverage['unassigned_rows'] == [5]
        assert coverage['failed_rows'] == []
