"""Exercise the startup entry point without models imported by other test modules."""

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_fresh_interpreter_initializes_catalogue_after_migrations_and_on_restart():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent(
                """
                import sys

                assert "app.modules.clients.models" not in sys.modules

                from sqlalchemy import func, select
                from sqlalchemy.orm import Session

                from app.database import Base, engine
                from app.modules.knowledge import bootstrap, startup
                from app.modules.knowledge.models import KnowledgeChunk, KnowledgeSource

                events = []

                def migrate(command, *, check):
                    assert command == [sys.executable, "-m", "alembic", "upgrade", "head"]
                    assert check is True
                    events.append("migrate")
                    Base.metadata.create_all(engine)

                class FakeEmbeddings:
                    def embed(self, texts):
                        assert events[0] == "migrate"
                        events.append("embed")
                        return [[1.0] + [0.0] * 1023 for _ in texts]

                startup.subprocess.run = migrate
                bootstrap.OllamaBgeM3EmbeddingProvider = FakeEmbeddings

                startup.main()
                embedding_calls = events.count("embed")
                assert embedding_calls > 0
                startup.main()
                assert events.count("migrate") == 2
                assert events.count("embed") == embedding_calls

                with Session(engine) as session:
                    assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 14
                    assert session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 18
                """
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_URL": "sqlite+pysqlite:///:memory:"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
