"""Удаление презентаций пользователем: отметка вместо физического удаления строки."""

import sqlalchemy as sa

from alembic import op

revision = "5b1f0c3d9a2e"
down_revision = "c2b7d44f8e91"
branch_labels = None
depends_on = None


def upgrade():
    """Добавляет nullable-колонку без перезаписи таблицы и блокировки на время заполнения."""
    op.add_column(
        "presentations", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    """Убирает отметку удаления; стёртые тексты и документы при этом не восстанавливаются."""
    op.drop_column("presentations", "deleted_at")
