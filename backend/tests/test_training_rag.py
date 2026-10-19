"""Evidence validation and persistence across RF-15, RF-18 and RF-19."""

import json
from io import BytesIO
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_training_adaptations import (
    FakeAdaptationProvider,
    adjust_response,
    current_plan,
    source_message,
)
from test_training_chat import FakeProvider as ChatProvider
from test_training_generation import (
    FakeProvider as GenerationProvider,
)
from test_training_generation import (
    complete_onboarding,
    create_client,
    proposal,
)
from test_training_generation import session as session
from test_training_review import api as api

from app.integrations import ai
from app.integrations.ai import (
    AiTrainingAdaptationResponse,
    AiTrainingChatResponse,
    AiTrainingRequestFocus,
    OllamaConfig,
    OllamaOnboardingProvider,
    OpenAiConfig,
    OpenAiResponsesOnboardingProvider,
)
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.knowledge.service import KnowledgeContext
from app.modules.training import router as training_router
from app.modules.training.adaptation_service import AdaptationStateError, TrainingAdaptationService
from app.modules.training.chat_service import TrainingChatDraftUpdateError, TrainingChatService
from app.modules.training.generation_service import (
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
)
from app.modules.training.knowledge_query import retrieve_training_knowledge
from app.modules.training.models import (
    TrainingAdaptationProposal,
    TrainingAiMessage,
    TrainingPlanVersion,
)
from app.modules.training.review_service import pending_versions
from app.modules.training.router import (
    adaptation_response,
    training_chat_response,
    version_response,
)
from app.modules.training.service import TrainingLifecycleService

CHUNK_ID = "reviewed-strength-1"
CHUNK = {
    "chunk_id": CHUNK_ID,
    "source_id": "reviewed-strength",
    "title": "Exercícios de força revisados",
    "url": "https://www.nhs.uk/live-well/exercise/strength-exercises/",
    "authors": ["NHS"],
    "license": "OGL-3.0",
    "license_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    "section": "Movimento com apoio",
    "content": "Use apoio estável e respeite as limitações relatadas.",
    "attribution": "Contains public sector information licensed under the OGL v3.0.",
    "captured_at": "2026-10-13",
}
LIMIT = "Fonte geral; não permite inferir diagnósticos. Revisão do instrutor obrigatória."


class FakeKnowledge:
    def __init__(self, evidence=None):
        self.evidence = evidence or KnowledgeContext((CHUNK,), "supported", LIMIT)
        self.calls = []

    def retrieve(self, session, client_id, query):
        self.calls.append((client_id, query))
        return self.evidence


def run_flow(session, flow, *, knowledge, citations, writer_status=None):
    owner = create_client(session, "ada", "ada@example.test")
    create_client(session, "grace", "grace@example.test")
    fields = {"citations": citations}
    if writer_status is not None:
        fields["knowledge_status"] = writer_status
    if flow == "generation":
        complete_onboarding(session, "ada")
        writer = GenerationProvider(proposal().model_copy(update=fields))
        result = InitialTrainingGenerationService(
            provider=writer,
            knowledge_service=knowledge,
        ).generate_for_subject(session, "ada")
        projection = version_response(session, result)
    elif flow == "chat":
        base = current_plan(session, owner)
        writer = ChatProvider(
            AiTrainingChatResponse(
                assistant_message="Respeite suas limitações e revise o movimento com o instrutor.",
            ).model_copy(update=fields)
        )
        state = TrainingChatService(writer, knowledge_service=knowledge).submit_for_subject(
            session,
            "ada",
            message="Como faço o agachamento?",
            client_request_id=uuid4(),
        )
        result = session.scalar(
            select(TrainingAiMessage).where(TrainingAiMessage.role == "assistant")
        )
        projection = training_chat_response(state, session, "ada").messages[-1].model_dump()
        assert base.status == "current" and base.revision == 2
    else:
        base = current_plan(session, owner)
        source = uuid4()
        source_message(session, owner, source)
        writer = FakeAdaptationProvider(adjust_response().model_copy(update=fields))
        result = TrainingAdaptationService(writer, knowledge_service=knowledge).generate(
            session,
            "ada",
            source_client_request_id=source,
            client_request_id=uuid4(),
            reason="O agachamento incomoda meu joelho.",
        )
        projection = adaptation_response(session, result)
        assert base.status == "current" and result.status == "proposed"
    return owner, writer, result, projection


@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
def test_three_flows_persist_only_backend_canonical_citations(session, flow):
    knowledge = FakeKnowledge()
    owner, writer, result, projection = run_flow(
        session,
        flow,
        knowledge=knowledge,
        citations=[CHUNK_ID],
    )
    session.expire(result)
    assert result.citations[0]["title"] == CHUNK["title"]
    assert result.citations[0]["url"] == CHUNK["url"]
    assert result.citations[0]["authors"] == ["NHS"]
    assert "content" not in result.citations[0]
    assert result.knowledge_status == projection["knowledge_status"] == "supported"
    assert result.knowledge_limitations == projection["knowledge_limitations"] == LIMIT
    assert projection["citations"][0]["chunk_id"] == CHUNK_ID
    assert knowledge.calls[0][0] == owner.id
    assert "grace" not in str(writer.contexts[0])
    assert writer.contexts[0]["knowledge"]["chunks"][0]["chunk_id"] == CHUNK_ID
    assert "authors" not in writer.contexts[0]["knowledge"]["chunks"][0]
    assert result.citations[0]["authors"] == ["NHS"]


@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
@pytest.mark.parametrize("status", ["insufficient_evidence", "outdated", "unavailable"])
def test_three_flows_expose_clear_backend_limits_without_current_evidence(session, flow, status):
    knowledge = FakeKnowledge(KnowledgeContext.empty(status))
    _, _, result, projection = run_flow(
        session,
        flow,
        knowledge=knowledge,
        citations=[],
        writer_status="supported",
    )
    assert result.citations == projection["citations"] == []
    assert projection["knowledge_status"] == status
    assert projection["knowledge_limitations"]
    assert "diagnósticos" in projection["knowledge_limitations"]


@pytest.mark.parametrize(
    ("flow", "error"),
    [
        ("generation", InvalidTrainingGenerationError),
        ("chat", TrainingChatDraftUpdateError),
        ("adaptation", AdaptationStateError),
    ],
)
@pytest.mark.parametrize(
    "citations",
    [
        ["another-client-private-chunk"],
        [{"chunk_id": CHUNK_ID, "title": "Invented title", "url": "https://invented.test"}],
    ],
)
def test_fabricated_or_other_client_chunk_ids_are_rejected_before_writes(
    session,
    flow,
    error,
    citations,
):
    knowledge = FakeKnowledge()
    with pytest.raises(error):
        run_flow(session, flow, knowledge=knowledge, citations=citations)
    assert (
        session.scalars(
            select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
        ).all()
        == []
    )
    assert session.scalars(select(TrainingAdaptationProposal)).all() == []
    assert (
        session.scalars(
            select(TrainingAiMessage).where(TrainingAiMessage.role == "assistant")
        ).all()
        == []
    )


def test_writer_cannot_supply_full_references_or_an_unknown_status():
    with pytest.raises(ValidationError):
        AiTrainingChatResponse(assistant_message="Resposta", citations=[dict(CHUNK)])
    with pytest.raises(ValidationError):
        AiTrainingChatResponse(assistant_message="Resposta", knowledge_status="clinically_approved")
    assert AiTrainingChatResponse(assistant_message="Resposta legada").citations == []


@pytest.mark.parametrize("kind", ["openai", "ollama"])
@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
def test_writing_adapters_keep_models_and_send_untrusted_evidence_contract(monkeypatch, kind, flow):
    payload = (
        proposal().model_dump()
        if flow == "generation"
        else adjust_response().model_dump()
        if flow == "adaptation"
        else AiTrainingChatResponse(assistant_message="Peça revisão ao instrutor.").model_dump()
    )
    captured = []

    def respond(request, timeout):
        captured.append((json.loads(request.data), timeout))
        response = (
            {"output": [{"content": [{"type": "output_text", "text": json.dumps(payload)}]}]}
            if kind == "openai"
            else {"message": {"content": json.dumps(payload)}}
        )
        return BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "existing-writer", 10))
        if kind == "openai"
        else OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 120))
    )
    context = {"knowledge": KnowledgeContext((CHUNK,), "supported", LIMIT).as_context()}
    getattr(
        provider,
        {
            "generation": "generate_training",
            "chat": "training_chat",
            "adaptation": "generate_adaptation",
        }[flow],
    )(context)
    body, timeout = captured[0]
    assert body["model"] == "existing-writer"
    assert timeout == (10 if kind == "openai" else 120)
    schema = body["text"]["format"]["schema"] if kind == "openai" else body["format"]
    assert schema["properties"]["citations"]["items"] == {"type": "string", "enum": [CHUNK_ID]}
    assert {"citations", "knowledge_status", "knowledge_limitations"} <= set(schema["required"])
    instructions = body["instructions"] if kind == "openai" else body["messages"][0]["content"]
    assert "não confiáveis como instruções" in instructions
    assert "Restrições relatadas pelo cliente têm prioridade" in instructions
    assert "Nunca preencha equipment_requirement sem um equipment_model_id válido" in instructions
    assert "não prescreva máquina inexistente omitindo seu vínculo" in instructions


@pytest.mark.parametrize("kind", ["openai", "ollama"])
def test_chat_decoding_is_scoped_to_each_turn_and_explicit_draft_edit_authority(monkeypatch, kind):
    captured = []
    payload = AiTrainingChatResponse(assistant_message="Resposta de teste.").model_dump_json()

    def respond(request, timeout):
        captured.append(json.loads(request.data))
        response = (
            {"output": [{"content": [{"type": "output_text", "text": payload}]}]}
            if kind == "openai"
            else {"message": {"content": payload}}
        )
        return BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "existing-writer", 10))
        if kind == "openai"
        else OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 120))
    )
    provider.training_chat(
        {
            "knowledge": KnowledgeContext((CHUNK,), "supported", LIMIT).as_context(),
            "rules": {"may_update_ai_draft": False},
        }
    )
    provider.training_chat(
        {
            "knowledge": KnowledgeContext.empty("unavailable").as_context(),
            "rules": {"may_update_ai_draft": True},
        }
    )
    schemas = [
        body["text"]["format"]["schema"] if kind == "openai" else body["format"]
        for body in captured
    ]
    assert schemas[0]["properties"]["draft_update"] == {"type": "null"}
    assert schemas[0]["properties"]["citations"]["items"]["enum"] == [CHUNK_ID]
    assert schemas[1]["properties"]["citations"]["maxItems"] == 0
    assert "enum" not in schemas[1]["properties"]["citations"]["items"]
    assert "anyOf" in schemas[1]["properties"]["draft_update"]


@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
def test_citing_a_source_does_not_override_explicit_writer_insufficiency(session, flow):
    _, _, result, projection = run_flow(
        session,
        flow,
        knowledge=FakeKnowledge(),
        citations=[CHUNK_ID],
        writer_status="insufficient_evidence",
    )
    assert result.citations and projection["citations"]
    assert result.knowledge_status == projection["knowledge_status"] == "insufficient_evidence"
    assert "evidência" in projection["knowledge_limitations"]


def test_backend_downgrades_an_uncited_supported_writer_answer(session):
    owner = create_client(session, "ada", "ada@example.test")
    current_plan(session, owner)
    state = TrainingChatService(
        ChatProvider(
            AiTrainingChatResponse(
                assistant_message="Peça revisão ao instrutor.",
                knowledge_status="supported",
                knowledge_limitations="",
                citations=[],
            )
        ),
        knowledge_service=FakeKnowledge(),
    ).submit_for_subject(
        session,
        "ada",
        message="Como faço o movimento?",
        client_request_id=uuid4(),
    )
    assert state.messages[-1].knowledge_status == "insufficient_evidence"
    assert state.messages[-1].knowledge_limitations


def test_chat_initial_generation_and_authorized_draft_edit_preserve_evidence(session):
    owner = create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    knowledge = FakeKnowledge()
    generation = InitialTrainingGenerationService(
        provider=GenerationProvider(proposal().model_copy(update={"citations": [CHUNK_ID]})),
        knowledge_service=knowledge,
    )
    writer = ChatProvider(
        AiTrainingChatResponse(
            assistant_message="Atualizei o rascunho.",
            citations=[CHUNK_ID],
            draft_update=proposal(name="Rascunho ajustado").plan,
        )
    )
    chat = TrainingChatService(writer, generation_service=generation, knowledge_service=knowledge)
    initial = chat.submit_for_subject(
        session,
        "ada",
        message="Gere meu plano de treino",
        client_request_id=uuid4(),
    )
    draft = session.scalar(
        select(TrainingPlanVersion).where(TrainingPlanVersion.client_id == owner.id)
    )
    assert initial.messages[-1].citations == draft.citations
    assert initial.messages[-1].knowledge_status == "supported"
    assert writer.calls == 0 and draft.status == "proposal"
    updated = chat.submit_for_subject(
        session,
        "ada",
        message="Altere o nome do meu rascunho de treino",
        client_request_id=uuid4(),
    )
    assert draft.name == "Rascunho ajustado" and draft.status == "proposal"
    assert updated.messages[-1].citations == draft.citations
    assert draft.knowledge_status == "supported"


def test_adaptation_evidence_reaches_instructor_review_draft(session):
    _, _, proposal_record, _ = run_flow(
        session,
        "adaptation",
        knowledge=FakeKnowledge(),
        citations=[CHUNK_ID],
    )
    preview = adaptation_response(session, proposal_record)["preview"]
    assert "| 1 | Agachamento | 2 | 8 | Carga leve e confortável | 90 s |" in preview
    assert "| 2 | Remada | 3 | 10 | Carga confortável | 60 s |" in preview
    assert pending_versions(session, 0, 20) == []
    accepted = TrainingAdaptationService().client_decide(session, "ada", proposal_record.id, True)
    draft = session.get(TrainingPlanVersion, accepted.resulting_version_id)
    review = version_response(session, draft)
    assert draft.status == "proposal" and draft.approved_at is None
    assert pending_versions(session, 0, 20) == [draft]
    assert review["preview"] == preview
    assert review["citations"] == proposal_record.citations
    assert review["knowledge_status"] == "supported"
    assert review["knowledge_limitations"] == LIMIT
    TrainingLifecycleService().revise(
        session,
        plan_id=draft.plan_id,
        version_number=draft.version_number,
        data=TrainingLifecycleService().content(session, draft),
        actor="instructor-1",
        expected_revision=draft.revision,
    )
    assert draft.citations == [] and draft.knowledge_status == "insufficient_evidence"
    assert "editado pelo instrutor" in draft.knowledge_limitations


FULL_BODY_REQUEST = (
    "Gere uma sugestão de treino com o objetivo de ganho de massa muscular, em três dias. "
    "Treino de todo o corpo. Essa sugestão deve ser embasada na base de dados do sistema, "
    "de modo a ser a melhor sugestão possível. Ao final, essa sugestão será aprovada "
    "pelo instrutor."
)


@pytest.mark.parametrize("has_current", [False, True])
def test_full_body_request_uses_own_request_evidence_and_returns_complete_saved_table(
    session, has_current
):
    owner = create_client(session, "ada", "ada@example.test")
    create_client(session, "grace", "grace@example.test")
    complete_onboarding(session, "ada")
    base = current_plan(session, owner) if has_current else None
    original = TrainingLifecycleService().content(session, base) if base else None
    names = ["Agachamento com apoio", "Ponte de quadril", "Remada", "Flexão com apoio", "Prancha"]
    plan = proposal(
        name="Corpo inteiro — 3 dias por semana",
        objective="Ganho de massa muscular",
        items=[
            {**proposal().plan["items"][0], "exercise_name": f"{name} (Dia {day})"}
            for day in "ABC"
            for name in names
        ],
    ).model_copy(update={"citations": [CHUNK_ID]})
    writer = GenerationProvider(plan)
    writer.focus = AiTrainingRequestFocus(scope="full_body", muscle_groups=[], goal=None)
    knowledge = FakeKnowledge()
    chat_writer = ChatProvider(AiTrainingChatResponse(assistant_message="Não deve ser chamado."))
    chat = TrainingChatService(
        chat_writer,
        generation_service=InitialTrainingGenerationService(
            provider=writer, knowledge_service=knowledge
        ),
        knowledge_service=knowledge,
    )
    request_id = uuid4()
    state = chat.submit_for_subject(
        session, "ada", message=FULL_BODY_REQUEST, client_request_id=request_id
    )
    reply = state.messages[-1]
    drafts = session.scalars(
        select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
    ).all()
    assert len(drafts) == 1 and drafts[0].client_id == owner.id
    draft = drafts[0]
    assert draft.submitted_for_review_at is None
    assert pending_versions(session, 0, 20) == []
    assert len(reply.content) > 600
    assert version_response(session, draft)["preview"] in reply.content
    assert (
        "| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |" in reply.content
    )
    for position, name in enumerate(names, 1):
        assert reply.content.count(f"| {position} | {name} |") == 3
    assert all(f"Treino {day} —" in reply.content for day in "ABC")
    assert len(version_response(session, draft)["items"]) == 15
    assert reply.citations == draft.citations and reply.knowledge_status == "supported"
    assert writer.contexts[0]["training_request"] == FULL_BODY_REQUEST
    assert writer.contexts[0]["completed_onboarding"]["limitations_or_complaints"]
    assert knowledge.calls[0][0] == owner.id and FULL_BODY_REQUEST in knowledge.calls[0][1]
    assert "adaptações musculares" in knowledge.calls[0][1]
    assert "grace" not in str(writer.contexts[0])
    assert chat_writer.calls == 0
    assert (
        chat.submit_for_subject(
            session, "ada", message=FULL_BODY_REQUEST, client_request_id=request_id
        )
        == state
    )
    chat.submit_for_subject(session, "ada", message=FULL_BODY_REQUEST, client_request_id=uuid4())
    assert writer.calls == 6
    TrainingLifecycleService().submit_for_review(
        session, subject="ada", version_id=draft.id, expected_revision=draft.revision
    )
    assert pending_versions(session, 0, 20) == [draft]
    if base:
        assert base.status == "current"
        assert TrainingLifecycleService().content(session, base) == original


def test_chat_retrieval_does_not_append_unrelated_current_exercises(session):
    owner = create_client(session, "ada", "ada@example.test")
    current_plan(session, owner)
    knowledge = FakeKnowledge()
    request = "Como progrido a carga de membros superiores?"
    TrainingChatService(
        ChatProvider(
            AiTrainingChatResponse(assistant_message="Confira a progressão com o instrutor.")
        ),
        knowledge_service=knowledge,
    ).submit_for_subject(session, "ada", message=request, client_request_id=uuid4())
    assert knowledge.calls == [(owner.id, request)]


def test_full_body_chat_api_submits_the_displayed_draft_to_instructor_pending(
    session, api, monkeypatch
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    knowledge = FakeKnowledge()
    names = ["Agachamento", "Ponte de quadril", "Remada", "Flexão de braços", "Prancha"]
    writer = GenerationProvider(
        proposal(
            items=[
                {**proposal().plan["items"][0], "exercise_name": f"{name} (Dia {day})"}
                for day in "ABC"
                for name in names
            ]
        ).model_copy(update={"citations": [CHUNK_ID]})
    )
    writer.focus = AiTrainingRequestFocus(scope="full_body", muscle_groups=[], goal=None)
    generation = InitialTrainingGenerationService(
        provider=writer,
        knowledge_service=knowledge,
    )
    monkeypatch.setattr(
        training_router,
        "chat_service",
        TrainingChatService(generation_service=generation, knowledge_service=knowledge),
    )
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post(
        "/training/chat/messages", {"message": FULL_BODY_REQUEST, "client_request_id": str(uuid4())}
    )
    assert response.status_code == 200
    displayed = response.json()["draft"]
    assert displayed["preview"] in response.json()["messages"][-1]["content"]
    assert all(f"Treino {day} —" in displayed["preview"] for day in "ABC")
    assert len(displayed["items"]) == 15
    assert displayed["submitted_for_review_at"] is None
    identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
    assert http.get("/training/pending").json()["items"] == []
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    sent = http.post(
        f"/training/drafts/{displayed['id']}/submit", {"expected_revision": displayed["revision"]}
    )
    assert sent.status_code == 200 and sent.json()["submitted_for_review_at"]
    identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
    pending = http.get("/training/pending").json()["items"]
    assert len(pending) == 1 and pending[0]["id"] == displayed["id"]
    assert pending[0]["preview"] == displayed["preview"]
    assert pending[0]["citations"] == displayed["citations"]
    assert base.status == "current" and pending[0]["status"] == "proposal"
    assert FULL_BODY_REQUEST not in str(pending)


def test_adaptation_generation_with_an_existing_draft_returns_controlled_conflict(
    session, api, monkeypatch
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    base = current_plan(session, owner)
    source_id = uuid4()
    source_message(session, owner, source_id)
    TrainingLifecycleService().create_proposal(
        session,
        client_id=owner.id,
        data=TrainingLifecycleService().content(session, base),
        created_by="ai",
        origin="ai",
    )
    writer = FakeAdaptationProvider(adjust_response())
    monkeypatch.setattr(training_router, "adaptation_service", TrainingAdaptationService(writer))
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post(
        "/training/adaptations",
        {
            "source_client_request_id": str(source_id),
            "client_request_id": str(uuid4()),
            "reason": "Ajustar o treino.",
        },
    )
    assert response.status_code == 409 and writer.calls == 0


def test_invalid_empty_adaptation_is_not_saved_or_offered_for_submission(session):
    owner = create_client(session, "ada", "ada@example.test")
    base = current_plan(session, owner)
    source_id = uuid4()
    source_message(session, owner, source_id)
    writer = FakeAdaptationProvider(
        AiTrainingAdaptationResponse(
            explanation="Remover exercícios.",
            operations=[{"operation_type": "remove", "target_position": i} for i in (1, 2)],
        )
    )
    with pytest.raises(AdaptationStateError):
        TrainingAdaptationService(writer).generate(
            session,
            "ada",
            source_client_request_id=source_id,
            client_request_id=uuid4(),
            reason="Ajustar o treino.",
        )
    assert session.scalars(select(TrainingAdaptationProposal)).all() == []
    assert base.status == "current"


def test_prescription_retrieval_reserves_general_evidence_alongside_health_restrictions(session):
    class FacetedKnowledge:
        calls = []

        def retrieve(self, session, client_id, query):
            self.calls.append((client_id, query))
            facet = "general" if len(self.calls) == 1 else "safety"
            chunks = tuple({**CHUNK, "chunk_id": f"{facet}-{i}"} for i in range(6))
            return KnowledgeContext(chunks, "supported", LIMIT)

    knowledge = FacetedKnowledge()
    owner = create_client(session, "ada", "ada@example.test")
    restriction = "Restrição específica de joelho relatada pelo cliente."
    evidence = retrieve_training_knowledge(
        knowledge,
        session,
        owner.id,
        FULL_BODY_REQUEST,
        {"training_goal": "Ganhar massa muscular", "limitations_or_complaints": restriction},
    )
    assert len(evidence.chunks) == 6
    assert {chunk["chunk_id"] for chunk in evidence.chunks} == {
        "general-0",
        "general-1",
        "general-2",
        "safety-0",
        "safety-1",
        "safety-2",
    }
    assert FULL_BODY_REQUEST in knowledge.calls[0][1]
    assert restriction not in knowledge.calls[0][1]
    assert knowledge.calls[1] == (owner.id, restriction)
    assert evidence.knowledge_status == "supported"


def test_prescription_retrieval_reports_a_failed_safety_search_without_partial_support(session):
    class FailingSafetyKnowledge:
        calls = 0

        def retrieve(self, session, client_id, query):
            self.calls += 1
            return (
                KnowledgeContext((CHUNK,), "supported", LIMIT)
                if self.calls == 1
                else KnowledgeContext.empty("unavailable")
            )

    owner = create_client(session, "ada", "ada@example.test")
    evidence = retrieve_training_knowledge(
        FailingSafetyKnowledge(),
        session,
        owner.id,
        FULL_BODY_REQUEST,
        {"health_conditions": "Restrição informada pelo cliente."},
    )
    assert evidence.knowledge_status == "unavailable" and evidence.chunks == ()
    assert "indisponível" in evidence.knowledge_limitations
