from presentation_ml.grounding import recognize_entities, select_source_passages


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
