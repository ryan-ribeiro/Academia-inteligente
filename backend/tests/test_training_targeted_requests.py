"""Muscle-targeted questions produce a sheet, direct review and an appendable draft."""

import json
import logging
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_adaptations import (
    FakeAdaptationProvider,
    adjust_response,
    current_plan,
    source_message,
)
from test_training_chat import FakeProvider as ChatWriter
from test_training_generation import FakeProvider as PlanWriter
from test_training_generation import complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_rag import CHUNK_ID, FULL_BODY_REQUEST, FakeKnowledge
from test_training_review import api as api

from app.integrations import ai
from app.integrations.ai import (
    AiProviderError,
    AiTrainingChatResponse,
    AiTrainingRequestFocus,
    OllamaConfig,
    OllamaOnboardingProvider,
    OpenAiConfig,
    OpenAiResponsesOnboardingProvider,
)
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training import router as training_router
from app.modules.training.adaptation_service import TrainingAdaptationService
from app.modules.training.chat_service import (
    TrainingChatDraftUpdateError,
    TrainingChatService,
    TrainingChatUnavailableError,
)
from app.modules.training.generation_service import InitialTrainingGenerationService
from app.modules.training.models import (
    TrainingAdaptationOperation,
    TrainingPlan,
    TrainingPlanVersion,
)
from app.modules.training.review_service import review_metadata
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import (
    ConcurrentTrainingUpdateError,
    InvalidTrainingContentError,
    InvalidTrainingTransitionError,
    TrainingLifecycleService,
)

REQUEST = "Que exercícios posso fazer para ganho de massa muscular no bíceps?"


def focused_service(groups, names, scope="targeted"):
    writer = PlanWriter(
        proposal(
            name=" e ".join(groups) or "Corpo inteiro",
            objective="Ganho de massa muscular",
            items=[{**proposal().plan["items"][0], "exercise_name": name} for name in names],
        ).model_copy(update={"citations": [CHUNK_ID]})
    )
    writer.focus = AiTrainingRequestFocus(
        scope=scope, muscle_groups=groups, goal="Ganho de massa muscular"
    )
    writer.focus_contexts = []

    def analyze(context):
        writer.focus_contexts.append(context)
        return writer.focus

    writer.analyze_training_request = analyze
    knowledge = FakeKnowledge()
    chat_writer = ChatWriter(AiTrainingChatResponse(assistant_message="Não deve ser chamado."))
    service = TrainingChatService(
        chat_writer,
        generation_service=InitialTrainingGenerationService(
            provider=writer, knowledge_service=knowledge
        ),
        knowledge_service=knowledge,
    )
    return service, writer, knowledge, chat_writer


@pytest.mark.parametrize(
    ("user_message", "groups", "names"),
    [
        (REQUEST, ["Bíceps"], ["Rosca direta", "Rosca alternada", "Rosca martelo"]),
        (
            "Quais exercícios posso fazer para hipertrofia no quadríceps?",
            ["Quadríceps"],
            ["Extensão de joelho"],
        ),
        (
            "Sugira exercícios para peito e tríceps.",
            ["Peito", "Tríceps"],
            ["Flexão de braços", "Extensão de cotovelo"],
        ),
    ],
)
@pytest.mark.parametrize("has_current", [False, True])
def test_question_routes_through_ai_focus_and_scoped_retrieval_before_generation(
    session, user_message, groups, names, has_current
):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner) if has_current else None
    service, writer, knowledge, chat_writer = focused_service(groups, names)
    request_id = uuid4()
    result = service.submit_for_subject(
        session, "client", message=user_message, client_request_id=request_id
    )
    draft = session.scalar(
        select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
    )
    assert writer.focus_contexts == [
        {
            "training_request": user_message,
            "focus_constraints": {"allowed_scopes": ["targeted", "unspecified"]},
        }
    ]
    assert writer.contexts[0]["training_focus"]["muscle_groups"] == groups
    assert writer.contexts[0]["training_focus"]["goal"] == "Ganho de massa muscular"
    assert writer.contexts[0]["completed_onboarding"]["limitations_or_complaints"] == (
        "Evitar impacto alto no joelho"
    )
    assert writer.contexts[0]["completed_onboarding"]["health_conditions"] == (
        "Histórico informado pelo cliente"
    )
    assert all(group in knowledge.calls[0][1] for group in groups)
    assert "Ganhar força" not in knowledge.calls[0][1]
    assert all(name.split(" (Dia")[0] in result.messages[-1].content for name in names)
    assert [
        item.exercise_name for item in TrainingLifecycleService.content(session, draft).items
    ] == names
    assert chat_writer.calls == 0 and draft.submitted_for_review_at is None
    assert result.messages[-1].citations == draft.citations
    service.submit_for_subject(
        session, "client", message=user_message, client_request_id=request_id
    )
    assert writer.calls == 1
    service.submit_for_subject(session, "client", message=user_message, client_request_id=uuid4())
    assert writer.calls == 2
    if base:
        assert base.status == "current"


def test_explicit_full_body_request_preserves_the_broader_scope(session):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    service, writer, _, _ = focused_service(
        [], ["Agachamento", "Flexão de braços", "Remada"], scope="full_body"
    )
    result = service.submit_for_subject(
        session,
        "client",
        message="Quais exercícios posso fazer para hipertrofia do corpo inteiro?",
        client_request_id=uuid4(),
    )
    assert writer.contexts[0]["training_focus"]["scope"] == "full_body"
    assert all(name in result.messages[-1].content for name in ["Agachamento", "Remada"])


@pytest.mark.parametrize("has_current", [False, True])
@pytest.mark.parametrize("failure", [None, "unavailable", "schema"])
@pytest.mark.parametrize("retry_same_id", [False, True])
def test_biceps_sheet_can_be_replaced_by_full_body_request_after_failure_or_resend(
    session, has_current, failure, retry_same_id
):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner) if has_current else None
    base_id = base.id if base else None
    lifecycle = TrainingLifecycleService()
    original_current = lifecycle.content(session, base) if base else None
    service, writer, knowledge, chat_writer = focused_service(["Bíceps"], ["Rosca direta"])
    service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    draft = lifecycle.find_proposal(session, client_id=owner.id)
    draft_id = draft.id
    lifecycle.submit_for_review(
        session, subject="client", version_id=draft.id, expected_revision=draft.revision
    )
    biceps_content = lifecycle.content(session, draft)
    biceps_revision = draft.revision
    request_id = uuid4()
    writer.focus = AiTrainingRequestFocus(scope="full_body", muscle_groups=[], goal="Hipertrofia")
    if failure:
        writer.result = (
            AiProviderError("configuration", retryable=False)
            if failure == "unavailable"
            else proposal(items=[])
        )
        with pytest.raises(
            TrainingChatUnavailableError
            if failure == "unavailable"
            else TrainingChatDraftUpdateError
        ):
            service.submit_for_subject(
                session, "client", message=FULL_BODY_REQUEST, client_request_id=request_id
            )
        assert lifecycle.content(session, draft) == biceps_content
        assert draft.revision == biceps_revision and draft.submitted_for_review_at is not None
        session.expunge_all()
        if not retry_same_id:
            request_id = uuid4()

    names = ["Agachamento (Dia A)", "Remada (Dia B)", "Flexão de braços (Dia C)"]
    writer.result = proposal(
        name="Corpo inteiro — três dias",
        objective="Ganho de massa muscular",
        items=[{**proposal().plan["items"][0], "exercise_name": name} for name in names],
    ).model_copy(update={"citations": [CHUNK_ID]})
    result = service.submit_for_subject(
        session, "client", message=FULL_BODY_REQUEST, client_request_id=request_id
    )
    draft = lifecycle.find_proposal(session, client_id=owner.id)
    assert draft.id == draft_id and draft.revision == biceps_revision + 1
    assert draft.status == "proposal" and draft.submitted_for_review_at is None
    assert [item.exercise_name for item in lifecycle.content(session, draft).items] == names
    assert "Corpo inteiro — 3 dias" in result.messages[-1].content
    assert "Rosca direta" not in result.messages[-1].content
    assert all(name.split(" (Dia")[0] in result.messages[-1].content for name in names)
    assert all(f"Treino {day} —" in result.messages[-1].content for day in "ABC")
    assert writer.contexts[-1]["training_request"] == FULL_BODY_REQUEST
    assert writer.contexts[-1]["training_focus"]["scope"] == "full_body"
    assert any(FULL_BODY_REQUEST in query for _, query in knowledge.calls)
    assert result.messages[-1].citations == draft.citations and draft.citations
    calls = writer.calls
    replay = service.submit_for_subject(
        session,
        "client",
        message=FULL_BODY_REQUEST,
        client_request_id=request_id if retry_same_id else uuid4(),
    )
    assert writer.calls == calls + (0 if retry_same_id else 3)
    if retry_same_id:
        assert replay == result
    assert chat_writer.calls == 0
    assert (
        len(
            session.scalars(
                select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
            ).all()
        )
        == 1
    )
    if base:
        base = session.get(TrainingPlanVersion, base_id)
        assert base.status == "current" and lifecycle.content(session, base) == original_current


def test_model_added_muscles_are_corrected_before_retrieval_or_writing(session):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    service, writer, knowledge, _ = focused_service(["Bíceps"], ["Rosca direta"])
    responses = iter(
        [
            AiTrainingRequestFocus(
                scope="targeted", muscle_groups=["Bíceps", "Tríceps", "Ombros"], goal="Hipertrofia"
            ),
            writer.focus,
        ]
    )

    def analyze(context):
        assert knowledge.calls == [] and writer.calls == 0
        writer.focus_contexts.append(context)
        return next(responses)

    writer.analyze_training_request = analyze
    service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    assert len(writer.focus_contexts) == 2
    correction = writer.focus_contexts[1]
    assert correction["training_request"] == REQUEST
    assert correction["focus_correction"]["rejected_focus"]["muscle_groups"] == [
        "Bíceps",
        "Tríceps",
        "Ombros",
    ]
    assert writer.contexts[0]["training_focus"]["muscle_groups"] == ["Bíceps"]
    assert all("Tríceps" not in query and "Ombros" not in query for _, query in knowledge.calls)


def test_full_body_focus_correction_keeps_broader_scope_before_retrieval(session):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    service, writer, knowledge, _ = focused_service(
        [],
        ["Agachamento (Dia A)", "Agachamento com apoio (Dia B)", "Afundo com apoio (Dia C)"],
        scope="full_body",
    )
    responses = iter(
        [
            AiTrainingRequestFocus(scope="full_body", muscle_groups=["todo corpo"], goal=None),
            writer.focus,
        ]
    )

    def analyze(context):
        assert knowledge.calls == [] and writer.calls == 0
        writer.focus_contexts.append(context)
        return next(responses)

    writer.analyze_training_request = analyze
    service.submit_for_subject(
        session, "client", message=FULL_BODY_REQUEST, client_request_id=uuid4()
    )
    correction = writer.focus_contexts[1]["focus_correction"]["instruction"]
    assert "scope=full_body" in correction and "muscle_groups=[]" in correction
    assert writer.contexts[0]["training_focus"]["scope"] == "full_body"
    assert writer.contexts[0]["training_focus"]["muscle_groups"] == []
    assert FULL_BODY_REQUEST in knowledge.calls[0][1]


@pytest.mark.parametrize("groups", [["Bíceps", "Tríceps"], ["Braços"], ["Bícep"]])
def test_persistently_ungrounded_focus_fails_without_retrieval_or_draft_changes(
    session, groups, caplog
):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    lifecycle = TrainingLifecycleService()
    draft = lifecycle.create_proposal(
        session,
        client_id=owner.id,
        data=TrainingPlanVersionInput.model_validate(proposal().plan),
        created_by="ai",
        origin="ai",
    )
    original = lifecycle.content(session, draft)
    revision = draft.revision
    service, writer, knowledge, _ = focused_service(groups, ["Rosca direta"])
    with pytest.raises(TrainingChatDraftUpdateError):
        service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    assert len(writer.focus_contexts) == 2 and writer.calls == 0 and knowledge.calls == []
    assert draft.revision == revision and lifecycle.content(session, draft) == original
    event = json.loads(caplog.records[-1].message)
    assert event["outcome"] == "draft_blocked"
    assert event["reason"] == "invalid_training_focus" and event["retry_count"] == 1
    assert REQUEST not in caplog.text and str(owner.id) not in caplog.text


@pytest.mark.parametrize(
    "group,training_request",
    [
        ("PARTE ANTERIOR DA COXA", "Quero exercícios para a parte   anterior da coxa."),
        ("BICEPS", "Que exercícios posso fazer para bíceps?"),
        ("Bíceps", "Que exercícios posso fazer para biceps?"),
    ],
)
def test_focus_grounding_accepts_case_accents_and_whitespace_without_a_muscle_dictionary(
    group, training_request
):
    from app.modules.training.focus import analyze_training_focus

    focus = AiTrainingRequestFocus(scope="targeted", muscle_groups=[group], goal="Hipertrofia")
    result = analyze_training_focus(lambda context: focus, training_request)
    assert result["muscle_groups"] == [group]


def test_generic_adaptation_question_keeps_the_confirmation_flow(session):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    service, writer, _, chat_writer = focused_service(["Bíceps"], ["Rosca direta"])
    chat_writer.result = AiTrainingChatResponse(
        assistant_message="Posso preparar uma adaptação para você conferir.",
        adaptation_suggested=True,
        adaptation_reason="Dor relatada pelo cliente.",
    )
    result = service.submit_for_subject(
        session,
        "client",
        message="Pode me sugerir uma adaptação para minha dor?",
        client_request_id=uuid4(),
    )
    assert writer.calls == 0 and writer.focus_contexts == []
    assert chat_writer.calls == 1 and result.messages[-1].adaptation_suggested
    assert session.scalars(select(TrainingPlanVersion)).all() == [base]


def test_new_focus_revises_only_the_existing_draft_and_clears_prior_submission(session):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    service, writer, _, _ = focused_service(["Bíceps"], ["Rosca direta"])
    existing = InitialTrainingGenerationService(
        provider=writer, knowledge_service=FakeKnowledge()
    ).generate_for_subject(session, "client")
    TrainingLifecycleService().submit_for_review(
        session, subject="client", version_id=existing.id, expected_revision=existing.revision
    )
    writer.focus = AiTrainingRequestFocus(
        scope="targeted", muscle_groups=["Tríceps"], goal="Hipertrofia"
    )
    writer.result = proposal(
        name="Tríceps",
        items=[{**proposal().plan["items"][0], "exercise_name": "Extensão de cotovelo"}],
    )
    service.submit_for_subject(
        session,
        "client",
        message="Quais exercícios posso fazer para hipertrofia no tríceps?",
        client_request_id=uuid4(),
    )
    assert session.scalars(
        select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
    ).all() == [existing]
    assert existing.name == "Tríceps" and existing.submitted_for_review_at is None
    assert base.status == "current"


@pytest.mark.parametrize("draft_source", ["instructor", "adaptation"])
def test_targeted_request_reuses_a_current_plan_edit_as_an_appendable_standalone_sheet(
    session, draft_source
):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    original = lifecycle.content(session, base)
    adaptation = None
    if draft_source == "adaptation":
        source_id = uuid4()
        source_message(session, owner, source_id)
        adaptations = TrainingAdaptationService(
            FakeAdaptationProvider(adjust_response()), knowledge_service=FakeKnowledge()
        )
        adaptation = adaptations.generate(
            session,
            "client",
            source_client_request_id=source_id,
            client_request_id=uuid4(),
            reason="O agachamento incomoda meu joelho.",
        )
        adaptations.client_decide(session, "client", adaptation.id, True)
        editing = session.get(TrainingPlanVersion, adaptation.resulting_version_id)
        operations = session.scalars(select(TrainingAdaptationOperation)).all()
    else:
        editing = lifecycle.create_revision(
            session,
            plan_id=base.plan_id,
            version_number=base.version_number,
            data=original,
            actor="instructor-1",
        )
    draft_id, revision = editing.id, editing.revision
    service, _, _, _ = focused_service(["Bíceps"], ["Rosca direta"])
    service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    draft = lifecycle.find_proposal(session, client_id=owner.id)
    assert draft.id == draft_id and draft.revision == revision + 1
    assert draft.plan_id != base.plan_id and draft.submitted_for_review_at is None
    assert lifecycle.content(session, base) == original and base.status == "current"
    if adaptation is not None:
        assert adaptation.status == "superseded" and adaptation.resulting_version_id is None
        assert session.scalars(select(TrainingAdaptationOperation)).all() == operations
    lifecycle.submit_for_review(
        session, subject="client", version_id=draft.id, expected_revision=draft.revision
    )
    assert review_metadata(session, draft)["append_target"]["id"] == str(base.id)
    lifecycle.append_to_current(
        session,
        version_id=draft.id,
        expected_revision=draft.revision,
        current_version_id=base.id,
        expected_current_revision=base.revision,
        selected_positions=[1],
    )
    assert [item.exercise_name for item in lifecycle.content(session, draft).items] == [
        *[item.exercise_name for item in original.items],
        "Rosca direta",
    ]
    assert draft.plan_id == base.plan_id and base.status == "current"


def test_replacing_a_current_plan_edit_rolls_back_when_the_chat_reply_cannot_be_saved(
    session, monkeypatch
):
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
    original_plan_id, original_revision = draft.plan_id, draft.revision
    plan_ids = session.scalars(select(TrainingPlan.id)).all()
    service, _, _, _ = focused_service(["Bíceps"], ["Rosca direta"])
    summary = service._bounded_summary

    def fail_reply(session, conversation_id, exclude=None):
        if exclude is None:
            raise RuntimeError("reply persistence failure")
        return summary(session, conversation_id, exclude)

    monkeypatch.setattr(service, "_bounded_summary", fail_reply)
    with pytest.raises(RuntimeError, match="reply persistence failure"):
        service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    session.rollback()
    assert draft.plan_id == original_plan_id and draft.revision == original_revision
    assert lifecycle.content(session, draft) == original
    assert lifecycle.content(session, base) == original and base.status == "current"
    assert session.scalars(select(TrainingPlan.id)).all() == plan_ids


def test_client_click_sends_targeted_sheet_and_instructor_appends_then_approves(
    session, api, monkeypatch
):
    http, identity = api
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    original = TrainingLifecycleService.content(session, base)
    chat, _, _, _ = focused_service(["Bíceps"], ["Rosca direta", "Rosca alternada"])
    monkeypatch.setattr(training_router, "chat_service", chat)
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    response = http.post(
        "/training/chat/messages", {"message": REQUEST, "client_request_id": str(uuid4())}
    )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["submitted_for_review_at"] is None
    sent = http.post(
        f"/training/drafts/{draft['id']}/submit", {"expected_revision": draft["revision"]}
    )
    assert sent.status_code == 200
    identity.identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))
    pending = http.get("/training/pending").json()["items"]
    assert len(pending) == 1 and pending[0]["id"] == draft["id"]
    source = pending[0]
    target = source["append_target"]
    payload = {
        "expected_revision": source["revision"],
        "current_version_id": target["id"],
        "expected_current_revision": target["revision"],
        "selected_positions": [2],
    }
    merged = http.post(f"/training/pending/{draft['id']}/append-to-current", payload)
    assert merged.status_code == 200
    combined = merged.json()
    assert combined["plan_id"] == str(base.plan_id) and combined["version_number"] == 2
    assert combined["append_target"] is None
    assert [item["exercise_name"] for item in combined["items"]] == [
        *[item.exercise_name for item in original.items],
        "Rosca alternada",
    ]
    assert combined["status"] == "proposal" and base.status == "current"
    assert TrainingLifecycleService.content(session, base) == original
    assert (
        http.post(f"/training/pending/{draft['id']}/append-to-current", payload).status_code == 409
    )
    approved = http.post(
        f"/training/plans/{base.plan_id}/versions/2/approve",
        {"expected_revision": combined["revision"]},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "current"
    assert base.status == "superseded"
    assert TrainingLifecycleService.content(session, base) == original
    assert http.get("/training/pending").json()["items"] == []


@pytest.mark.parametrize("role", ["client", "admin", "employee", "attendant"])
def test_append_requires_instructor_role_even_for_direct_requests(session, api, role):
    http, identity = api
    create_client(session, "client", "client@example.test")
    identity.identity = AuthenticatedIdentity("client", "client", (role,))
    response = http.post(
        f"/training/pending/{uuid4()}/append-to-current",
        {
            "expected_revision": 1,
            "current_version_id": str(uuid4()),
            "expected_current_revision": 1,
            "selected_positions": [1],
        },
    )
    assert response.status_code == 403


def append_fixture(session, *, submitted=True):
    owner = create_client(session, "client", "client@example.test")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    draft = lifecycle.create_proposal(
        session,
        client_id=owner.id,
        data=TrainingPlanVersionInput.model_validate(proposal(name="Bíceps").plan),
        created_by="ai",
        origin="ai",
    )
    if submitted:
        lifecycle.submit_for_review(
            session, subject="client", version_id=draft.id, expected_revision=draft.revision
        )
    options = dict(
        version_id=draft.id,
        expected_revision=draft.revision,
        current_version_id=base.id,
        expected_current_revision=base.revision,
        selected_positions=[1],
    )
    return lifecycle, base, draft, options


@pytest.mark.parametrize("fault", ["unsubmitted", "stale_draft", "stale_current", "wrong_client"])
def test_append_rejects_unreviewable_stale_or_cross_client_targets_atomically(session, fault):
    lifecycle, base, draft, options = append_fixture(session, submitted=fault != "unsubmitted")
    original = lifecycle.content(session, draft)
    source_plan = draft.plan_id
    if fault == "stale_draft":
        options["expected_revision"] += 1
    elif fault == "stale_current":
        options["expected_current_revision"] += 1
    elif fault == "wrong_client":
        other = create_client(session, "other", "other@example.test")
        options["current_version_id"] = current_plan(session, other).id
    expected = (
        InvalidTrainingTransitionError if fault == "unsubmitted" else ConcurrentTrainingUpdateError
    )
    with pytest.raises(expected):
        lifecycle.append_to_current(session, **options)
    assert draft.plan_id == source_plan and lifecycle.content(session, draft) == original
    assert base.status == "current"


def test_failed_append_commit_restores_draft_contents_and_leaves_current_intact(
    session, monkeypatch
):
    lifecycle, base, draft, options = append_fixture(session)
    original = lifecycle.content(session, draft)
    source_plan = draft.plan_id
    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("failure")))
        with pytest.raises(RuntimeError):
            lifecycle.append_to_current(session, **options)
    session.expire_all()
    assert draft.plan_id == source_plan and draft.revision == options["expected_revision"]
    assert lifecycle.content(session, draft) == original and base.status == "current"


@pytest.mark.parametrize("positions", [[], [1, 1], [2], [0], [True]])
def test_append_rejects_empty_duplicate_or_invalid_exercise_selections(session, positions):
    lifecycle, base, draft, options = append_fixture(session)
    original = lifecycle.content(session, draft)
    source_plan = draft.plan_id
    options["selected_positions"] = positions
    with pytest.raises(InvalidTrainingContentError):
        lifecycle.append_to_current(session, **options)
    assert draft.plan_id == source_plan and lifecycle.content(session, draft) == original
    assert base.status == "current"


@pytest.mark.parametrize("kind", ["openai", "ollama"])
def test_focus_analysis_uses_existing_adapter_and_strict_contract(monkeypatch, kind):
    captured = []
    focus = {"scope": "targeted", "muscle_groups": ["Bíceps"], "goal": "Hipertrofia"}

    def respond(request, timeout):
        captured.append(json.loads(request.data))
        payload = (
            {"output": [{"content": [{"type": "output_text", "text": json.dumps(focus)}]}]}
            if kind == "openai"
            else {"message": {"content": json.dumps(focus)}}
        )
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "existing-writer", 10))
        if kind == "openai"
        else OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 120))
    )
    assert provider.analyze_training_request({"training_request": REQUEST}).model_dump() == focus
    body = captured[0]
    schema = body["text"]["format"]["schema"] if kind == "openai" else body["format"]
    assert body["model"] == "existing-writer" and not schema["additionalProperties"]
    assert set(schema["required"]) == {"scope", "muscle_groups", "goal"}
    if kind == "ollama":
        assert body["options"]["num_ctx"] == 16384


@pytest.mark.parametrize("failure", ["unavailable", "missing_muscles"])
def test_failed_focus_analysis_does_not_fall_back_to_full_body(session, failure):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    service, writer, _, _ = focused_service([], [])
    if failure == "unavailable":

        def fail(context):
            raise AiProviderError("unavailable", retryable=False)

        writer.analyze_training_request = fail
    error_type = (
        TrainingChatUnavailableError if failure == "unavailable" else TrainingChatDraftUpdateError
    )
    with pytest.raises(error_type):
        service.submit_for_subject(session, "client", message=REQUEST, client_request_id=uuid4())
    assert writer.calls == 0 and session.scalars(select(TrainingPlanVersion)).all() == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (REQUEST, True),
        ("Por favor, que exercícios posso fazer para bíceps?", True),
        ("Olá! Que exercícios posso fazer para bíceps?", True),
        ("Como treinar antebraços?", True),
        ("Pode me sugerir exercícios para glúteos?", True),
        ("Poderia recomendar uma ficha para peitoral?", True),
        ("Quero exercícios para costas.", True),
        ("Não quero exercícios para bíceps.", False),
        ("Que exercícios devo evitar?", False),
        ("Quais exercícios estão no meu plano?", False),
        ("Como faço a rosca direta?", False),
        ("Pode me sugerir uma adaptação para minha dor?", False),
        ("Pode me sugerir uma legenda?", False),
        ("Poderia indicar como executar a rosca?", False),
    ],
)
def test_request_recognition_does_not_hardcode_muscles(message, expected):
    assert TrainingChatService._requests_exercise_suggestion(message) is expected
