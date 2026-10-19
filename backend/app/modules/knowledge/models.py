"""Bibliographic metadata and reviewed chunks with pgvector and full-text indexes."""

from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.database import Base
from app.integrations.embeddings import EMBEDDING_DIMENSIONS, validate_embedding


class EmbeddingVector(UserDefinedType):
    """pgvector parameter encoding without an additional Python dependency."""

    cache_ok = True

    def get_col_spec(self, **kwargs):
        return f"public.vector({EMBEDDING_DIMENSIONS})"

    def bind_processor(self, dialect):
        def encode(value):
            return None if value is None else json.dumps(validate_embedding(value))

        return encode

    def result_processor(self, dialect, coltype):
        def decode(value):
            return None if value is None else json.loads(value) if isinstance(value, str) else value

        return decode


class KnowledgeSource(Base):
    __tablename__ = "knowledge_source"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('approved', 'pending', 'excluded')",
            name="ck_knowledge_source_review_status",
        ),
        Index("ix_knowledge_source_client_review", "client_id", "review_status", "review_due_at"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Null means reviewed public bibliography; client-owned additions never cross clients.
    client_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("client.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    license: Mapped[str] = mapped_column(String(100), nullable=False)
    license_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[date | None] = mapped_column(Date)
    review_due_at: Mapped[date | None] = mapped_column(Date)
    captured_at: Mapped[date | None] = mapped_column(Date)
    attribution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    catalog_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        Index("ix_knowledge_chunk_source", "source_id"),
        Index(
            "ix_knowledge_chunk_search",
            text("to_tsvector('simple', section || ' ' || content)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_knowledge_chunk_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "public.vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("knowledge_source.id", ondelete="CASCADE"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        EmbeddingVector().with_variant(JSON, "sqlite"), nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
