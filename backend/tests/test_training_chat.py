from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from training_fixtures import AcceptingTrainingReviewer, instructor

from app.database import Base, get_database_session
from app.integrations.ai import AiProviderError, AiTrainingChatResponse
from app.modules.clients.models import Account, Client
from app.modules.equipment import models as equipment_models  # noqa: F401
from app.modules.identity import router as identity_router
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.onboarding.draft_service import OnboardingDraftService
from app.modules.onboarding.schema import OnboardingDraftUpdate
from app.modules.training.chat_service import (
    TrainingChatNotFoundError,
    TrainingChatService,
    TrainingChatUnavailableError,
)
from app.modules.training.models import (
    TrainingAiConversation,
    TrainingAiMessage,
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.schema import ManualPlanCreate, TrainingPlanItemInput
from app.modules.training.service import TrainingLifecycleService


class FakeProvider(AcceptingTrainingReviewer):
    def __init__(self, result: AiTrainingChatResponse | Exception) -> None:
        self.result = result
        self.calls = 0
        self.contexts: list[dict[str, object]] = []

    def training_chat(self, context: dict[str, object]) -> AiTrainingChatResponse:
        self.calls += 1
        self.contexts.append(context)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RetryProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__(AiTrainingChatResponse(assistant_message="Vamos revisar seu exercício."))
        self.fail_once = True

    def training_chat(self, context: dict[str, object]) -> AiTrainingChatResponse:
        self.calls += 1
        self.contexts.append(context)
        if self.fail_once:
            self.fail_once = False
            raise AiProviderError("timeout", retryable=True)
        return self.result


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield value
    finally:
        value.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_client(session: Session, subject: str, email: str) -> Client:
    client = Client(
        name=email.split("@")[0],
        account=Account(email=email, keycloak_subject=subject, account_active=True),
    )
    session.add(client)
    session.commit()
    return client


def create_current_plan(session: Session, client: Client) -> None:
    instructor(session, "instrutor")
    lifecycle = TrainingLifecycleService()
    proposal = lifecycle.create_proposal(
        session,
        client_id=client.id,
        data=ManualPlanCreate(
            client_id=str(client.id),
            name="Força inicial",
            objective="Ganhar força",
            items=[
                TrainingPlanItemInput(
                    exercise_name="Agachamento",
                    sets=3,
                    repetitions="8",
                    load_guidance="Carga confortável",
                    rest_seconds=90,
                )
            ],
        ),
        created_by="instrutor",
        origin="instructor",
    )
    lifecycle.approve(
        session,
        plan_id=proposal.plan_id,
        version_number=proposal.version_number,
        actor="instrutor",
        expected_revision=proposal.revision,
    )


def complete_onboarding(session: Session, subject: str) -> None:
    service = OnboardingDraftService()
    scope = service.resolve_client_scope(session, subject)
    service.save_draft(
        session,
        scope,
        OnboardingDraftUpdate(
            training_goal="Ganhar força",
            training_experience="beginner",
            height_cm=170,
            weight_kg="70.5",
            has_limitations_or_complaints=True,
            limitations_or_complaints="Joelho sensível",
            uses_medications=False,
            has_health_conditions=False,
        ),
    )
    service.complete_draft(session, scope)


def test_chat_is_client_scoped_persisted_and_never_mutates_plan(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    create_client(session, "grace", "grace@example.test")
    create_current_plan(session, ada)
    complete_onboarding(session, "ada")
    provider = FakeProvider(
        AiTrainingChatResponse(assistant_message="Faça o movimento com controle.")
    )
    service = TrainingChatService(provider)

    state = service.submit_for_subject(
        session, "ada", message="Como faço o agachamento?", client_request_id=uuid4()
    )

    assert [message.role for message in state.messages] == ["user", "assistant"]
    assert state.messages[-1].content == "Faça o movimento com controle."
    assert provider.contexts[0]["current_training_plan"] == {
        "name": "Força inicial",
        "objective": "Ganhar força",
        "items": [
            {
                "exercise_name": "Agachamento",
                "sets": 3,
                "repetitions": "8",
                "load_guidance": "Carga confortável",
                "rest_seconds": 90,
            }
        ],
    }
    assert "grace@example.test" not in str(provider.contexts[0])
    assert session.scalars(select(TrainingPlan)).all()[0].is_current is True
    with pytest.raises(TrainingChatNotFoundError):
        service.state_for_subject(session, "missing")
    assert service.state_for_subject(session, "grace").messages == []


def test_idempotent_message_does_not_call_provider_or_create_duplicates(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    provider = FakeProvider(AiTrainingChatResponse(assistant_message="Resposta em português."))
    service = TrainingChatService(provider)
    request_id = uuid4()

    first = service.submit_for_subject(
        session, "ada", message="Tenho uma dúvida", client_request_id=request_id
    )
    second = service.submit_for_subject(
        session, "ada", message="Tenho uma dúvida", client_request_id=request_id
    )

    assert len(first.messages) == len(second.messages) == 2
    assert provider.calls == 1
    assert len(session.scalars(select(TrainingAiMessage)).all()) == 2


def test_chat_persists_an_ai_detected_adaptation_suggestion(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    create_current_plan(session, ada)
    request_id = uuid4()
    service = TrainingChatService(
        FakeProvider(
            AiTrainingChatResponse(
                assistant_message="Posso preparar uma proposta para revisão.",
                adaptation_suggested=True,
                adaptation_reason="Desconforto relatado no agachamento.",
            )
        )
    )

    state = service.submit_for_subject(
        session,
        "ada",
        message="Meu joelho incomoda no agachamento.",
        client_request_id=request_id,
    )

    suggestion = state.messages[-1]
    assert suggestion.adaptation_suggested is True
    assert suggestion.adaptation_reason == "Desconforto relatado no agachamento."
    assert suggestion.reply_to_client_request_id == request_id
    assert session.scalars(select(TrainingPlan)).all()[0].is_current is True


def test_chat_does_not_offer_adaptation_without_a_current_plan(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    service = TrainingChatService(
        FakeProvider(
            AiTrainingChatResponse(
                assistant_message="Vamos conversar sobre isso.",
                adaptation_suggested=True,
                adaptation_reason="Desconforto relatado.",
            )
        )
    )
    state = service.submit_for_subject(
        session, "ada", message="Meu joelho incomoda.", client_request_id=uuid4()
    )
    assert state.messages[-1].adaptation_suggested is False


def test_chat_can_update_the_single_active_draft(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    lifecycle = TrainingLifecycleService()
    draft = lifecycle.create_proposal(
        session,
        client_id=ada.id,
        data=ManualPlanCreate(
            client_id=str(ada.id),
            name="Rascunho inicial",
            objective="Ganhar força",
            items=[
                TrainingPlanItemInput(
                    exercise_name="Agachamento",
                    sets=3,
                    repetitions="8",
                    load_guidance="Carga confortável",
                    rest_seconds=90,
                )
            ],
        ),
        created_by="ai",
        origin="ai",
    )
    provider = FakeProvider(
        AiTrainingChatResponse(
            assistant_message="Atualizei o seu rascunho para uma alternativa mais confortável.",
            draft_update={
                "name": "Rascunho inicial",
                "objective": "Ganhar força sem desconforto no joelho",
                "items": [
                    {
                        "exercise_name": "Leg press",
                        "sets": 3,
                        "repetitions": "10",
                        "load_guidance": "Carga leve e sem dor",
                        "rest_seconds": 90,
                    }
                ],
            },
        )
    )

    TrainingChatService(provider).submit_for_subject(
        session,
        "ada",
        message="Atualize o rascunho para não usar agachamento.",
        client_request_id=uuid4(),
    )

    updated = session.scalar(select(TrainingPlanVersion).where(TrainingPlanVersion.id == draft.id))
    assert updated is not None
    assert updated.status == "proposal" and updated.origin == "ai" and updated.revision == 2
    assert updated.objective == "Ganhar força sem desconforto no joelho"
    assert (
        session.scalar(
            select(TrainingPlanItem.exercise_name).where(TrainingPlanItem.version_id == draft.id)
        )
        == "Leg press"
    )
    assert provider.contexts[0]["editable_training_draft"] is not None


def test_chat_can_update_an_instructor_draft(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    lifecycle = TrainingLifecycleService()
    manual = lifecycle.create_proposal(
        session,
        client_id=ada.id,
        data=ManualPlanCreate(
            client_id=str(ada.id),
            name="Rascunho do instrutor",
            objective="Força",
            items=[
                TrainingPlanItemInput(
                    exercise_name="Remada",
                    sets=3,
                    repetitions="10",
                    load_guidance="Carga confortável",
                    rest_seconds=60,
                )
            ],
        ),
        created_by="instrutor",
        origin="instructor",
    )
    provider = FakeProvider(
        AiTrainingChatResponse(
            assistant_message="Atualizei o rascunho conforme solicitado.",
            draft_update={
                "name": "Rascunho ajustado",
                "objective": "Força sem desconforto",
                "items": [
                    {
                        "exercise_name": "Outro",
                        "sets": 2,
                        "repetitions": "10",
                        "load_guidance": "Leve",
                        "rest_seconds": 60,
                    }
                ],
            },
        )
    )
    service = TrainingChatService(provider)

    service.submit_for_subject(
        session, "ada", message="Altere meu treino", client_request_id=uuid4()
    )

    updated = session.scalar(select(TrainingPlanVersion).where(TrainingPlanVersion.id == manual.id))
    assert updated is not None
    assert updated.name == "Rascunho ajustado" and updated.revision == 2
    assert provider.contexts[0]["editable_training_draft"] is not None


def test_retry_and_failure_leave_training_plan_unchanged(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    create_current_plan(session, ada)
    retry = RetryProvider()
    service = TrainingChatService(retry)
    service.submit_for_subject(
        session, "ada", message="Explique meu treino", client_request_id=uuid4()
    )
    assert retry.calls == 2

    unavailable = TrainingChatService(
        FakeProvider(AiProviderError("configuration", retryable=False))
    )
    with pytest.raises(TrainingChatUnavailableError):
        unavailable.submit_for_subject(
            session, "ada", message="Outra dúvida", client_request_id=uuid4()
        )
    plan = session.scalar(select(TrainingPlan).where(TrainingPlan.client_id == ada.id))
    assert plan is not None and plan.is_current is True


def test_expired_raw_chat_is_purged_without_deleting_training_plan(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    create_current_plan(session, ada)
    service = TrainingChatService(FakeProvider(AiTrainingChatResponse(assistant_message="Certo.")))
    service.submit_for_subject(session, "ada", message="Olá", client_request_id=uuid4())
    conversation = session.scalar(select(TrainingAiConversation))
    assert conversation is not None
    conversation.raw_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    for message in session.scalars(select(TrainingAiMessage)).all():
        message.created_at = datetime.now(UTC) - timedelta(days=31)
    session.commit()

    assert service.state_for_subject(session, "ada").messages == []
    plan = session.scalar(select(TrainingPlan).where(TrainingPlan.client_id == ada.id))
    assert plan is not None and plan.is_current is True
    assert session.scalar(select(TrainingAiConversation)).summary is None


def test_health_context_is_minimized_to_relevant_client_question(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    provider = FakeProvider(AiTrainingChatResponse(assistant_message="Converse com seu instrutor."))
    service = TrainingChatService(provider)
    service.submit_for_subject(
        session, "ada", message="Explique minhas séries", client_request_id=UUID(int=1)
    )
    assert "limitations_or_complaints" not in provider.contexts[0]["relevant_onboarding"]
    service.submit_for_subject(
        session, "ada", message="Tenho dor no joelho", client_request_id=UUID(int=2)
    )
    assert (
        provider.contexts[1]["relevant_onboarding"]["limitations_or_complaints"]
        == "Joelho sensível"
    )


class FakeIdentityProvider:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self.identity = identity

    def get_identity(self, access_token: str) -> AuthenticatedIdentity:
        del access_token
        return self.identity


def request_chat(app, authorization: str | None) -> int:
    sent: list[dict[str, object]] = []
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/training/chat",
        "raw_path": b"/training/chat",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def test_raw_training_chat_endpoint_requires_the_client_role(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import create_app

    create_client(session, "ada", "ada@example.test")
    app = create_app()
    instructor(session, "instructor")

    def override_database_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_database_session] = override_database_session
    assert request_chat(app, None) == 401
    monkeypatch.setattr(
        identity_router,
        "identity_provider",
        FakeIdentityProvider(
            AuthenticatedIdentity("instructor", "i@example.test", ("instructor",))
        ),
    )
    assert request_chat(app, "Bearer token") == 403
    app.dependency_overrides.clear()


def test_memory_keeps_complete_client_corrections_and_excludes_assistant_claims(session):
    import json

    create_client(session, "ada", "ada@example.test")
    provider = FakeProvider(
        AiTrainingChatResponse(assistant_message="Afirmação inventada pelo assistente")
    )
    service = TrainingChatService(provider)
    for message in [
        "Treino três dias e prefiro manhã.",
        "Correção: treino dois dias, a manhã continua.",
        "Obrigado",
        "Entendi",
        "Certo",
        "Qual frequência eu disse?",
    ]:
        service.submit_for_subject(session, "ada", message=message, client_request_id=uuid4())
    summary = provider.contexts[-1]["conversation_summary"]
    assert "Afirmação inventada" not in summary
    entries = json.loads(summary)
    assert entries[0]["client_statement"] == "Treino três dias e prefiro manhã."
    assert entries[1]["client_statement"] == "Correção: treino dois dias, a manhã continua."
    assert len(summary) <= service._summary_limit


def test_active_chat_drops_expired_sources_and_summary(session):
    create_client(session, "ada", "ada@example.test")
    provider = FakeProvider(AiTrainingChatResponse(assistant_message="Certo."))
    service = TrainingChatService(provider)
    service.submit_for_subject(
        session, "ada", message="Relato antigo sensível", client_request_id=uuid4()
    )
    conversation = session.scalar(select(TrainingAiConversation))
    conversation.summary = "Relato antigo sensível"
    for item in session.scalars(select(TrainingAiMessage)):
        item.created_at = datetime.now(UTC) - timedelta(days=31)
    session.commit()
    service.submit_for_subject(session, "ada", message="Olá novamente", client_request_id=uuid4())
    assert "Relato antigo sensível" not in str(provider.contexts[-1])
    assert conversation.summary is None


def test_followup_uses_relevant_user_context_without_mutating_completed_onboarding(session):
    from app.modules.onboarding.models import Onboarding

    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    provider = FakeProvider(AiTrainingChatResponse(assistant_message="Converse com seu instrutor."))
    service = TrainingChatService(provider)
    for message in [
        "Tenho dor no joelho e só treino dois dias.",
        "Na verdade, é no ombro, não no joelho.",
        "E como faço nesse caso?",
    ]:
        service.submit_for_subject(session, "ada", message=message, client_request_id=uuid4())
    context = provider.contexts[-1]
    assert context["relevant_onboarding"]["limitations_or_complaints"] == "Joelho sensível"
    assert any("ombro" in item["content"] for item in context["recent_messages"])
    assert session.scalar(select(Onboarding)).limitations_or_complaints == "Joelho sensível"


def test_failed_retry_uses_original_message_and_stale_retry_is_rejected(session):
    from app.modules.training.service import ConcurrentTrainingUpdateError

    create_client(session, "ada", "ada@example.test")
    provider = FakeProvider(AiProviderError("unavailable", retryable=False))
    service = TrainingChatService(provider)
    request_id = uuid4()
    with pytest.raises(TrainingChatUnavailableError):
        service.submit_for_subject(
            session, "ada", message="Prefiro manhã", client_request_id=request_id
        )
    provider.result = AiTrainingChatResponse(assistant_message="Entendido.")
    service.submit_for_subject(session, "ada", message="Outro texto", client_request_id=request_id)
    assert provider.contexts[-1]["current_user_message"] == "Prefiro manhã"
    provider.result = AiProviderError("unavailable", retryable=False)
    stale = uuid4()
    with pytest.raises(TrainingChatUnavailableError):
        service.submit_for_subject(session, "ada", message="Três dias", client_request_id=stale)
    provider.result = AiTrainingChatResponse(assistant_message="Entendido.")
    service.submit_for_subject(
        session, "ada", message="Na verdade, dois dias", client_request_id=uuid4()
    )
    with pytest.raises(ConcurrentTrainingUpdateError):
        service.submit_for_subject(session, "ada", message="Três dias", client_request_id=stale)


def test_hallucinated_save_without_patch_is_not_presented_as_success(session):
    create_client(session, "ada", "ada@example.test")
    service = TrainingChatService(
        FakeProvider(AiTrainingChatResponse(assistant_message="Atualizei seu treino."))
    )
    state = service.submit_for_subject(
        session, "ada", message="Como funciona?", client_request_id=uuid4()
    )
    assert "Nenhuma alteração foi salva" in state.messages[-1].content


def test_unrequested_draft_update_is_blocked_and_success_is_confirmed_from_persistence(session):
    from test_training_lifecycle import data

    ada = create_client(session, "ada", "ada@example.test")
    lifecycle = TrainingLifecycleService()
    draft = lifecycle.create_proposal(
        session, client_id=ada.id, data=data(), created_by="ai", origin="ai"
    )
    provider = FakeProvider(
        AiTrainingChatResponse(
            assistant_message="Atualizei e aprovei!",
            draft_update=data("Novo rascunho").model_dump(mode="json"),
        )
    )
    service = TrainingChatService(provider)
    result = service.submit_for_subject(
        session, "ada", message="Tenho dor e prefiro manhã.", client_request_id=uuid4()
    )
    assert draft.revision == 1 and draft.status == "proposal"
    assert "Não alterei nenhum plano" in result.messages[-1].content
    assert provider.contexts[-1]["rules"]["may_update_ai_draft"] is False
    result = service.submit_for_subject(
        session, "ada", message="Atualize o rascunho para duas séries.", client_request_id=uuid4()
    )
    assert draft.revision == 2 and draft.status == "proposal"
    assert "ainda dependem da aprovação" in result.messages[-1].content
    assert "Enviar rascunho para minha revisão" in result.messages[-1].content
    assert "Treino A — Novo rascunho" in result.messages[-1].content
    assert "| 1 | Agachamento | 3 | 8 | Carga confortável | 90 s |" in result.messages[-1].content
    assert "aprovei" not in result.messages[-1].content


def test_draft_revision_rolls_back_if_reply_cannot_be_written(session, monkeypatch):
    from test_training_lifecycle import data

    ada = create_client(session, "ada", "ada@example.test")
    draft = TrainingLifecycleService().create_proposal(
        session, client_id=ada.id, data=data(), created_by="ai", origin="ai"
    )
    service = TrainingChatService(
        FakeProvider(
            AiTrainingChatResponse(
                assistant_message="Atualizei.", draft_update=data("Novo").model_dump(mode="json")
            )
        )
    )
    original_add = session.add

    def fail_reply(instance, *args, **kwargs):
        if isinstance(instance, TrainingAiMessage) and instance.role == "assistant":
            raise RuntimeError("Simulated write failure")
        return original_add(instance, *args, **kwargs)

    monkeypatch.setattr(session, "add", fail_reply)
    with pytest.raises(RuntimeError):
        service.submit_for_subject(
            session, "ada", message="Atualize o rascunho", client_request_id=uuid4()
        )
    session.rollback()
    session.refresh(draft)
    assert draft.revision == 1 and draft.name != "Novo"


@pytest.mark.parametrize(
    "message,allowed",
    [
        ("Quero aumentar massa", False),
        ("Como trocar as séries?", False),
        ("Explique por que devo alterar meu treino", False),
        ("Meu instrutor pediu para alterar o treino", False),
        ("Gostaria de saber se preciso trocar o exercício", False),
        ("Não quero alterar o treino", False),
        ("Atualize meu peso para 82 kg", False),
        ("Pode trocar o leg press por outro exercício?", True),
        ("Troque o leg press", True),
        ("Reduza a carga", True),
    ],
)
def test_only_explicit_training_changes_authorize_draft_writes(message, allowed):
    assert TrainingChatService._requests_draft_change(message, [], ["Leg press"]) is allowed


def test_explicit_confirmation_can_accept_the_previous_draft_question():
    from app.modules.training.chat_service import TrainingChatMessage

    previous = TrainingChatMessage(
        "assistant",
        "Posso trocar o leg press no rascunho?",
        datetime.now(UTC),
        None,
        uuid4(),
        False,
        None,
    )
    assert TrainingChatService._requests_draft_change("Sim", [previous], ["Leg press"])
    assert not TrainingChatService._requests_draft_change("Sim", [], ["Leg press"])


def test_summary_does_not_truncate_a_long_correction_or_reintroduce_older_facts(session):
    create_client(session, "ada", "ada@example.test")
    service = TrainingChatService(FakeProvider(AiTrainingChatResponse(assistant_message="Certo")))
    service._summary_limit = 100
    for message in [
        "Três dias",
        "Correção: " + "detalhe " * 30 + "somente dois dias",
        "Um",
        "Dois",
        "Três",
    ]:
        service.submit_for_subject(session, "ada", message=message, client_request_id=uuid4())
    # The older correction cannot fit as a complete attributed statement. Dropping
    # it must not revive the superseded three-day claim.
    assert (
        service._bounded_summary(session, session.scalar(select(TrainingAiConversation.id))) is None
    )
