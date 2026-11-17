from presentation_ml.grounding import select_source_passages
from presentation_ml.knowledge_graph import (
    ReportTable,
    build_knowledge_graph,
    table_comparison_slide,
)


def test_entities_reuse_explicit_alias_and_preserve_status_and_evidence():
    first = (
        'МБОУ «Школа № 12» (далее — «Школа 12») '
        'участвует в программе «Пилот» с сентября 2025 года.'
    )
    planned = '«Школа 12» планирует участвовать в программе «Расширение».'
    denied = '«Школа 12» не участвует в программе «Резерв».'
    graph = build_knowledge_graph([(4, first), (5, planned + ' ' + denied)])
    nodes = {node.id: node for node in graph.nodes}
    assert len(graph.edges) == 3
    assert len({edge.subject for edge in graph.edges}) == 1
    assert nodes[graph.edges[0].subject].name == 'МБОУ «Школа № 12»'
    assert [(nodes[e.target].name, e.status, e.page, e.quote) for e in graph.edges] == [
        ('Пилот', 'reported', 4, first),
        ('Расширение', 'planned', 5, planned),
        ('Резерв', 'denied', 5, denied),
    ]


def test_cooccurrence_and_undeclared_short_names_do_not_create_edges():
    graph = build_knowledge_graph([(1,
        'ООО «Вектор» и программа «Пилот» упомянуты в приложении. '
        '«Вектор» участвует в программе «Пилот».',
    )])
    assert not graph.edges


def test_numeric_change_keeps_period_scope_and_unit():
    text = 'ООО «Вектор» увеличило охват с 62% до 71% в 2025 году в пилотных школах.'
    graph = build_knowledge_graph([(7, text)])
    (edge,) = graph.edges
    assert (edge.relation, edge.status, edge.page, edge.quote) == (
        'metric_change', 'reported', 7, text,
    )
    assert dict(edge.qualifiers) == {
        'before': '62', 'after': '71', 'unit': '%',
        'period': '2025 году', 'scope': 'в пилотных школах',
    }


def test_offline_selection_comparison_on_hand_labeled_example():
    text = (
        'ООО «Альфа» и АО «Бета» указаны в приложении от 10 мая 2025 года.\n\n'
        'ООО «Вектор» участвует в программе «Пилот» с сентября 2025 года.\n\n'
        'ООО «Альфа» и АО «Бета» перечислены в приказе от 11 мая 2025 года.\n\n'
        'ООО «Вектор» не участвует в программе «Расширение».'
    )
    expected = {('Пилот', 'reported'), ('Расширение', 'denied')}
    passages = select_source_passages(text, limit=2)
    baseline = build_knowledge_graph((None, part) for part in passages)
    graph = build_knowledge_graph([(None, text)])

    def relations(candidate, edges):
        nodes = {node.id: node.name for node in candidate.nodes}
        return {(nodes[edge.target], edge.status) for edge in edges}

    assert relations(baseline, baseline.edges) == set()
    assert relations(graph, graph.select_edges(limit=2)) == expected


def test_ambiguous_alias_is_not_used_as_a_subject():
    graph = build_knowledge_graph([(None,
        'ООО «Вектор» (далее — «Оператор») отвечает за реализацию программы «Пилот». '
        'АО «Спектр» (далее — «Оператор») отвечает за реализацию программы «Резерв». '
        '«Оператор» участвует в программе «Расширение».',
    )])
    assert [edge.relation for edge in graph.edges] == ['responsible_for', 'responsible_for']
    assert not any(node.aliases for node in graph.nodes)


def test_explicit_references_link_a_topic_to_its_figure_and_table():
    quote = 'Динамика записи на кружки представлена на диаграмме 3 и в таблице 8.'
    unrelated = 'На этой странице также упоминаются рисунок 10 и таблица 20.'
    graph = build_knowledge_graph([(6, f'{quote} {unrelated}')])
    nodes = {node.id: node for node in graph.nodes}
    assert [
        (nodes[edge.subject].name, edge.relation, nodes[edge.target].name, edge.page, edge.quote)
        for edge in graph.edges
    ] == [
        ('Динамика записи на кружки', 'illustrated_by', 'Диаграмма 3', 6, quote),
        ('Динамика записи на кружки', 'tabulated_in', 'Таблица 8', 6, quote),
    ]


def test_merged_year_header_preserves_comparison_and_exact_table_row():
    row = ('1.', 'Городские школы', '1 230', '1 450')
    table = ReportTable(8, '4', (
        ('Номер строки', 'Группа', 'Количество участников', None),
        (None, None, '2022 год', '2023 год'),
        row,
        ('2.', 'Сельские школы', '—', '120'),
    ))
    graph = build_knowledge_graph([], tables=[table])
    (edge,) = graph.edges
    assert edge.relation == 'metric_comparison'
    assert edge.page == 8 and edge.table_row == row
    slide = table_comparison_slide(graph, edge)
    assert slide['title'] == 'Количество участников · стр. 8'
    assert slide['body'] == 'Городские школы\n2022 — 1 230\n2023 — 1 450'
    assert 'таблица 4' in slide['notes']
