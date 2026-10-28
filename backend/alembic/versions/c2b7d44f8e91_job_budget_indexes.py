"""Индексы скользящих квот приёма без изменения API и сохранённых документов."""

from alembic import op

revision = "c2b7d44f8e91"
down_revision = "9956876a761d"
branch_labels = None
depends_on = None


def upgrade():
    """Создаёт индексы конкурентно, не блокируя запись заданий в существующую таблицу."""
    with op.get_context().autocommit_block():
        op.create_index(
            "jobs_created_at", "jobs", ["created_at"],
            postgresql_concurrently=True, if_not_exists=True,
        )
        op.create_index(
            "jobs_owner_created_at", "jobs", ["owner_id", "created_at"],
            postgresql_concurrently=True, if_not_exists=True,
        )


def downgrade():
    """Конкурентно удаляет индексы квот, сохраняя задания и документы."""
    with op.get_context().autocommit_block():
        op.drop_index("jobs_owner_created_at", table_name="jobs", postgresql_concurrently=True)
        op.drop_index("jobs_created_at", table_name="jobs", postgresql_concurrently=True)
