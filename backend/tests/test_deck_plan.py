from datetime import UTC, datetime, timedelta

import pytest

import presentation_ml

SOURCE = {"blocks": [
    {"kind": "text", "id": "p1-text", "page": 1,
     "text": "Архив открыт по предварительной записи."},
    {"kind": "text", "id": "p2-text", "page": 2,
     "text": "В субботу выдача заканчивается в 14:00."},
]}


def intent(takeaway, *evidence_ids, visual_kind="text"):
    return {"goal": "Объяснить порядок доступа", "takeaway": takeaway,
            "visual_intent": "Порядок посещения", "visual_kind": visual_kind,
            "evidence_ids": list(evidence_ids)}


def planned_generation(monkeypatch, reply, *, slide_count=5, inspect_request=None, source=SOURCE):
    monkeypatch.setenv("PM_ML_PROMPT_VERSION", "v4")
    calls = []

    def respond(**request):
        calls.append(request)
        if inspect_request:
            inspect_request(request)
        return reply

    monkeypatch.setattr(presentation_ml, "request_document", respond)
    result = presentation_ml._generate(
        text="", source=source, slideCount=slide_count, job_id="test",
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert len(calls) == 1
    return result


def test_generation_binds_intent_to_source_without_graph_facts(monkeypatch):
    def inspect(request):
        assert "предварительной записи" in request["payload"]["text"]
        anchors = request["payload"]["source_anchors"]
        assert [anchor["source"]["block_id"] for anchor in anchors] == ["p1-text", "p2-text"]
        assert "plan" in request["schema"]["required"]
        assert "2–4 конкретные детали в видимом тексте" in request["system"]
        assert "Не своди разные случаи к общему тезису" in request["system"]
        assert "Не прячь существенные условия в notes" in request["system"]
        assert "Не оставляй такие условия только для финального слайда" in request["system"]

    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Правила доступа"), intent("Требуется запись", "block-1"),
                 intent("Проверьте время выдачи", "block-2")],
        "slides": [
            {"layout": "title", "title": "Архив"},
            {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            {"layout": "closing", "title": "Порядок доступа", "subtitle": "Выдача до 14:00."},
        ],
    }, inspect_request=inspect)
    assert set(result.document) == {"title", "slides"}
    assert [s.slide_id for s in result.plan.slides] == [s["id"] for s in result.document["slides"]]
    (content,) = result.plan.slides[1].intents
    assert content.goal == "Объяснить порядок доступа"
    assert content.takeaway == "Требуется запись"
    assert content.visual_intent == "Порядок посещения"
    (evidence,) = content.evidence
    assert (evidence.id, evidence.block_id, evidence.page) == ("block-1", "p1-text", 1)


def test_planned_generation_carries_opening_figures_and_literal_definitions(monkeypatch):
    source = {"blocks": [
        {"kind": "text", "id": "intro", "page": 1, "text": "Introduction"},
        {"kind": "text", "id": "programme", "page": 1,
         "text": "School-Led Tutoring (SLT) was subsidised at 75% in its first year."},
        {"kind": "text", "id": "eligibility", "page": 1,
         "text": "Eligibility included pupils receiving pupil premium (PP)."},
        {"kind": "text", "id": "findings", "page": 2, "text": "Results"},
        {"kind": "text", "id": "results", "page": 2,
         "text": "The effect was modest across the monitored schools."},
        {"kind": "text", "id": "recommendations", "page": 3, "text": "Recommendations"},
        {"kind": "text", "id": "next", "page": 3,
         "text": "Record tutoring routes and subjects separately."},
    ]}

    def inspect(request):
        review = request["payload"]["review_sections"]
        assert review["context"][0] == source["blocks"][1]["text"]
        assert review["proposed"] == [source["blocks"][-1]["text"]]
        assert request["payload"]["source_glossary"] == [
            {"abbreviation": "SLT", "definition": "School-Led Tutoring",
             "source": {"block_id": "programme", "page": 1}},
            {"abbreviation": "PP", "definition": "pupil premium",
             "source": {"block_id": "eligibility", "page": 1}},
        ]
        assert "source_glossary" in request["system"]

    planned_generation(monkeypatch, {
        "title": "Оценка программы",
        "plan": [intent("Результаты", "block-5")],
        "slides": [{"layout": "text", "title": "Результаты", "body": "Эффект был небольшим."}],
    }, source=source, inspect_request=inspect)


@pytest.mark.parametrize("evidence_ids", [("invented",), ()])
def test_generation_rejects_unresolved_evidence_on_content_slide(monkeypatch, evidence_ids):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("Требуется запись", *evidence_ids)],
            "slides": [{"layout": "text", "title": "Запись", "body": "Запишитесь заранее."}],
        })


def test_generation_renders_exact_numeric_source_paragraph_before_filling_closing(monkeypatch):
    paragraph = ("Журнал был недоступен 9–11 декабря. После восстановления в сводку "
                 "вернули 11 записей о завершённых занятиях.")
    source = {"blocks": [{"kind": "text", "id": "journal", "page": 2, "text": paragraph},
                         {"kind": "text", "id": "reference",
                          "text": "Distance travelled [NTS0101] Average time [NTS0101]"},
                         {"kind": "text", "id": "limits", "text": "Данные требуют оговорки."}]}

    def inspect(request):
        assert request["payload"]["verbatim_blocks"] == ["block-1"]
        assert "[block-1]\n" + paragraph in request["payload"]["text"]
        assert "[block-2]\nDistance travelled [NTS0101]" in request["payload"]["text"]
        proposal = request["schema"]["properties"]["plan"]["items"]["properties"]
        assert proposal["verbatim_block_ids"]["items"]["enum"] == ["block-1"]

    result = planned_generation(monkeypatch, {
        "title": "Занятия",
        "plan": [{**intent("Ограничения учёта", "block-1", "block-3"),
                  "verbatim_block_ids": ["block-1"]}],
        "slides": [{"id": "journal-slide", "layout": "text", "title": "Учёт",
                    "body": "Данные требуют оговорки."}],
    }, source=source, inspect_request=inspect)
    _, content, closing = result.document["slides"]
    assert content["id"] == "journal-slide"
    assert content["body"] == "Данные требуют оговорки.\n\n" + paragraph
    assert paragraph in closing["subtitle"]
    assert result.plan.slides[1].intents[0].evidence[0].block_id == "journal"


def test_planned_v4_can_preserve_a_short_nonnumeric_limitation_verbatim(monkeypatch):
    source = {"blocks": [
        {"kind": "text", "id": "summary", "text": "Отзывы участников собрали на общем обсуждении."},
        {"kind": "text", "id": "limits", "text": "Ограничения"},
        {"kind": "text", "id": "survey-limit", "text": "Опрос не проводили."},
        {"kind": "text", "id": "next", "text": "Следующий этап"},
        {"kind": "text", "id": "decision", "text": "Решение обсудят на общем заседании."},
    ]}

    def inspect(request):
        assert request["payload"]["review_sections"]["limitations"] == ["Опрос не проводили."]
        assert request["payload"]["verbatim_blocks"] == ["block-3"]

    result = planned_generation(monkeypatch, {
        "title": "Отзывы",
        "plan": [{**intent("Границы наблюдений", "block-3"), "verbatim_block_ids": ["block-3"]}],
        "slides": [{"layout": "text", "title": "Границы наблюдений",
                    "body": "Был проведён опрос всех участников."}],
    }, source=source, inspect_request=inspect)
    assert result.document["slides"][1]["body"] == "Опрос не проводили."
    assert result.plan.slides[1].intents[0].evidence[0].block_id == "survey-limit"


@pytest.mark.parametrize(("ids", "layout"), [
    (["block-2"], "text"),
    (["block-3"], "text"),
    (["block-1"], "title"),
])
def test_generation_validates_verbatim_references(monkeypatch, ids, layout):
    source = {"blocks": [
        {"kind": "text", "id": "journal", "text": "В отчёт вернули 11 старых записей о занятиях."},
        {"kind": "text", "id": "notes", "text": "Обсуждение всё ещё продолжается."},
    ]}
    with pytest.raises(ValueError, match="verbatim"):
        planned_generation(monkeypatch, {
            "title": "Занятия",
            "plan": [{**intent("Учёт", "block-1"), "verbatim_block_ids": ids}],
            "slides": [{"layout": layout, "title": "Учёт", "body": ""}],
        }, source=source)


def test_generation_prints_a_repeated_valid_verbatim_reference_once(monkeypatch):
    paragraph = "В отчёт вернули 11 старых записей о занятиях."
    result = planned_generation(monkeypatch, {
        "title": "Занятия",
        "plan": [{**intent("Учёт"), "verbatim_block_ids": ["block-1", "block-1"]}],
        "slides": [{"layout": "text", "title": "Учёт", "body": ""}],
    }, source={"blocks": [{"kind": "text", "id": "journal", "text": paragraph}]})

    assert result.document["slides"][1]["body"] == paragraph
    (proposal,) = result.plan.slides[1].intents
    assert proposal.verbatim_block_ids == ("block-1",)
    assert [address.block_id for address in proposal.evidence] == ["journal"]


def test_generation_can_print_a_verbatim_paragraph_in_the_closing(monkeypatch):
    paragraph = "После восстановления в сводку вернули 11 записей о завершённых занятиях."
    result = planned_generation(monkeypatch, {
        "title": "Занятия",
        "plan": [intent("Обзор", "block-1"),
                 {**intent("Ограничения учёта"), "verbatim_block_ids": ["block-1"]}],
        "slides": [{"layout": "text", "title": "Учёт", "body": "Сверили сводку."},
                   {"layout": "closing", "title": "Итог", "subtitle": "Продолжим сверку."}],
    }, source={"blocks": [{"kind": "text", "id": "journal", "text": paragraph}]})
    assert result.document["slides"][-1]["subtitle"] == paragraph


def test_verbatim_final_block_preserves_may_decision_without_repeating_its_summary(monkeypatch):
    decision = ("На май утверждён порог учёта остановок две минуты для всех машин. "
                "Обновление двух других датчиков пока не согласовано. "
                "Замена датчика обошлась в 38 тысяч рублей. Окупаемость пока не оценивали.")
    draft = ("Согласовали общий порог регистрации для всех машин на май. "
             "Решение об обновлении двух оставшихся датчиков ещё не принято. "
             "До оценки окупаемости известна только стоимость замены. "
             "Обновление остальных датчиков потребует отдельного решения.")
    assert len(decision + draft) > 400
    source = {"blocks": [
        {"kind": "text", "id": "observations", "text": "Наблюдение после замены длилось два дня."},
        {"kind": "text", "id": "plans", "text": decision},
    ]}
    deck = planned_generation(monkeypatch, {
        "title": "Участок упаковки",
        "plan": [intent("Тема"), intent("Наблюдения", "block-1"),
                 {**intent("Действия", "block-2"), "verbatim_block_ids": ["block-2"]}],
        "slides": [
            {"layout": "title", "title": "Участок упаковки"},
            {"layout": "text", "title": "Наблюдения", "body": "Наблюдение длилось два дня."},
            {"id": "may", "layout": "text", "title": "Планы на май", "body": draft,
             "notes": "Проверено по докладу."},
        ],
    }, source=source, slide_count=3)
    _, observations, closing = deck.document["slides"]
    assert observations["body"] == "Наблюдение длилось два дня."
    assert closing == {"id": "may", "layout": "closing", "title": "Планы на май",
                       "subtitle": decision, "notes": "Проверено по докладу."}
    assert deck.plan.slides[-1].intents[0].evidence[0].block_id == "plans"


@pytest.mark.parametrize("long_source", [False, True])
def test_compaction_preserves_intents_and_binds_inserted_boundaries(monkeypatch, long_source):
    first, second = SOURCE["blocks"]
    source = {"blocks": [{**first, "text": first["text"] + " Справки в архиве." * 100}, second]}
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Требуется запись", "block-1"),
                 intent("Выдача до 14:00", "block-2")],
        "slides": [
            {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            {"layout": "text", "id": "saturday", "title": "Суббота", "body": "Выдача до 14:00."},
        ],
    }, slide_count=3, source=source if long_source else SOURCE)
    slides = result.document["slides"]
    assert [slide["layout"] for slide in slides] == ["title", "text", "closing"]
    assert [slide.slide_id for slide in result.plan.slides] == [slide["id"] for slide in slides]
    assert [part.takeaway for part in result.plan.slides[1].intents] == ["Требуется запись"]
    assert slides[1]["body"] == "Запишитесь заранее."
    assert slides[2]["id"] == "saturday"
    assert slides[2]["subtitle"] == "Выдача до 14:00."
    assert result.plan.slides[2].intents[0].evidence[0].block_id == "p2-text"


@pytest.mark.parametrize(("variant", "expected"), [
    ("partial", "Запись в 2025 году сохранялась."),
    ("uncited", "Запись в 205 году сохранялась."),
    ("ambiguous", "Запись в 205 году сохранялась."),
    ("other_words", "Запись в 205 году прекращалась."),
    ("full_year", "Запись в 2026 году сохранялась."),
])
def test_generation_restores_a_truncated_year_only_from_unambiguous_evidence(
    monkeypatch, variant, expected,
):
    sentence = {
        "other_words": "Запись в 205 году прекращалась.",
        "full_year": "Запись в 2026 году сохранялась.",
    }.get(variant, "Запись в 205 году сохранялась.")
    source = {"blocks": [
        {"kind": "text", "id": "rule", "text": "Условия. Запись в 2025 году сохранялась."},
        {"kind": "text", "id": "other", "text": "Запись в 2005 году сохранялась."
         if variant == "ambiguous" else "Приходите вовремя."},
    ]}
    ids = ["block-2"] if variant == "uncited" else ["block-1", "block-2"]
    result = planned_generation(monkeypatch, {
        "title": "Учёт",
        "plan": [intent("Условия", *ids)],
        "slides": [{"layout": "text", "title": "Запись", "body": f"Вводная. {sentence}"}],
    }, source=source)
    assert result.document["slides"][1]["body"] == f"Вводная. {expected}"


def test_joined_heading_keeps_the_heading_and_content_intents(monkeypatch):
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Правила доступа"), intent("Требуется запись", "block-1")],
        "slides": [
            {"layout": "section", "title": "Правила доступа"},
            {"layout": "text", "title": "", "body": "Запишитесь заранее."},
        ],
    })
    joined = result.plan.slides[1]
    assert joined.slide_id == result.document["slides"][1]["id"]
    assert [part.takeaway for part in joined.intents] == ["Правила доступа", "Требуется запись"]


def test_evidence_can_reference_a_block_outside_the_excerpt_sample(monkeypatch):
    source = {"blocks": [
        {"kind": "text", "id": f"p{i}", "text": f"Справочная запись номер {i}."}
        for i in range(1, 41)
    ]}

    def inspect(request):
        payload = request["payload"]
        assert "block-5" not in {item["id"] for item in payload["source_anchors"]}
        assert "[block-5]\nСправочная запись номер 5." in payload["text"]

    result = planned_generation(monkeypatch, {
        "title": "Справочник",
        "plan": [intent("Справочная запись", "block-5")],
        "slides": [{"layout": "text", "title": "Запись", "body": "Справочная запись номер 5."}],
    }, source=source, inspect_request=inspect)
    assert result.plan.slides[1].intents[0].evidence[0].block_id == "p5"


def test_evidence_addresses_the_end_of_a_long_text_block(monkeypatch):
    tail = "Заявки на отпуск принимаются до 14:00."
    full_text = "Справочная информация. " * 64 + tail
    source = {"blocks": [{"kind": "text", "id": "text-1", "text": full_text}]}

    def inspect(request):
        text = request["payload"]["text"]
        assert "[block-1-part-2]" in text
        assert text.endswith(tail)

    result = planned_generation(monkeypatch, {
        "title": "Порядок подачи",
        "plan": [intent("Срок подачи", "block-1-part-2")],
        "slides": [{"layout": "text", "title": "Срок", "body": tail}],
    }, source=source, inspect_request=inspect)
    (ref,) = result.plan.slides[1].intents[0].evidence
    assert ref.block_id == "text-1"
    assert 0 < ref.start < ref.end == len(full_text)
    assert full_text[ref.start:ref.end].endswith(tail)


@pytest.mark.parametrize("layout", ["section", "closing", "title"])
def test_boundary_with_substantive_subtitle_requires_evidence(monkeypatch, layout):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("В 14:00"), intent("Требуется запись", "block-1")],
            "slides": [
                {"layout": layout, "title": "Часы работы", "subtitle": "Выдача до 14:00."},
                {"layout": "text", "title": "Запись", "body": "Запишитесь заранее."},
            ],
        })


def test_compaction_rejects_content_without_evidence_even_after_layout_changes(monkeypatch):
    with pytest.raises(ValueError, match="evidence"):
        planned_generation(monkeypatch, {
            "title": "Архив",
            "plan": [intent("Введение"), intent("Суббота"), intent("Итог", "block-2")],
            "slides": [
                {"layout": "section", "title": "Введение"},
                {"layout": "section", "title": "Суббота"},
                {"layout": "closing", "title": "Часы работы", "subtitle": "Выдача до 14:00."},
            ],
        }, slide_count=3)


@pytest.mark.parametrize("visual_kind", ["comparison", "text"])
def test_plan_comparison_requires_explicit_intent(monkeypatch, visual_kind):
    source = {"blocks": [{
        "kind": "table", "id": "p1-table-1", "page": 1,
        "rows": [["Группа", "Завершённые занятия", None], [None, "2024", "2025"],
                 ["Северная", "48", "63"], ["Центральная", "72", "69"]],
    }]}
    result = planned_generation(monkeypatch, {
        "title": "Пилот",
        "plan": [intent("Число занятий изменилось", "fact-2", "fact-1", visual_kind=visual_kind)],
        "slides": [{"layout": "section", "title": "Две площадки", "subtitle": "Итоги пилота"}],
    }, source=source)
    slide = result.document["slides"][1]
    if visual_kind == "text":
        assert slide["layout"] == "section"
        assert "composition" not in slide
        return
    assert slide["layout"] == "text" and slide["body"] == "Итоги пилота"
    assert slide["id"] == result.plan.slides[1].slide_id
    assert slide["composition"] == {
        "kind": "comparison",
        "categories": ["Северная", "Центральная"],
        "series": [{"label": "2024", "values": [48, 72]}, {"label": "2025", "values": [63, 69]}],
    }


def test_plan_metric_copies_verified_row_and_preserves_context(monkeypatch):
    source = {"blocks": [{
        "kind": "table", "id": "p1-table-1", "page": 1,
        "rows": [["Группа", "Доля ответов", None], [None, "2024", "2025"],
                 ["Онлайн", "48 %", "63 %"]],
    }]}
    result = planned_generation(monkeypatch, {
        "title": "Пилот",
        "plan": [intent("Ответы онлайн", "fact-1", visual_kind="metric")],
        "slides": [{"layout": "text", "title": "Онлайн", "body": "Электронная форма."}],
    }, source=source)
    slide = result.document["slides"][1]
    assert slide["body"] == "Электронная форма."
    assert slide["composition"] == {"kind": "metric", "values": [
        {"label": "Доля ответов · Онлайн · 2024", "value": "48 %"},
        {"label": "Доля ответов · Онлайн · 2025", "value": "63 %"},
    ]}


@pytest.mark.parametrize(("kind", "body", "expected"), [
    ("lead", "Главный вывод.\nОснование и условия вывода.", "lead"),
    ("blocks", "Первое наблюдение.\nВторое наблюдение.", "blocks"),
    ("steps", "Подать заявку.\nПолучить подтверждение.\nЗабрать документы.", "steps"),
    ("steps", "Один факт без последовательности.", None),
])
def test_plan_assigns_text_composition_without_rewriting_text(monkeypatch, kind, body, expected):
    def inspect(request):
        assert "textStyle" not in request["schema"]["$defs"]["TextSlide"]["properties"]

    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Объяснить порядок доступа", "block-1", visual_kind=kind)],
        "slides": [{"layout": "text", "title": "Условия", "body": body, "textStyle": "steps"}],
    }, inspect_request=inspect)
    slide = result.document["slides"][1]
    assert slide["body"] == body
    assert slide.get("textStyle") == expected


@pytest.mark.parametrize("outline_is_supported", [True, False])
def test_plan_applies_tree_only_to_supported_branches(monkeypatch, outline_is_supported):
    body = ("Сервисы библиотеки\nЧитальный зал\n  Работа с подлинниками.\n"
            "Удалённый доступ\n  Запрос копий.")
    outline = body.replace("\n  ", "\n- ")
    if not outline_is_supported:
        outline = outline.replace("Работа с подлинниками.", "Запрос копий.", 1)
        outline = outline.rsplit("Запрос копий.", 1)[0] + "Работа с подлинниками."
    source = {"blocks": [
        {"kind": "text", "id": "outline", "text": outline},
    ]}
    result = planned_generation(monkeypatch, {
        "title": "Услуги",
        "plan": [intent("Перечислить сервисы", "block-1", visual_kind="tree")],
        "slides": [{"layout": "text", "title": "Каналы обслуживания", "body": body}],
    }, source=source)
    slide = result.document["slides"][1]
    assert slide["body"] == body
    assert slide.get("textStyle") == ("tree" if outline_is_supported else None)


def test_tree_can_cite_a_source_block_for_each_node(monkeypatch):
    lines = ["Сервисы библиотеки"]
    for label in ("Читальный зал", "Удалённый доступ", "Межбиблиотечный обмен"):
        lines.extend([label, "  Первое действие.", "  Второе действие."])
    source = {"blocks": [
        {"kind": "text", "id": f"line-{index}", "text": line.replace("  ", "- ", 1)}
        for index, line in enumerate(lines, 1)
    ]}
    ids = [f"block-{index}" for index in range(1, len(lines) + 1)]
    result = planned_generation(monkeypatch, {
        "title": "Услуги",
        "plan": [intent("Перечислить сервисы", *ids, visual_kind="tree")],
        "slides": [{"layout": "text", "title": "Каналы обслуживания", "body": "\n".join(lines)}],
    }, source=source)
    assert result.document["slides"][1]["textStyle"] == "tree"


@pytest.mark.parametrize("title", ["Услуги архива", "Каналы доступа"])
@pytest.mark.parametrize(("body", "expected_tree"), [
    ("Каналы доступа\nЧитальный зал — работа с подлинниками. Телефон — консультации.", True),
    ("Каналы доступа\nЧитальный зал — работа с подлинниками. "
     "Телефон — консультации и заказы.", False),
    ("Каналы доступа\nЧитальный зал — консультации. Телефон — работа с подлинниками.", False),
    ("Каналы доступа\nЧитальный зал — работа с подлинниками. Телефон — консультации.\n"
     "Доступ только по будням.", False),
])
def test_plain_plan_recovers_tree_only_when_the_whole_body_matches(
    monkeypatch, title, body, expected_tree,
):
    if title == "Каналы доступа":
        body = body.removeprefix(f"{title}\n")
    source = {"blocks": [
        {"kind": "text", "id": f"line-{index}", "text": line}
        for index, line in enumerate(("Каналы доступа", "Читальный зал", "- Работа с подлинниками.",
                                     "Телефон", "- Консультации."), 1)
    ]}
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Доступ к архиву", "block-1", "block-2", "block-4")],
        "slides": [{"layout": "text", "title": title, "body": body}],
    }, source=source)
    slide = result.document["slides"][1]
    if expected_tree:
        assert slide["textStyle"] == "tree"
        assert slide["body"] == (
            "Каналы доступа\nЧитальный зал\n  Работа с подлинниками.\nТелефон\n  Консультации."
        )
    else:
        assert "textStyle" not in slide
        assert slide["body"] == body


@pytest.mark.parametrize("variant", ["source", "swapped", "ordinary", "unordered", "changed"])
def test_procedure_recovery_respects_source_order_and_conditions(monkeypatch, variant):
    title = "Порядок выдачи" if variant != "ordinary" else "Сведения о выдаче"
    actions = ["Покажите пропуск.", "Получите талон.", "Подойдите к окну."]
    conditions = "Доступ подтверждает сотрудник. Срок зависит от наличия дела."
    body_conditions = "Доступ подтверждает сотрудник; срок зависит от наличия дела."
    actual = actions[::-1] if variant == "swapped" else actions
    if variant == "changed":
        body_conditions = body_conditions.replace("зависит", "не зависит")
    body = " ".join([*actual, body_conditions])
    source = {"blocks": [
        {"kind": "text", "id": f"line-{index}", "text": line}
        for index, line in enumerate([
            title, *[f"- {action}" if variant == "unordered" else action for action in actions],
            "Условия выдачи", conditions,
        ], 1)
    ]}
    result = planned_generation(monkeypatch, {
        "title": "Архив",
        "plan": [intent("Выдача дела", "block-1", "block-2", "block-3", "block-4", "block-6")],
        "slides": [{"layout": "text", "title": title, "body": body}],
    }, source=source)
    slide = result.document["slides"][1]
    if variant == "source":
        assert slide["textStyle"] == "steps"
        assert slide["body"] == "\n".join(actions) + "\n\nУсловия выдачи\n" + conditions
    else:
        assert "textStyle" not in slide
        assert slide["body"] == body


def test_revision_of_body_keeps_source_owned_composition(monkeypatch):
    composition = {
        "kind": "metric", "values": [
            {"label": "2024", "value": "5 дней"}, {"label": "2025", "value": "4 дня"},
        ],
    }
    slide = {"id": "s1", "layout": "text", "title": "Ожидание", "body": "Замер по форме."}
    document = {"title": "Пилот", "slides": [{**slide, "composition": composition}]}

    def respond(**request):
        assert "composition" not in request["schema"]["$defs"]["TextSlide"]["properties"]
        return {"status": "applied", "document": {
            "title": "Пилот", "slides": [{**slide, "body": "Электронная форма."}],
        }}

    monkeypatch.setattr(presentation_ml, "request_document", respond)
    result = presentation_ml.revise(
        document=document, text="Доклад", slideCount=3, instruction="Уточни формулировку",
        target_slide_numbers=[1], target_slide_ids=["s1"], job_id="test",
        deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert result["slides"] == [{**slide, "body": "Электронная форма.", "composition": composition}]
    assert document["slides"][0]["body"] == "Замер по форме."
