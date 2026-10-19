"""Idempotent reviewed-catalogue reconciliation, executed before backend startup."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.integrations.embeddings import (
    EMBEDDING_MODEL,
    EmbeddingProvider,
    OllamaBgeM3EmbeddingProvider,
    validate_embedding,
)
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.modules.knowledge.service import source_is_reviewed

CATALOG_PATH = Path(__file__).with_name("catalog.json")


def _date(value):
    return date.fromisoformat(value) if value else None


def seed_catalog(
    session: Session,
    provider: EmbeddingProvider,
    catalog: dict[str, object],
) -> int:
    """Reconcile managed public sources; never overwrite a client's private source."""
    with session.no_autoflush:
        return _seed_catalog(session, provider, catalog)


def _seed_catalog(session: Session, provider: EmbeddingProvider, catalog: dict[str, object]) -> int:
    if catalog.get("version") != 1 or not isinstance(catalog.get("sources"), list):
        raise ValueError("invalid_knowledge_catalog")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(571124823)"))
    source_ids, chunk_ids = set(), set()
    pending: list[tuple[KnowledgeChunk, str]] = []
    total = 0
    for entry in catalog["sources"]:
        source_id = entry["id"]
        if source_id in source_ids or not isinstance(source_id, str) or len(source_id) > 100:
            raise ValueError("invalid_knowledge_source_id")
        source_ids.add(source_id)
        source = session.get(KnowledgeSource, source_id)
        if source and (source.client_id is not None or not source.catalog_managed):
            raise ValueError("knowledge_catalog_identity_conflict")
        if source is None:
            source = KnowledgeSource(id=source_id, catalog_managed=True)
            session.add(source)
        for name in (
            "title",
            "url",
            "authors",
            "language",
            "license",
            "license_url",
            "commercial_use_allowed",
            "review_status",
            "reviewed_by",
        ):
            setattr(source, name, entry.get(name))
        for name in ("reviewed_at", "review_due_at", "captured_at"):
            setattr(source, name, _date(entry.get(name)))
        source.attribution = entry.get("attribution", "")
        source.content_note = entry.get("content_note", "")
        source.limitations = entry.get("limitations", [])
        if (
            source.review_status not in ("approved", "pending", "excluded")
            or not isinstance(source.authors, list)
            or not source.authors
            or not isinstance(source.title, str)
            or not source.title.strip()
            or not isinstance(source.url, str)
            or not source.url.startswith("https://")
            or not isinstance(source.license_url, str)
            or not isinstance(source.commercial_use_allowed, bool)
            or not isinstance(source.limitations, list)
            or any(not isinstance(limit, str) for limit in source.limitations)
        ):
            raise ValueError("invalid_knowledge_source_metadata")
        # Explicit approval cannot bypass a noncommercial or unknown licence.
        approved = source_is_reviewed(source, date.today())
        if source.review_status == "approved" and not approved:
            raise ValueError("unlicensed_or_unreviewed_knowledge_source")
        chunks = entry.get("chunks", []) if approved else []
        if approved and not chunks:
            raise ValueError("approved_knowledge_source_without_chunks")
        # There is no domain relationship on these metadata records: persist the
        # parent first so PostgreSQL FK ordering never depends on ORM mapper order.
        session.flush([source])
        keep = []
        for chunk_data in chunks:
            chunk_id, content = chunk_data["id"], chunk_data["content"]
            section = chunk_data["section"]
            if (
                not isinstance(chunk_id, str)
                or not chunk_id
                or len(chunk_id) > 150
                or chunk_id in chunk_ids
                or not isinstance(content, str)
                or not content.strip()
                or len(content) > 12000
                or not isinstance(section, str)
                or not section.strip()
                or len(section) > 500
            ):
                raise ValueError("invalid_knowledge_chunk")
            chunk_ids.add(chunk_id)
            keep.append(chunk_id)
            embedding_text = f"{source.title}\n{section}\n{content}"
            if len(embedding_text) > 12000:
                raise ValueError("knowledge_chunk_exceeds_embedding_limit")
            digest = hashlib.sha256(embedding_text.encode("utf-8")).hexdigest()
            chunk = session.get(KnowledgeChunk, chunk_id)
            if chunk and chunk.source_id != source_id:
                raise ValueError("knowledge_chunk_identity_conflict")
            changed = (
                not chunk
                or chunk.content_hash != digest
                or chunk.embedding_model != EMBEDDING_MODEL
            )
            if chunk is None:
                chunk = KnowledgeChunk(id=chunk_id, source_id=source_id)
                session.add(chunk)
            chunk.section, chunk.content, chunk.content_hash = section, content, digest
            if changed:
                chunk.embedding_model = EMBEDDING_MODEL
                pending.append((chunk, embedding_text))
            total += 1
        session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.source_id == source_id,
                KnowledgeChunk.id.not_in(keep),
            ),
            execution_options={"synchronize_session": False},
        )
    removed = session.scalars(
        select(KnowledgeSource).where(
            KnowledgeSource.catalog_managed.is_(True),
            KnowledgeSource.id.not_in(source_ids),
            KnowledgeSource.client_id.is_(None),
        )
    ).all()
    for source in removed:
        source.review_status = "excluded"
        session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    for offset in range(0, len(pending), 16):
        batch = pending[offset : offset + 16]
        embeddings = provider.embed([content for _, content in batch])
        if len(embeddings) != len(batch):
            raise ValueError("invalid_catalog_embeddings")
        for (chunk, _), embedding in zip(batch, embeddings, strict=True):
            chunk.embedding = validate_embedding(embedding)
    session.flush()
    if total == 0:
        raise ValueError("empty_reviewed_knowledge_catalog")
    return total


def main() -> None:
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL must be configured")
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    with SessionLocal() as session, session.begin():
        count = seed_catalog(session, OllamaBgeM3EmbeddingProvider(), catalog)
    print(f"Reviewed knowledge catalogue ready: {count} chunks")


if __name__ == "__main__":
    main()
