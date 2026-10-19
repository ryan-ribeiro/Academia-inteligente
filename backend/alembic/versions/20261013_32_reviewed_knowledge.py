"""Reviewed licensed bibliography with pgvector and PostgreSQL full-text search."""

import sqlalchemy as sa

from alembic import op

revision = "20261013_32"
down_revision = "20260927_31"
branch_labels = None
depends_on = None


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "public.vector(1024)"


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table(
        "knowledge_source",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("client.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("license", sa.String(100), nullable=False),
        sa.Column("license_url", sa.String(2000), nullable=False),
        sa.Column("commercial_use_allowed", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.Date()),
        sa.Column("review_due_at", sa.Date()),
        sa.Column("captured_at", sa.Date()),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("content_note", sa.Text(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("catalog_managed", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "review_status IN ('approved', 'pending', 'excluded')",
            name="ck_knowledge_source_review_status",
        ),
    )
    op.create_index(
        "ix_knowledge_source_client_review",
        "knowledge_source",
        ["client_id", "review_status", "review_due_at"],
    )
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.String(150), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(100),
            sa.ForeignKey("knowledge_source.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
    )
    op.create_index("ix_knowledge_chunk_source", "knowledge_chunk", ["source_id"])
    op.execute(
        "CREATE INDEX ix_knowledge_chunk_search ON knowledge_chunk "
        "USING gin (to_tsvector('simple', section || ' ' || content))"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunk_embedding ON knowledge_chunk "
        "USING hnsw (embedding public.vector_cosine_ops)"
    )


def downgrade():
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_source")
    # The extension may be shared by other database schemas; do not remove it.
