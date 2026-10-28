"""ORM-модели доступа, текущего документа и служебного жизненного цикла заданий."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Аккаунт с уникальным логином без учёта регистра и Argon2id-хешем пароля."""

    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(String(64))
    login_normalized: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    """Серверная сессия с хешем токена; user_id=None означает сессию до входа."""

    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Presentation(Base):
    """Текущее состояние презентации без истории и архивных результатов.

    До первого успеха document, document_token и slide_count отсутствуют вместе.
    После успеха они заменяются атомарно. Токен обозначает актуальность, а не
    номер версии; желаемое число слайдов хранится отдельно от фактического.
    """

    __tablename__ = "presentations"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("requested_slide_count BETWEEN 3 AND 20"),
        CheckConstraint(
            "(document IS NULL AND document_token IS NULL AND slide_count IS NULL) OR "
            "(document IS NOT NULL AND document_token IS NOT NULL AND slide_count IS NOT NULL AND "
            "slide_count = jsonb_array_length(document->'slides') AND "
            "slide_count BETWEEN 1 AND 60) IS TRUE",
            name="current_document_consistent",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    requested_slide_count: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    document_token: Mapped[str | None] = mapped_column(String(128))
    slide_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Служебное задание, обеспечивающее доставку, статус и идемпотентность.

    input_snapshot нужен только для выполнения и очищается при завершении.
    Результат хранится в Presentation, а output_document_token позволяет проверить,
    остаётся ли он текущим. attempt_token защищает от публикации старой попыткой.
    Частичный уникальный индекс допускает только одно активное задание презентации.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["presentation_id", "owner_id"], ["presentations.id", "presentations.owner_id"]
        ),
        UniqueConstraint("owner_id", "idempotency_key"),
        CheckConstraint("kind IN ('generate', 'revise')"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','timed_out')"),
        CheckConstraint("phase IN ('waiting','ml','validation','saving','done')"),
        Index(
            "one_active_job",
            "presentation_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
        Index("jobs_recovery", "status", "deadline_at", "dispatched_at"),
        Index("jobs_created_at", "created_at"),
        Index("jobs_owner_created_at", "owner_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    presentation_id: Mapped[UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    phase: Mapped[str] = mapped_column(String(16), default="waiting")
    base_document_token: Mapped[str | None] = mapped_column(String(128))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    output_document_token: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_token: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(300))
