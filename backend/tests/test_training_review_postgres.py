"""Actual PostgreSQL row-lock tests in a disposable, isolated test schema."""

import os
import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from test_training_lifecycle import client_id, data
from training_fixtures import instructor, submitted_draft

from app.database import Base
from app.modules.clients.models import Account, Client
from app.modules.training.models import TrainingAdaptationProposal, TrainingPlanVersion
from app.modules.training.service import TrainingLifecycleError, TrainingLifecycleService


def test_concurrent_selected_appends_keep_one_draft_and_do_not_duplicate_current_items(sessions):
    from test_training_targeted_requests import append_fixture

    with sessions() as session:
        lifecycle, base, draft, options = append_fixture(session)
        draft_id, current_id = draft.id, base.id
        original = lifecycle.content(session, base)
        additions = lifecycle.content(session, draft)
    ready = Barrier(2)

    def append_once(_):
        with sessions() as session:
            session.get(TrainingPlanVersion, draft_id)
            ready.wait(timeout=10)
            try:
                TrainingLifecycleService().append_to_current(session, **options)
                return "success"
            except TrainingLifecycleError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(append_once, (1, 2))) == ["conflict", "success"]
    with sessions() as session:
        draft = session.get(TrainingPlanVersion, draft_id)
        current = session.get(TrainingPlanVersion, current_id)
        combined = TrainingLifecycleService.content(session, draft)
        assert combined.items == [*original.items, additions.items[0]]
        assert TrainingLifecycleService.content(session, current) == original
        assert current.status == "current" and draft.status == "proposal"
        assert draft.version_number == 2 and draft.plan_id == current.plan_id
        assert (
            len(
                session.scalars(
                    select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
                ).all()
            )
            == 1
        )


pytestmark = pytest.mark.skipif(
    os.getenv("TEST_POSTGRES") != "1", reason="Explicit isolated PostgreSQL test opt-in required"
)


@pytest.fixture
def sessions():
    schema = "test_training_" + uuid4().hex
    admin = create_engine(os.environ["DATABASE_URL"])
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        os.environ["DATABASE_URL"],
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


@pytest.mark.parametrize(
    "actions",
    [("save", "save"), ("save", "approve"), ("approve", "approve"), ("ai-save", "approve")],
)
def test_first_successful_write_wins_with_two_real_transactions(sessions, actions):
    lifecycle = TrainingLifecycleService()
    with sessions() as session:
        instructor(session, "one")
        instructor(session, "two")
        version = lifecycle.create_proposal(
            session, client_id=client_id(session), data=data(), created_by="ai", origin="ai"
        )
        submitted_draft(session, version)
        version_id, plan_id = version.id, version.plan_id
    ready = Barrier(2)

    def write(index):
        with sessions() as session:
            # Both identity maps deliberately hold the original revision.
            stale = session.get(TrainingPlanVersion, version_id)
            expected = stale.revision
            ready.wait(timeout=10)
            try:
                options = dict(
                    plan_id=plan_id,
                    version_number=1,
                    actor="ai" if actions[index] == "ai-save" else ("one", "two")[index],
                    expected_revision=expected,
                )
                if actions[index] in {"save", "ai-save"}:
                    lifecycle.revise(session, data=data(f"Saved {index}"), **options)
                else:
                    lifecycle.approve(session, **options)
                return "success"
            except TrainingLifecycleError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(write, range(2)))
    assert sorted(results) == ["conflict", "success"]
    with sessions() as session:
        version = session.get(TrainingPlanVersion, version_id)
        assert version.revision == 2
        assert len(session.scalars(select(TrainingPlanVersion)).all()) == 1


def test_submission_and_ai_edit_cannot_both_win_for_the_same_revision(sessions):
    lifecycle = TrainingLifecycleService()
    with sessions() as session:
        version = lifecycle.create_proposal(
            session, client_id=client_id(session), data=data(), created_by="ai", origin="ai"
        )
        version_id, plan_id = version.id, version.plan_id
    ready = Barrier(2)

    def write(action):
        with sessions() as session:
            stale = session.get(TrainingPlanVersion, version_id)
            expected = stale.revision
            ready.wait(timeout=10)
            try:
                if action == "submit":
                    lifecycle.submit_for_review(
                        session, subject="client", version_id=version_id, expected_revision=expected
                    )
                else:
                    lifecycle.revise(
                        session,
                        plan_id=plan_id,
                        version_number=1,
                        actor="ai",
                        expected_revision=expected,
                        data=data("Alterado"),
                    )
                return "success"
            except TrainingLifecycleError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(write, ("submit", "edit"))) == ["conflict", "success"]
    with sessions() as session:
        version = session.get(TrainingPlanVersion, version_id)
        assert version.status == "proposal" and version.revision == 2


def test_migration_preserves_confirmed_review_but_requires_consent_for_existing_ai(sessions):
    lifecycle = TrainingLifecycleService()
    with sessions() as session:
        drafts = []
        for index, origin in enumerate(("ai", "instructor", "ai")):
            client = Client(name=f"Client {index}", account=Account(email=f"{index}@test.test"))
            session.add(client)
            session.commit()
            drafts.append(
                lifecycle.create_proposal(
                    session,
                    client_id=client.id,
                    data=data(),
                    created_by=origin,
                    origin=origin,
                )
            )
        adaptation = TrainingAdaptationProposal(
            client_id=drafts[2].client_id,
            base_version_id=drafts[2].id,
            source_client_request_id=uuid4(),
            client_request_id=uuid4(),
            reason="Teste",
            explanation="Teste",
            status="pending_instructor_review",
            client_reviewed_at=datetime.now(UTC),
            resulting_version_id=drafts[2].id,
        )
        session.add(adaptation)
        session.commit()
        identifiers = [draft.id for draft in drafts]
        engine = session.get_bind()
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261017_34_training_review_submission.py"
    )
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE training_plan_version DROP COLUMN submitted_for_review_at")
        )
        with Operations.context(MigrationContext.configure(connection)):
            runpy.run_path(str(migration))["upgrade"]()
    with sessions() as session:
        migrated = [session.get(TrainingPlanVersion, identifier) for identifier in identifiers]
        assert migrated[0].submitted_for_review_at is None
        assert all(version.submitted_for_review_at for version in migrated[1:])
