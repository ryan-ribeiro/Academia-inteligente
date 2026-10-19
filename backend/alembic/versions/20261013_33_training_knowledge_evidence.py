"""Persist validated bibliographic evidence on client-owned AI artifacts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261013_33"
down_revision = "20261013_32"
branch_labels = None
depends_on = None

TABLES = ("training_plan_version", "training_ai_message", "training_adaptation_proposal")


def upgrade():
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("citations", postgresql.JSONB(), nullable=False, server_default="[]"),
        )
        op.add_column(
            table,
            sa.Column(
                "knowledge_status", sa.String(32), nullable=False,
                server_default="insufficient_evidence",
            ),
        )
        op.add_column(
            table,
            sa.Column("knowledge_limitations", sa.Text(), nullable=False, server_default=""),
        )


def downgrade():
    for table in reversed(TABLES):
        for column in ("knowledge_limitations", "knowledge_status", "citations"):
            op.drop_column(table, column)
