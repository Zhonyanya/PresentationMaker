"""Store the source blocks associated with the current presentation."""

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "4d41dc8ce2b0"
down_revision = "5b1f0c3d9a2e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("presentations", Column("source_document", JSONB(), nullable=True))


def downgrade():
    op.drop_column("presentations", "source_document")
