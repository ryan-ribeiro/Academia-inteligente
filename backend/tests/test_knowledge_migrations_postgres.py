"""Execute the RAG migrations and restart-safe catalogue seed on real PostgreSQL."""

import json
import os
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from test_knowledge import FakeEmbeddings
from test_knowledge_postgres import knowledge_sessions as knowledge_sessions

from app.modules.knowledge.bootstrap import CATALOG_PATH, seed_catalog
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeSource

pytestmark = pytest.mark.skipif(
    os.getenv("TEST_POSTGRES") != "1", reason="Isolated PostgreSQL opt-in"
)


def test_actual_rag_migrations_support_catalogue_initialization_and_repeated_start(
    knowledge_sessions,
):
    # The fixture creates and removes its own UUID-named schema. Rebuild only
    # changed tables/columns through the real migrations rather than create_all.
    with knowledge_sessions() as session:
        engine = session.get_bind()
    migrations = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE knowledge_chunk"))
        connection.execute(text("DROP TABLE knowledge_source"))
        for table in (
            "training_plan_version",
            "training_ai_message",
            "training_adaptation_proposal",
        ):
            for column in ("citations", "knowledge_status", "knowledge_limitations"):
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        with Operations.context(MigrationContext.configure(connection)):
            for filename in (
                "20261013_32_reviewed_knowledge.py",
                "20261013_33_training_knowledge_evidence.py",
            ):
                runpy.run_path(str(migrations / filename))["upgrade"]()

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    provider = FakeEmbeddings()
    with knowledge_sessions() as session:
        assert seed_catalog(session, provider, catalog) == 18
        session.commit()
    with knowledge_sessions() as session:
        assert seed_catalog(session, provider, catalog) == 18
        session.commit()
        assert len(provider.calls) == 18
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 14
        assert session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 18
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .join(KnowledgeSource)
                .where(KnowledgeSource.review_status != "approved")
            )
            == 0
        )
        dimension_type = session.scalar(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid='knowledge_chunk'::regclass AND a.attname='embedding'"
            )
        )
        assert dimension_type.endswith("vector(1024)")
        for table in (
            "training_plan_version",
            "training_ai_message",
            "training_adaptation_proposal",
        ):
            columns = session.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=:table"
                ),
                {"table": table},
            ).all()
            assert {"citations", "knowledge_status", "knowledge_limitations"} <= set(columns)
