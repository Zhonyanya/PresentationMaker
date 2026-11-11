from presentation_ml.grounding import (
    recognize_entities,
    select_page_passages,
    select_source_passages,
)


def test_recognize_explicit_russian_entities():
    source = 'Анна Петрова встретилась с ООО «Вектор» 15 мая 2025 года.'
    assert recognize_entities(source) == [
        ('person', 'Анна Петрова'),
        ('organization', 'ООО «Вектор»'),
        ('date', '15 мая 2025 года'),
    ]


def test_entity_ranking_keeps_source_condition():
    source = (
        'В приложении указаны пункты 1, 2 и 3.\n\n'
        'ООО «Вектор» не согласовало запуск до 15 мая 2025 года.'
    )
    assert select_source_passages(source, limit=1) == [
        'ООО «Вектор» не согласовало запуск до 15 мая 2025 года.',
    ]


def test_pdf_prefers_reported_outcome_over_dates_and_reference_numbers():
    outcome = 'По итогам года охват вырос с 62 до 71 процента.'
    passages = select_page_passages([
        (4, 'В соответствии с приказом от 15 мая 2025 года № 37 и пунктами 1, 2, 3.'),
        (5, outcome),
    ], limit=1)
    assert [(passage.page_number, passage.text) for passage in passages] == [(5, outcome)]
