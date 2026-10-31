"""Совместимый с браузерным Zod контракт запросов и полного JSON-документа."""

import json
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.errors import AppError


def database_text(value: str) -> str:
    """Отклоняет NUL и одиночные суррогаты до обращения к PostgreSQL text/JSONB.

    JSON допускает экранированный одиночный суррогат («\\ud800»), но в UTF-8 его не
    закодировать: без этой проверки запрос падал бы с 500 при хешировании и записи.
    """
    if "\x00" in value:
        raise ValueError("NUL is not supported in stored text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Unpaired surrogates are not supported") from exc
    return value


# Токен документа: непустая строка, которую можно хешировать и сравнивать
DocumentToken = Annotated[
    str, StringConstraints(min_length=1, max_length=128), AfterValidator(database_text)
]


def text(max_length: int, min_length: int = 0, *, trim=False):
    """Создаёт строгий строковый тип с ограничением длины как в JavaScript.

    Args:
        max_length: Максимальная длина в кодовых единицах UTF-16.
        min_length: Минимальная длина в тех же единицах.
        trim: Нужно ли удалять пробельные символы по краям до проверки длины.

    Returns:
        Аннотация Pydantic со строгой проверкой строки без неявного приведения типов.
    """

    def validate(value: str):
        database_text(value)
        # Zod считает кодовые единицы UTF-16, а не кодовые точки Unicode как len в Python.
        length = len(value.encode("utf-16-le")) // 2
        if not min_length <= length <= max_length:
            raise ValueError("Text length is outside the contract")
        return value

    return Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=trim, max_length=max_length),
        AfterValidator(validate),
    ]


class Contract(BaseModel):
    """Общая политика Zod: строгие типы и игнорирование неизвестных полей."""

    model_config = ConfigDict(extra="ignore", strict=True)


class SlideBase(Contract):
    """Общие поля слайда; обязательность и уникальность ID проверяются при нормализации."""

    id: Annotated[str, StringConstraints(min_length=1), AfterValidator(database_text)] | None = None
    title: text(200)
    notes: text(10000) | None = None


class TitleSlide(SlideBase):
    layout: Literal["title"]
    subtitle: text(400) | None = None
    caption: text(200) | None = None


class TextSlide(SlideBase):
    layout: Literal["text"]
    body: text(4000)


Items = Annotated[list[text(1000)], Field(max_length=12)]


class BulletsSlide(SlideBase):
    layout: Literal["bullets"]
    bullets: Items = Field(default_factory=list)


class TwoColumnSlide(SlideBase):
    layout: Literal["two-column"]
    leftTitle: text(120) | None = None
    left: Items = Field(default_factory=list)
    rightTitle: text(120) | None = None
    right: Items = Field(default_factory=list)


class SectionSlide(SlideBase):
    layout: Literal["section"]
    subtitle: text(400) | None = None


class ClosingSlide(SlideBase):
    layout: Literal["closing"]
    subtitle: text(400) | None = None


Slide = Annotated[
    TitleSlide | TextSlide | BulletsSlide | TwoColumnSlide | SectionSlide | ClosingSlide,
    Field(discriminator="layout"),
]


class Document(Contract):
    """Полный документ шести допустимых макетов, общий для хранения и браузерного вывода."""

    title: text(200)
    slides: Annotated[list[Slide], Field(min_length=1, max_length=60)]


class GenerateRequest(Contract):
    """Запрос генерации с обязательным желаемым slideCount, а не числом по умолчанию."""

    text: text(60000, 100, trim=True)
    title: text(200, trim=True) | None = None
    slideCount: Annotated[int, Field(ge=3, le=20)]

    @model_validator(mode="before")
    @classmethod
    def optional_title_not_null(cls, value):
        """Разрешает отсутствие title, но отклоняет явный null, как исходная Zod-схема."""
        if isinstance(value, dict) and "title" in value and value["title"] is None:
            raise ValueError("Optional title must be absent, not null")
        return value


class RegenerateRequest(GenerateRequest):
    """Полная генерация существующей презентации с токеном её текущего документа."""

    base_document_token: DocumentToken | None = None


class ReviseRequest(Contract):
    """Правка содержимого без изменения ID и порядка; номера целей начинаются с единицы."""

    instruction: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
        AfterValidator(database_text),
    ]
    base_document_token: DocumentToken
    target_slide_numbers: (
        Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1)] | None
    ) = None

    @model_validator(mode="after")
    def unique_targets(self):
        """Отклоняет повторные номера; верхнюю границу проверяет сервис по текущему снимку."""
        if self.target_slide_numbers and len(set(self.target_slide_numbers)) != len(
            self.target_slide_numbers
        ):
            raise ValueError("Номера слайдов должны быть уникальны")
        return self


def normalize_document(raw: object, *, generation: bool, max_bytes: int) -> dict:
    """Проверяет полный результат перед сохранением, не обрезая содержимое.

    При генерации отсутствующие и повторные ID заменяются новыми, пробелы
    по краям ID удаляются. При правке ID должны уже быть непустыми, уникальными
    и без таких пробелов: неоднозначную идентичность слайда исправлять нельзя.
    Сохранение ID и их порядка относительно исходного снимка проверяет validate_revision.

    Args:
        raw: JSON-строка, байты JSON либо разобранный объект документа.
        generation: Режим генерации; также требует первый title и последний closing.
        max_bytes: Максимальный размер входного JSON и его сериализации в UTF-8.

    Returns:
        Проверенный документ с уникальными ID, списками по умолчанию и без лишних полей.

    Raises:
        ValueError: При превышении размера, невалидном JSON, нарушении схемы,
            идентичности слайдов или структуры генерации.
        TypeError: Если объект не поддерживает JSON-сериализацию.
    """
    if isinstance(raw, (str, bytes)):
        if len(raw) > max_bytes or (isinstance(raw, str) and len(raw.encode()) > max_bytes):
            raise ValueError("ML response too large")
        raw = json.loads(raw)
    # Проверяем крупные строки до выделения памяти под их экранированную копию.
    pending = [iter((raw,))]
    seen_containers = set()
    while pending:
        value = next(pending[-1], StopIteration)
        if value is StopIteration:
            pending.pop()
        elif isinstance(value, str):
            if len(value) > max_bytes:
                raise ValueError("ML response too large")
        elif isinstance(value, (dict, list)) and id(value) not in seen_containers:
            seen_containers.add(id(value))
            if isinstance(value, dict):
                pending.append(iter(value.keys()))
                pending.append(iter(value.values()))
            else:
                pending.append(iter(value))
    # Считаем размер по частям, не создавая вторую полную копию JSON.
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(raw):
        if len(chunk) > max_bytes - size:
            raise ValueError("ML response too large")
        size += len(chunk.encode())
        if size > max_bytes:
            raise ValueError("ML response too large")
    # Необязательное поле в Zod можно пропустить, но нельзя передать как null.
    if not isinstance(raw, dict) or not isinstance(raw.get("slides"), list):
        raise ValueError("Invalid document")
    for slide in raw["slides"]:
        if not isinstance(slide, dict):
            raise ValueError("Invalid slide")
        models = (TitleSlide, TextSlide, BulletsSlide, TwoColumnSlide, SectionSlide, ClosingSlide)
        layouts = {model.model_fields["layout"].annotation.__args__[0]: model for model in models}
        model = layouts.get(slide.get("layout"))
        known = model.model_fields if model else {}
        if any(value is None for key, value in slide.items() if key in known):
            raise ValueError("Null slide fields are not supported")
        if isinstance(slide.get("id"), str) and not slide["id"].strip():
            raise ValueError("Empty slide ID")
    doc = Document.model_validate(raw).model_dump(exclude_none=True)
    seen = set()
    for slide in doc["slides"]:
        identifier = slide.get("id", "").strip()
        if not generation and identifier != slide.get("id"):
            raise ValueError("Revision cannot rewrite slide identity")
        if not identifier or identifier in seen:
            if not generation:
                raise ValueError("Revision must preserve unambiguous slide identity")
            identifier = str(uuid4())
        slide["id"] = identifier
        seen.add(identifier)
    if generation and (
        doc["slides"][0]["layout"] != "title" or doc["slides"][-1]["layout"] != "closing"
    ):
        raise ValueError("Generation requires title and closing slides")
    return doc


def validate_revision(previous: dict, current: dict, target_ids: list[str] | None) -> None:
    """Проверяет сохранение ID, порядка и области правки без мутации документов.

    Любая правка сохраняет последовательность ID исходного снимка. Добавление,
    удаление и перестановка слайдов недоступны до согласования отдельного
    структурного протокола с ML. Соответствие слайдов по содержимому не угадывается.

    Args:
        previous: Принятый серверный снимок с нормализованными ID.
        current: Полный нормализованный результат правки.
        target_ids: ID выбранных слайдов; None или пустой список разрешают менять
            содержимое всего документа, но не его ID, состав или порядок слайдов.

    Raises:
        AppError: Если изменены ID, состав или порядок слайдов, а при выбранных
            целях — также нецелевые слайды либо общее название презентации
            (502, INVALID_ML_RESPONSE).
    """
    if [slide["id"] for slide in previous["slides"]] != [
        slide["id"] for slide in current["slides"]
    ]:
        raise AppError(
            502,
            "INVALID_ML_RESPONSE",
            "ML изменил ID, состав или порядок слайдов. Структурные правки пока недоступны.",
        )
    if not target_ids:
        return
    old = [s for s in previous["slides"] if s["id"] not in target_ids]
    new = [s for s in current["slides"] if s["id"] not in target_ids]
    if old != new or previous["title"] != current["title"]:
        raise AppError(502, "INVALID_ML_RESPONSE", "ML изменил слайды вне выбранной области.")
