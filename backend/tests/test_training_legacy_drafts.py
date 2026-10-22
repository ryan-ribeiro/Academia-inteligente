"""Previously saved resource-only drafts cannot bypass today's validation through reuse."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_adaptations import current_plan
from test_training_chat import FakeProvider as ChatProvider
from test_training_generation import FakeProvider, complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_rag import FakeKnowledge
from test_training_review import api as api

from app.integrations.ai import AiProviderError, AiTrainingChatResponse
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training import router
from app.modules.training.chat_service import TrainingChatService
from app.modules.training.generation_service import InitialTrainingGenerationService
from app.modules.training.models import TrainingPlanItem, TrainingPlanVersion
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import TrainingLifecycleService


def legacy_draft(session, owner):
    draft = TrainingLifecycleService().create_proposal(
        session,
        client_id=owner.id,
        data=TrainingPlanVersionInput.model_validate(proposal().plan),
        created_by="ai",
        origin="ai",
    )
    # Simulate data persisted before resource-name validation was introduced.
    item = session.scalar(select(TrainingPlanItem).where(TrainingPlanItem.version_id == draft.id))
    item.exercise_name = "Peso corporal (Dia A)"
    session.commit()
    return draft


@pytest.mark.parametrize("has_current", [False, True])
def test_initial_generation_replaces_invalid_cached_draft_without_a_replacement_flag(
    session, api, monkeypatch, has_current
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    lifecycle = TrainingLifecycleService()
    base = current_plan(session, owner) if has_current else None
    original = lifecycle.content(session, base) if base else None
    draft = legacy_draft(session, owner)
    writer = FakeProvider(proposal())
    monkeypatch.setattr(
        router,
        "generation_service",
        InitialTrainingGenerationService(provider=writer, knowledge_service=FakeKnowledge()),
    )
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post("/training/initial-proposal", {})
    assert response.status_code == 201
    saved = response.json()
    assert saved["id"] == str(draft.id) and saved["revision"] == 2
    assert saved["items"][0]["exercise_name"] == "Agachamento"
    assert not saved.get("validation_error") and "Peso corporal" not in saved["preview"]
    assert writer.calls == len(writer.review_contexts) == 1
    feedback = writer.contexts[0]["selection_correction"]["completeness_issues"]
    assert feedback[0]["position"] == 1
    assert feedback[0]["exercise_name"] == "Peso corporal (Dia A)"
    assert "items" not in writer.contexts[0]["selection_correction"]["rejected_plan"]
    assert session.scalars(
        select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
    ).all() == [draft]
    if base:
        assert base.status == "current" and lifecycle.content(session, base) == original


def test_generic_generation_in_chat_does_not_replay_an_invalid_cached_draft(session):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    draft = legacy_draft(session, owner)
    writer = FakeProvider(proposal())
    chat = ChatProvider(AiTrainingChatResponse(assistant_message="Não deve ser chamado."))
    result = TrainingChatService(
        chat,
        generation_service=InitialTrainingGenerationService(
            provider=writer, knowledge_service=FakeKnowledge()
        ),
    ).submit_for_subject(session, "client", message="Gere meu treino", client_request_id=uuid4())
    assert "Agachamento" in result.messages[-1].content
    assert "Peso corporal" not in result.messages[-1].content
    assert draft.revision == 2 and writer.calls == len(writer.review_contexts) == 1
    assert chat.calls == 0


@pytest.mark.parametrize("failure", ["unavailable", "invalid"])
def test_failed_regeneration_keeps_legacy_draft_blocked_in_both_client_projections(
    session, api, monkeypatch, failure
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    draft = legacy_draft(session, owner)
    result = (
        AiProviderError("configuration", retryable=False)
        if failure == "unavailable"
        else proposal(items=[{**proposal().plan["items"][0], "exercise_name": "Peso corporal"}])
    )
    writer = FakeProvider(result)
    monkeypatch.setattr(
        router,
        "generation_service",
        InitialTrainingGenerationService(provider=writer, knowledge_service=FakeKnowledge()),
    )
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post("/training/initial-proposal", {})
    assert response.status_code == (503 if failure == "unavailable" else 502)
    assert draft.revision == 1
    for path in ("/training/drafts", "/training/chat"):
        response = http.get(path)
        assert response.status_code == 200
        projection = response.json()[0] if path.endswith("drafts") else response.json()["draft"]
        assert projection["id"] == str(draft.id)
        assert "exercícios inválidos" in projection["validation_error"]
        assert projection["preview"] is None


@pytest.mark.parametrize("already_submitted", [False, True])
def test_legacy_draft_cannot_be_submitted_or_approved(session, api, already_submitted):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    current = lifecycle.content(session, base)
    draft = legacy_draft(session, owner)
    if already_submitted:
        draft.submitted_for_review_at = datetime.now(UTC)
        session.commit()
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post(f"/training/drafts/{draft.id}/submit", {"expected_revision": 1})
    assert response.status_code == 422
    assert draft.revision == 1
    assert bool(draft.submitted_for_review_at) == already_submitted
    if already_submitted:
        identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
        response = http.post(
            f"/training/plans/{draft.plan_id}/versions/1/approve", {"expected_revision": 1}
        )
        assert response.status_code == 422
    assert base.status == "current" and lifecycle.content(session, base) == current
