"""Начальная схема пользователей, сессий, текущих презентаций и заданий."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9956876a761d"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Создаёт таблицы и ограничения владения, текущего документа и активных заданий."""
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("login_normalized", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login_normalized"),
    )
    op.create_table(
        "presentations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("requested_slide_count", sa.Integer(), nullable=False),
        sa.Column(
            "document", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("document_token", sa.String(length=128), nullable=True),
        sa.Column("slide_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(document IS NULL AND document_token IS NULL AND slide_count IS NULL) OR "
            "(document IS NOT NULL AND document_token IS NOT NULL AND slide_count IS NOT NULL AND "
            "slide_count = jsonb_array_length(document->'slides') AND "
            "slide_count BETWEEN 1 AND 60) IS TRUE",
            name="current_document_consistent",
        ),
        sa.CheckConstraint("requested_slide_count BETWEEN 3 AND 20"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "owner_id"),
    )
    op.create_index(op.f("ix_presentations_owner_id"), "presentations", ["owner_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("csrf_token", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("presentation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("base_document_token", sa.String(length=128), nullable=True),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_document_token", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_token", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.CheckConstraint("kind IN ('generate', 'revise')"),
        sa.CheckConstraint("phase IN ('waiting','ml','validation','saving','done')"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','timed_out')"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["presentation_id", "owner_id"],
            ["presentations.id", "presentations.owner_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key"),
    )
    op.create_index(op.f("ix_jobs_owner_id"), "jobs", ["owner_id"], unique=False)
    op.create_index(op.f("ix_jobs_presentation_id"), "jobs", ["presentation_id"], unique=False)
    op.create_index(
        "jobs_recovery", "jobs", ["status", "deadline_at", "dispatched_at"], unique=False
    )
    op.create_index(
        "one_active_job",
        "jobs",
        ["presentation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )


def downgrade():
    """Удаляет начальную схему вместе со всеми её пользовательскими данными."""
    op.drop_index(
        "one_active_job",
        table_name="jobs",
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.drop_index("jobs_recovery", table_name="jobs")
    op.drop_index(op.f("ix_jobs_presentation_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_owner_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_presentations_owner_id"), table_name="presentations")
    op.drop_table("presentations")
    op.drop_table("users")
