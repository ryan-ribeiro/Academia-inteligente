"""Explicit routine rebuilds must produce a submittable draft, not chat prose."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_adaptations import current_plan
from test_training_generation import complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_review import api as api
from test_training_targeted_requests import focused_service
from training_fixtures import instructor

from app.integrations.ai import AiProviderError
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training import router as training_router
from app.modules.training.chat_service import (
    TrainingChatDraftUpdateError,
    TrainingChatService,
    TrainingChatUnavailableError,
)
from app.modules.training.models import TrainingPlanVersion
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import TrainingLifecycleService

REQUEST = "Refaça todo a minha ficha de treino do zero, para ganho de massa"


@pytest.mark.parametrize(
    "message",
    [
        REQUEST,
        "Refaça toda a minha ficha de treino do zero, para ganho de massa.",
        "Refaça minha ficha",
        "Quero refazer meu treino para hipertrofia",
        "Pode refazer a minha ficha de treino?",
        "Você poderia refazer minha ficha?",
        "Por favor, remonte todo o meu treino do zero",
        "Gostaria de reformular o meu plano de treino",
        "Preciso que você recrie minha ficha",
        "Monte uma nova ficha de treino do zero",
    ],
)
def test_rebuild_is_an_explicit_generation_request(message):
    assert TrainingChatService._requests_initial_plan(message, [])


@pytest.mark.parametrize(
    "message",
    [
        "Não refaça minha ficha",
        "Não quero refazer meu treino",
        "Como posso refazer minha ficha?",
        "Quero saber como refazer minha ficha",
        "Meu instrutor disse: refaça sua ficha",
        "Refaça minha ficha se o instrutor concordar",
        "Refaça minha ficha depois que eu corrigir meus dados",
        "Refaça minha ficha, mas não refaça agora",
        "Refaça minha ficha, mas não quero refazer agora",
        "Pode me explicar como refazer minha ficha?",
    ],
)
def test_negated_conditional_and_informational_rebuilds_do_not_authorize_generation(message):
    assert not TrainingChatService._requests_initial_plan(message, [])


@pytest.mark.parametrize("has_current", [False, True])
@pytest.mark.parametrize("draft_origin", [None, "ai", "instructor"])
@pytest.mark.parametrize("message", [REQUEST, "Refaça minha ficha"])
def test_rebuild_returns_one_draft_and_the_displayed_revision_can_be_sent_to_review(
    session, api, monkeypatch, has_current, draft_origin, message
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner) if has_current else None
    if base is None:
        instructor(session, "instructor-1")
    lifecycle = TrainingLifecycleService()
    original = lifecycle.content(session, base) if base else None
    existing = None
    if draft_origin:
        existing = lifecycle.create_proposal(
            session,
            client_id=owner.id,
            data=TrainingPlanVersionInput.model_validate(proposal().plan),
            created_by="ai" if draft_origin == "ai" else "instructor-1",
            origin=draft_origin,
        )
        lifecycle.submit_for_review(
            session, subject="client", version_id=existing.id, expected_revision=existing.revision
        )
    chat, writer, _, chat_writer = focused_service(
        [], ["Remada", "Flexão de braços", "Agachamento"], scope="unspecified"
    )
    monkeypatch.setattr(training_router, "chat_service", chat)
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    request = {"message": message, "client_request_id": str(uuid4())}
    response = http.post("/training/chat/messages", request)
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft is not None and draft["submitted_for_review_at"] is None
    assert draft["status"] == "proposal" and draft["objective"] == "Ganho de massa muscular"
    assert "Remada" in draft["preview"]
    assert draft["preview"] in response.json()["messages"][-1]["content"]
    assert "Enviar rascunho para minha revisão" in response.json()["messages"][-1]["content"]
    if existing:
        assert draft["id"] == str(existing.id)
    assert writer.contexts[-1]["training_request"] == message
    assert writer.calls == 1 and chat_writer.calls == 0
    assert http.post("/training/chat/messages", request).json() == response.json()
    assert writer.calls == 1
    assert (
        len(
            session.scalars(
                select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
            ).all()
        )
        == 1
    )
    identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
    assert http.get("/training/pending").json()["items"] == []
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    sent = http.post(
        f"/training/drafts/{draft['id']}/submit", {"expected_revision": draft["revision"]}
    )
    assert sent.status_code == 200 and sent.json()["submitted_for_review_at"]
    identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
    pending = http.get("/training/pending").json()["items"]
    assert len(pending) == 1 and pending[0]["id"] == draft["id"]
    if base:
        assert base.status == "current" and lifecycle.content(session, base) == original


@pytest.mark.parametrize("failure", ["unavailable", "schema"])
def test_failed_rebuild_preserves_the_existing_draft_and_approved_plan(session, failure):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    original = lifecycle.content(session, base)
    draft = lifecycle.create_revision(
        session,
        plan_id=base.plan_id,
        version_number=base.version_number,
        data=original,
        actor="instructor-1",
    )
    revision = draft.revision
    chat, writer, _, chat_writer = focused_service([], ["Remada"], scope="unspecified")
    writer.result = (
        AiProviderError("unavailable", retryable=False)
        if failure == "unavailable"
        else proposal(items=[])
    )
    with pytest.raises(
        TrainingChatUnavailableError if failure == "unavailable" else TrainingChatDraftUpdateError
    ):
        chat.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    assert draft.revision == revision and lifecycle.content(session, draft) == original
    assert base.status == "current" and lifecycle.content(session, base) == original
    assert chat_writer.calls == 0


def test_rebuild_requires_completed_onboarding(session):
    create_client(session, "client", "client@example.test")
    chat, writer, _, chat_writer = focused_service([], ["Remada"], scope="unspecified")
    result = chat.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    assert "conclua seu onboarding" in result.messages[-1].content
    assert writer.calls == chat_writer.calls == 0
    assert not session.scalars(select(TrainingPlanVersion)).all()
