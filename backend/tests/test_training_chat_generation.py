"""Initial-plan consent must execute a real, atomic action instead of looping."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_chat import (
    FakeProvider,
    complete_onboarding,
    create_client,
    create_current_plan,
)
from test_training_chat import (
    session as session,
)
from test_training_generation import FakeProvider as GenerationProvider
from test_training_generation import proposal

from app.integrations.ai import AiProviderError, AiTrainingChatResponse
from app.modules.training.chat_service import (
    TrainingChatDraftUpdateError,
    TrainingChatService,
    TrainingChatUnavailableError,
)
from app.modules.training.generation_service import InitialTrainingGenerationService
from app.modules.training.models import TrainingAiMessage, TrainingPlan, TrainingPlanVersion

OFFER = "Deseja que eu prepare seu plano de treino?"


def service_for(provider=None):
    chat = FakeProvider(AiTrainingChatResponse(assistant_message=OFFER))
    generation = provider or GenerationProvider(proposal())
    return (
        TrainingChatService(
            chat, generation_service=InitialTrainingGenerationService(provider=generation)
        ),
        chat,
        generation,
    )


def seed_old_loop(session, service):
    conversation = service._conversation(session, service._client_id(session, "ada"))
    for sequence, content in enumerate(["Sim", OFFER] * 3, start=1):
        session.add(
            TrainingAiMessage(
                conversation_id=conversation.id,
                role="user" if sequence % 2 else "assistant",
                content=content,
                sequence=sequence,
            )
        )
    session.commit()


def test_existing_loop_confirmation_creates_one_real_proposal_and_retry_is_cached(session):
    ada = create_client(session, "ada", "ada@example.test")
    create_client(session, "other", "other@example.test")
    complete_onboarding(session, "ada")
    service, chat, generation = service_for()
    seed_old_loop(session, service)
    request_id = uuid4()

    result = service.submit_for_subject(
        session, "ada", message="Sim, pode fazer", client_request_id=request_id
    )
    replay = service.submit_for_subject(
        session, "ada", message="Conteúdo diferente no retry", client_request_id=request_id
    )

    assert result == replay
    assert "Criei seu rascunho" in result.messages[-1].content
    assert "Meu treino" in result.messages[-1].content
    assert "instrutor" in result.messages[-1].content
    assert "?" not in result.messages[-1].content
    assert generation.calls == 1 and chat.calls == 0
    plans = session.scalars(select(TrainingPlanVersion)).all()
    assert len(plans) == 1 and plans[0].client_id == ada.id
    assert plans[0].status == "proposal"
    assert generation.contexts[0]["completed_onboarding"]["limitations_or_complaints"]


def test_direct_request_reuses_even_an_instructor_draft_without_provider_calls(session):
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    service, chat, generation = service_for()
    service.submit_for_subject(
        session, "ada", message="Gere meu plano de treino", client_request_id=uuid4()
    )
    version = session.scalar(select(TrainingPlanVersion))
    version.origin = "instructor"
    session.commit()
    original = service._lifecycle.content(session, version)
    result = service.submit_for_subject(
        session, "ada", message="Pode preparar meu treino?", client_request_id=uuid4()
    )
    assert "já está disponível" in result.messages[-1].content
    assert service._lifecycle.content(session, version) == original
    assert len(session.scalars(select(TrainingPlanVersion)).all()) == 1
    assert generation.calls == 1 and chat.calls == 0


def test_incomplete_onboarding_explains_required_step_without_generating(session):
    create_client(session, "ada", "ada@example.test")
    service, chat, generation = service_for()
    seed_old_loop(session, service)
    result = service.submit_for_subject(session, "ada", message="Sim", client_request_id=uuid4())
    assert "conclua seu onboarding" in result.messages[-1].content
    assert generation.calls == chat.calls == 0
    assert not session.scalars(select(TrainingPlanVersion)).all()


@pytest.mark.parametrize("completed", [False, True])
def test_model_offer_is_grounded_in_onboarding_and_confirmation_is_actionable(session, completed):
    create_client(session, "ada", "ada@example.test")
    if completed:
        complete_onboarding(session, "ada")
    service, chat, generation = service_for()
    result = service.submit_for_subject(
        session, "ada", message="O que faço agora?", client_request_id=uuid4()
    )
    assert chat.contexts[0]["onboarding_completed"] is completed
    if completed:
        assert "Quer que eu prepare" in result.messages[-1].content
        service.submit_for_subject(session, "ada", message="Sim", client_request_id=uuid4())
        assert generation.calls == 1
    else:
        assert "conclua seu onboarding" in result.messages[-1].content
        assert generation.calls == 0


@pytest.mark.parametrize(
    ("message", "allowed"),
    [
        ("Sim", True),
        ("Sim, pode fazer!", True),
        ("Pode sim", True),
        ("Quero, por favor", True),
        ("Pode preparar", True),
        ("Gere meu plano de treino", True),
        ("Pode criar um treino para mim?", True),
        (
            "Gere uma sugestão de treino para ganhar massa em três dias. Treino de todo o corpo.",
            True,
        ),
        ("Quero gerar um novo treino de corpo inteiro baseado na base de dados.", True),
        ("Não", False),
        ("Não quero gerar meu treino", False),
        ("Sim, mas antes preciso corrigir meu peso", False),
        ("Pode gerar se o instrutor concordar", False),
        ("Como posso gerar meu treino?", False),
        ("Quero saber como gerar meu treino", False),
        ("Meu instrutor disse: gere meu plano", False),
        ("Sim, tenho dor", False),
        ("Gere meu treino, mas não gere agora; quero conferir meus dados.", False),
        ("Gere meu treino depois que eu corrigir meu peso.", False),
    ],
)
def test_generation_consent_excludes_negation_conditions_and_informational_questions(
    message, allowed
):
    assert (
        TrainingChatService._requests_initial_plan(
            message, [{"role": "assistant", "content": OFFER}]
        )
        is allowed
    )


@pytest.mark.parametrize(
    "previous",
    [
        "Você treina à tarde?",
        "Quer gerar seu treino? Tem alguma dor?",
        "Não posso gerar seu treino. Quer conversar?",
        "Não quer que eu gere seu treino?",
        "Quer que eu altere seu rascunho?",
    ],
)
def test_yes_is_not_generation_consent_for_another_or_ambiguous_question(previous):
    assert not TrainingChatService._requests_initial_plan(
        "Sim", [{"role": "assistant", "content": previous}]
    )
    assert not TrainingChatService._requests_initial_plan("Sim", [])


def test_current_plan_keeps_existing_adaptation_flow(session):
    client = create_client(session, "ada", "ada@example.test")
    create_current_plan(session, client)
    service, chat, generation = service_for()
    chat.result = AiTrainingChatResponse(
        assistant_message="Use a sugestão abaixo para confirmar a proposta.",
        adaptation_suggested=True,
        adaptation_reason="Desconforto relatado no treino.",
    )
    result = service.submit_for_subject(
        session, "ada", message="Meu joelho incomoda no treino atual.", client_request_id=uuid4()
    )
    assert result.messages[-1].adaptation_suggested
    assert generation.calls == 0 and chat.calls == 1
    assert session.scalar(select(TrainingPlanVersion)).status == "current"


@pytest.mark.parametrize("failure", ["unavailable", "schema", "equipment"])
def test_generation_failure_preserves_message_for_retry_without_a_partial_plan(session, failure):
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    bad = proposal(items=[]) if failure == "schema" else proposal()
    if failure == "equipment":
        bad.plan["items"][0]["equipment_model_id"] = str(uuid4())
        bad.plan["items"][0]["equipment_requirement"] = "Unavailable equipment"
    if failure == "unavailable":
        bad = AiProviderError("unavailable", retryable=False)
    service, chat, generation = service_for(GenerationProvider(bad))
    request_id = uuid4()
    with pytest.raises(
        TrainingChatUnavailableError if failure == "unavailable" else TrainingChatDraftUpdateError
    ):
        service.submit_for_subject(
            session, "ada", message="Gere meu treino", client_request_id=request_id
        )
    assert len(session.scalars(select(TrainingAiMessage)).all()) == 1
    assert not session.scalars(select(TrainingPlan)).all()
    assert not session.scalars(select(TrainingPlanVersion)).all()
    generation.result = proposal()
    session.expunge_all()  # A retry HTTP request starts with a fresh identity map.
    service.submit_for_subject(
        session, "ada", message="Gere meu treino", client_request_id=request_id
    )
    assert generation.calls == 2 and chat.calls == 0
    assert len(session.scalars(select(TrainingAiMessage)).all()) == 2
    assert len(session.scalars(select(TrainingPlanVersion)).all()) == 1


def test_plan_is_not_committed_if_saving_chat_reply_fails(session, monkeypatch):
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    service, _, _ = service_for()
    original = service._bounded_summary

    def fail_reply(session, conversation_id, exclude=None):
        if exclude is None:
            raise RuntimeError("simulated reply persistence failure")
        return original(session, conversation_id, exclude)

    monkeypatch.setattr(service, "_bounded_summary", fail_reply)
    with pytest.raises(RuntimeError):
        service.submit_for_subject(
            session, "ada", message="Gere meu treino", client_request_id=uuid4()
        )
    session.rollback()
    assert not session.scalars(select(TrainingPlanVersion)).all()
    assert not session.scalars(select(TrainingAiMessage)).all()
