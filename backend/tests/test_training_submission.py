"""Client consent gates the exact draft revision entering professional review."""

import pytest
from sqlalchemy import select
from test_training_lifecycle import client_id, data
from test_training_lifecycle import session as session
from test_training_review import api as api

from app.modules.clients.models import Account, Client
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.knowledge.service import KnowledgeResult
from app.modules.training.models import TrainingPlan, TrainingPlanVersion
from app.modules.training.presentation import proposal_preview
from app.modules.training.review_service import pending_version, pending_versions
from app.modules.training.router import version_response
from app.modules.training.service import (
    ConcurrentTrainingUpdateError,
    InvalidTrainingTransitionError,
    TrainingLifecycleService,
    TrainingVersionNotFoundError,
)


def own_draft(session):
    return TrainingLifecycleService().create_proposal(
        session,
        client_id=client_id(session),
        data=data("Corpo inteiro"),
        created_by="ai",
        origin="ai",
        knowledge=KnowledgeResult([], "unavailable", "Consulta às fontes indisponível."),
    )


def test_private_preview_requires_submission_and_keeps_evidence_and_plan_inactive(session):
    service = TrainingLifecycleService()
    draft = own_draft(session)
    assert draft.submitted_for_review_at is None
    assert pending_versions(session, 0, 20) == []
    with pytest.raises(TrainingVersionNotFoundError):
        pending_version(session, draft.id)
    options = dict(
        plan_id=draft.plan_id, version_number=1, actor="instructor-1", expected_revision=1
    )
    with pytest.raises(InvalidTrainingTransitionError):
        service.approve(session, **options)
    with pytest.raises(InvalidTrainingTransitionError):
        service.revise(session, data=data(), **options)
    evidence = (draft.citations, draft.knowledge_status, draft.knowledge_limitations)
    service.submit_for_review(session, subject="client", version_id=draft.id, expected_revision=1)
    assert draft.revision == 2 and draft.submitted_for_review_at
    assert pending_versions(session, 0, 20) == [draft]
    assert evidence == (draft.citations, draft.knowledge_status, draft.knowledge_limitations)
    assert draft.status == "proposal" and not session.get(TrainingPlan, draft.plan_id).is_current
    submitted_at = draft.submitted_for_review_at
    service.submit_for_review(session, subject="client", version_id=draft.id, expected_revision=2)
    assert draft.revision == 2
    assert draft.submitted_for_review_at.replace(tzinfo=None) == submitted_at.replace(tzinfo=None)
    service.approve(session, **{**options, "expected_revision": 2})
    assert draft.status == "current"


def test_ai_edit_revokes_submission_and_stale_requests_cannot_submit_or_approve(session):
    service = TrainingLifecycleService()
    draft = own_draft(session)
    service.submit_for_review(session, subject="client", version_id=draft.id, expected_revision=1)
    service.revise(
        session,
        plan_id=draft.plan_id,
        version_number=1,
        actor="ai",
        expected_revision=2,
        data=data("Treino ajustado"),
    )
    assert draft.revision == 3 and draft.submitted_for_review_at is None
    assert pending_versions(session, 0, 20) == []
    with pytest.raises(ConcurrentTrainingUpdateError):
        service.submit_for_review(
            session, subject="client", version_id=draft.id, expected_revision=1
        )
    with pytest.raises(ConcurrentTrainingUpdateError):
        service.approve(
            session,
            plan_id=draft.plan_id,
            version_number=1,
            actor="instructor-1",
            expected_revision=2,
        )
    with pytest.raises(TrainingVersionNotFoundError):
        service.submit_for_review(
            session, subject="someone-else", version_id=draft.id, expected_revision=3
        )
    service.submit_for_review(session, subject="client", version_id=draft.id, expected_revision=3)
    service.revise(
        session,
        plan_id=draft.plan_id,
        version_number=1,
        actor="instructor-1",
        expected_revision=4,
        data=data("Revisado pelo instrutor"),
    )
    assert draft.submitted_for_review_at and draft.revision == 5


def test_preview_is_ordered_and_serialized_with_all_knowledge_fields(session):
    draft = own_draft(session)
    preview = proposal_preview(session, draft)
    assert preview.startswith("Treino A — Corpo inteiro\nObjetivo: Ganhar força\n")
    assert "Status: Aguardando revisão do instrutor" in preview
    assert "| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |" in preview
    assert "| 1 | Agachamento | 3 | 8 | Carga confortável | 90 s |" in preview
    response = version_response(session, draft)
    assert response["preview"] == preview
    assert {"citations", "knowledge_status", "knowledge_limitations"} <= response.keys()
    assert response["submitted_for_review_at"] is None


def test_submit_api_is_owned_client_only_and_instructor_cannot_bypass_it(session, api):
    http, identity = api
    draft = own_draft(session)
    path = f"/training/drafts/{draft.id}/submit"
    assert http.post(path, {"expected_revision": 1}).status_code == 403
    assert (
        http.post(
            f"/training/plans/{draft.plan_id}/versions/1/approve", {"expected_revision": 1}
        ).status_code
        == 409
    )
    other = Client(name="Outro", account=Account(email="other@test.test", keycloak_subject="other"))
    session.add(other)
    session.commit()
    identity.identity = AuthenticatedIdentity("other", "other", ("client",))
    assert http.post(path, {"expected_revision": 1}).status_code == 404
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    assert http.get("/training/drafts").json()[0]["id"] == str(draft.id)
    response = http.post(path, {"expected_revision": 1})
    assert response.status_code == 200 and response.json()["submitted_for_review_at"]
    assert response.json()["status"] == "proposal" and response.json()["revision"] == 2
    assert http.post(path, {"expected_revision": 1}).status_code == 409
    assert session.scalar(select(TrainingPlanVersion.status)) == "proposal"
