"""Real PostgreSQL/pgvector hybrid retrieval, tenant filtering and migration evidence."""

import os
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from test_knowledge import FakeEmbeddings, catalog_source
from test_training_chat import create_client

from app.database import Base
from app.modules.knowledge.bootstrap import seed_catalog
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.modules.knowledge.service import KnowledgeService

pytestmark = pytest.mark.skipif(
    os.getenv("TEST_POSTGRES") != "1", reason="Isolated PostgreSQL opt-in"
)


@pytest.fixture
def knowledge_sessions():
    schema = "test_knowledge_" + uuid4().hex
    admin = create_engine(os.environ["DATABASE_URL"])
    with admin.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        os.environ["DATABASE_URL"],
        # Omit public deliberately, as other application PostgreSQL integration fixtures do.
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000"},
    )
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_pgvector_hybrid_has_hard_six_limit_and_search_indexes(knowledge_sessions):
    with knowledge_sessions() as session:
        client = create_client(session, "retrieval", "retrieval@example.test")
        entries = [catalog_source(f"lexical-{index}") for index in range(7)]
        entries.append(
            catalog_source(
                "semantic-only",
                chunks=[
                    {
                        "id": "semantic-only-1",
                        "section": "Resistance training",
                        "content": "Gradual resistance progression.",
                    }
                ],
            )
        )
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": entries})
        # An orthogonal vector prevents this exact-text match entering the semantic result.
        lexical = session.get(KnowledgeChunk, "lexical-0-1")
        lexical.embedding = [0.0, 1.0] + [0.0] * 1022
        session.flush()
        result = KnowledgeService(FakeEmbeddings()).retrieve(session, client.id, "força")
        assert result.knowledge_status == "supported" and len(result.chunks) == 6
        indexes = session.scalars(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname=current_schema() "
                "AND tablename='knowledge_chunk'"
            )
        ).all()
        assert any("USING hnsw" in index for index in indexes)
        assert any("USING gin" in index for index in indexes)


def test_hybrid_returns_both_lexical_only_and_semantic_only_candidates(knowledge_sessions):
    with knowledge_sessions() as session:
        client = create_client(session, "hybrid", "hybrid@example.test")
        entries = [
            catalog_source(
                "lexical",
                chunks=[
                    {"id": "lexical-1", "section": "Exact match", "content": "lexicalexclusiva"}
                ],
            ),
            catalog_source(
                "semantic",
                chunks=[
                    {
                        "id": "semantic-1",
                        "section": "Related meaning",
                        "content": "No shared query tokens.",
                    }
                ],
            ),
        ]
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": entries})
        session.get(KnowledgeChunk, "lexical-1").embedding = [0.0, 1.0] + [0.0] * 1022
        session.flush()
        result = KnowledgeService(FakeEmbeddings()).retrieve(session, client.id, "lexicalexclusiva")
        assert {chunk["chunk_id"] for chunk in result.chunks} == {"lexical-1", "semantic-1"}


def test_hybrid_isolates_clients_and_filters_nc_unreviewed_and_expired_sources(knowledge_sessions):
    with knowledge_sessions() as session:
        first = create_client(session, "first", "first@example.test")
        second = create_client(session, "second", "second@example.test")
        entries = [
            catalog_source(identifier)
            for identifier in ("global", "private", "nc", "pending", "expired")
        ]
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": entries})
        session.get(KnowledgeSource, "private").client_id = second.id
        session.get(KnowledgeSource, "nc").license = "CC-BY-NC-4.0"
        session.get(KnowledgeSource, "pending").review_status = "pending"
        session.get(KnowledgeSource, "expired").review_due_at = date.today()
        session.flush()
        service = KnowledgeService(FakeEmbeddings())
        first_context = service.retrieve(session, first.id, "força")
        assert [chunk["source_id"] for chunk in first_context.chunks] == ["global"]
        second_context = service.retrieve(session, second.id, "força")
        assert {chunk["source_id"] for chunk in second_context.chunks} == {"global", "private"}
        session.get(KnowledgeSource, "global").review_due_at = date.today() - timedelta(days=1)
        session.flush()
        outdated = service.retrieve(session, first.id, "força")
        assert outdated.knowledge_status == "outdated" and not outdated.chunks
        assert "revisão vencida" in outdated.knowledge_limitations
        assert "diagnósticos" in outdated.knowledge_limitations


def test_embedding_outage_leaves_database_transaction_usable(knowledge_sessions):
    from app.integrations.embeddings import EmbeddingProviderError

    class Unavailable:
        def embed(self, texts):
            raise EmbeddingProviderError("embedding_unavailable")

    with knowledge_sessions() as session:
        client = create_client(session, "outage", "outage@example.test")
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": [catalog_source()]})
        context = KnowledgeService(Unavailable()).retrieve(session, client.id, "força")
        assert context.knowledge_status == "unavailable" and not context.chunks
        assert session.scalar(select(KnowledgeSource.id)) == "reviewed"


def test_section_keywords_are_searchable_in_long_queries_without_vector_similarity(
    knowledge_sessions,
):
    with knowledge_sessions() as session:
        client = create_client(session, "section", "section@example.test")
        source = catalog_source(
            chunks=[
                {
                    "id": "reviewed-1",
                    "section": "Elevação de panturrilha",
                    "content": "Slow controlled movement.",
                }
            ]
        )
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": [source]})
        session.get(KnowledgeChunk, "reviewed-1").embedding = [0.0, 1.0] + [0.0] * 1022
        session.flush()
        context = KnowledgeService(FakeEmbeddings()).retrieve(
            session, client.id, "Meu treino tem panturrilha e quero revisar técnica com o instrutor"
        )
        assert [chunk["chunk_id"] for chunk in context.chunks] == ["reviewed-1"]


def test_concurrent_ownership_change_during_embedding_never_reloads_private_content(
    knowledge_sessions,
):
    with knowledge_sessions() as session:
        first = create_client(session, "race-first", "race-first@example.test")
        second = create_client(session, "race-second", "race-second@example.test")
        seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": [catalog_source()]})
        session.commit()
        first_id, second_id = first.id, second.id

    class ReassignDuringEmbedding(FakeEmbeddings):
        def embed(self, texts):
            # A second real transaction changes scope after the initial metadata preflight.
            with knowledge_sessions() as writer:
                writer.get(KnowledgeSource, "reviewed").client_id = second_id
                writer.get(
                    KnowledgeChunk, "reviewed-1"
                ).content = "PRIVATE SECOND CLIENT MEDICAL FACT"
                writer.commit()
            return super().embed(texts)

    with knowledge_sessions() as reader:
        context = KnowledgeService(ReassignDuringEmbedding()).retrieve(reader, first_id, "força")
        assert context.knowledge_status == "insufficient_evidence"
        assert not context.chunks and "PRIVATE" not in str(context.as_context())
