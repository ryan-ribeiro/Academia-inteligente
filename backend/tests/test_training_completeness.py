"""Full-body sheets require every requested session and a bounded coverage review."""

import json
from io import BytesIO

import pytest
from sqlalchemy import select
from test_training_adaptations import current_plan
from test_training_generation import FakeProvider, complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_rag import CHUNK_ID, FULL_BODY_REQUEST, FakeKnowledge

from app.integrations import ai
from app.integrations.ai import (
    AiProviderError,
    AiTrainingPlanAssessment,
    AiTrainingRequestFocus,
    OllamaConfig,
    OllamaOnboardingProvider,
    OpenAiConfig,
    OpenAiResponsesOnboardingProvider,
)
from app.modules.training.completeness import (
    IncompleteTrainingPlanError,
    requested_training_schedule,
    validate_assessment,
    validate_requested_sessions,
)
from app.modules.training.focus import InvalidTrainingFocusError, analyze_training_focus
from app.modules.training.generation_service import (
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
    TrainingGenerationUnavailableError,
)
from app.modules.training.models import TrainingPlanVersion
from app.modules.training.presentation import proposal_preview
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import TrainingLifecycleService

FOCUS = AiTrainingRequestFocus(scope="full_body", muscle_groups=[], goal="Ganho de massa muscular")
SCHEDULE = {"session_labels": ["A", "B", "C"]}


def routine(complete=True):
    names = ["Flexão de braços", "Agachamento"]
    if complete:
        names += ["Remada", "Ponte de quadril", "Prancha", "Elevação de panturrilha"]
    return proposal(
        name="Corpo inteiro — três dias",
        objective="Ganho de massa muscular",
        items=[
            {**proposal().plan["items"][0], "exercise_name": f"{name} (Dia {day})"}
            for day in "ABC"
            for name in names
        ],
    ).model_copy(update={"citations": [CHUNK_ID]})


def assessment(complete=True):
    return AiTrainingPlanAssessment(
        sessions=[
            {
                "label": day,
                "complete": complete,
                "issues": []
                if complete
                else ["missing_upper_pull", "missing_lower_hip", "missing_trunk"],
            }
            for day in "ABC"
        ]
    )


@pytest.mark.parametrize("frequency", ["3 dias", "três dias", "TRES DIAS", "três vezes por semana"])
def test_full_body_schedule_preserves_three_complete_sheets(frequency):
    assert (
        requested_training_schedule(
            f"Gere um treino de corpo inteiro em {frequency}.", FOCUS.model_dump()
        )
        == SCHEDULE
    )


def test_targeted_requests_and_set_counts_do_not_invent_three_full_body_sheets():
    targeted = FOCUS.model_copy(update={"scope": "targeted", "muscle_groups": ["bíceps"]})
    assert (
        requested_training_schedule("Bíceps em três dias", targeted.model_dump())["session_labels"]
        == []
    )
    assert (
        requested_training_schedule("Corpo inteiro, três séries", FOCUS.model_dump())[
            "session_labels"
        ]
        == []
    )


def test_explicit_full_body_scope_is_corrected_before_it_can_use_localized_instructions():
    responses = iter(
        [
            AiTrainingRequestFocus(scope="targeted", muscle_groups=["todo o corpo"], goal=None),
            FOCUS,
        ]
    )
    contexts = []

    def extract(context):
        contexts.append(context)
        return next(responses)

    assert analyze_training_focus(extract, FULL_BODY_REQUEST)["scope"] == "full_body"
    assert len(contexts) == 2 and "focus_correction" in contexts[1]


@pytest.mark.parametrize(
    "training_request",
    ["Gere um treino para bíceps.", "Gere treino para bíceps, não para corpo inteiro."],
)
def test_a_targeted_request_does_not_accept_invented_full_body_scope(training_request):
    with pytest.raises(InvalidTrainingFocusError):
        analyze_training_focus(lambda context: FOCUS, training_request)


@pytest.mark.parametrize("labels", [["A"], ["A", "A", "C"], ["A", "B", "C", "D"]])
def test_incomplete_or_repeated_assessment_sessions_are_rejected(labels):
    review = AiTrainingPlanAssessment(
        sessions=[{"label": day, "complete": True, "issues": []} for day in labels]
    )
    with pytest.raises(IncompleteTrainingPlanError):
        validate_assessment(review, {"training_schedule": SCHEDULE})


def test_a_complete_flag_does_not_override_reported_gaps():
    review = assessment(False)
    review.sessions[0].complete = True
    with pytest.raises(IncompleteTrainingPlanError):
        validate_assessment(review, {"training_schedule": SCHEDULE})


@pytest.mark.parametrize("labels", [[""], ["A", "B"], ["A", "B", "C", "D"], ["", "A", "B", "C"]])
def test_unassigned_missing_or_extra_sheet_is_rejected(labels):
    plan = TrainingPlanVersionInput.model_validate(
        proposal(
            items=[
                {
                    **proposal().plan["items"][0],
                    "exercise_name": "Agachamento" + (f" (Dia {day})" if day else ""),
                }
                for day in labels
            ]
        ).plan
    )
    with pytest.raises(IncompleteTrainingPlanError):
        validate_requested_sessions(plan, {"training_schedule": SCHEDULE})


class ReviewingWriter(FakeProvider):
    focus = FOCUS

    def __init__(self, outcome):
        super().__init__(routine(False))
        self.outcome = outcome
        self.reviews = []

    def generate_training(self, context):
        if self.outcome == "late_failure" and context["training_session"]["label"] == "B":
            self.result = AiProviderError("configuration", retryable=False)
            return super().generate_training(context)
        self.result = routine(self.calls > 0 and self.outcome != "incomplete")
        if self.calls and self.outcome == "invalid_citations":
            self.result = self.result.model_copy(update={"citations": ["invented"]})
        return super().generate_training(context)

    def assess_training(self, context):
        self.reviews.append(context)
        if self.outcome == "review_outage":
            raise AiProviderError("timeout_or_network", retryable=False)
        result = assessment(self.calls > 1 and self.outcome != "incomplete")
        result.sessions = [
            item
            for item in result.sessions
            if item.label in context["training_schedule"]["session_labels"]
        ]
        return result


@pytest.mark.parametrize(
    "outcome", ["corrected", "incomplete", "invalid_citations", "review_outage", "late_failure"]
)
def test_incomplete_body_sheets_are_corrected_once_before_atomic_persistence(session, outcome):
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    current_content = lifecycle.content(session, base)
    draft = lifecycle.create_proposal(
        session,
        client_id=owner.id,
        data=TrainingPlanVersionInput.model_validate(proposal().plan),
        created_by="ai",
        origin="ai",
    )
    lifecycle.submit_for_review(
        session, subject="client", version_id=draft.id, expected_revision=draft.revision
    )
    original_content, original_revision = lifecycle.content(session, draft), draft.revision
    writer, knowledge = ReviewingWriter(outcome), FakeKnowledge()
    service = InitialTrainingGenerationService(provider=writer, knowledge_service=knowledge)

    def run():
        return service.generate_for_subject(
            session, "client", training_request=FULL_BODY_REQUEST, replace_existing=True
        )

    if outcome == "corrected":
        run()
        assert len(lifecycle.content(session, draft).items) == 18
        assert draft.revision == original_revision + 1 and draft.submitted_for_review_at is None
        preview = proposal_preview(session, draft)
        assert all(f"Treino {day} —" in preview for day in "ABC")
        assert preview.count("| 1 | Flexão de braços |") == 3
    else:
        with pytest.raises(
            TrainingGenerationUnavailableError
            if outcome in {"review_outage", "late_failure"}
            else InvalidTrainingGenerationError
        ):
            run()
        assert lifecycle.content(session, draft) == original_content
        assert draft.revision == original_revision and draft.submitted_for_review_at is not None
    assert lifecycle.content(session, base) == current_content and base.status == "current"
    assert (
        len(
            session.scalars(
                select(TrainingPlanVersion).where(TrainingPlanVersion.status == "proposal")
            ).all()
        )
        == 1
    )
    assert (
        writer.calls
        == {
            "review_outage": 1,
            "corrected": 4,
            "late_failure": 3,
            "incomplete": 2,
            "invalid_citations": 2,
        }[outcome]
    )
    assert writer.reviews[0]["training_request"] == FULL_BODY_REQUEST
    assert writer.reviews[0]["completed_onboarding"]["limitations_or_complaints"]
    assert writer.reviews[0]["knowledge"] == writer.contexts[0]["knowledge"]
    assert writer.reviews[0]["training_schedule"] == {"session_labels": ["A"]}
    assert writer.reviews[0]["training_session"]["all_session_labels"] == SCHEDULE["session_labels"]
    if writer.calls > 1:
        assert writer.contexts[1]["knowledge"] == writer.contexts[0]["knowledge"]
        assert writer.contexts[1]["selection_correction"]["completeness_issues"]


def test_three_sheets_preserve_conservative_evidence_status_and_deduplicate_citations(session):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    writer = FakeProvider(routine())
    writer.focus = FOCUS
    generate = writer.generate_training

    def respond(context):
        response = generate(context)
        return response.model_copy(
            update={
                "knowledge_status": "insufficient_evidence"
                if context["training_session"]["label"] == "B"
                else "supported",
            }
        )

    writer.generate_training = respond
    draft = InitialTrainingGenerationService(
        provider=writer, knowledge_service=FakeKnowledge()
    ).generate_for_subject(session, "client", training_request=FULL_BODY_REQUEST)
    assert draft.knowledge_status == "insufficient_evidence"
    assert [citation["chunk_id"] for citation in draft.citations] == [CHUNK_ID]
    assert "suficiente" in draft.knowledge_limitations
    assert [context["training_session"]["label"] for context in writer.contexts] == ["A", "B", "C"]


@pytest.mark.parametrize("conflicting_day", [False, True])
def test_server_assigns_only_the_explicitly_requested_day_without_overwriting_conflicts(
    session, conflicting_day
):
    create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")

    class UnlabelledWriter(FakeProvider):
        focus = FOCUS

        def generate_training(self, context):
            self.calls += 1
            self.contexts.append(context)
            items = [
                {
                    **item,
                    "exercise_name": item["exercise_name"].replace(" (Dia A)", "")
                    + (" (Dia B)" if conflicting_day else ""),
                }
                for item in routine().plan["items"][:6]
            ]
            return proposal(items=items).model_copy(update={"citations": [CHUNK_ID]})

    writer = UnlabelledWriter(routine())
    service = InitialTrainingGenerationService(provider=writer, knowledge_service=FakeKnowledge())
    if conflicting_day:
        with pytest.raises(InvalidTrainingGenerationError):
            service.generate_for_subject(session, "client", training_request=FULL_BODY_REQUEST)
        assert session.scalars(select(TrainingPlanVersion)).all() == []
        assert writer.calls == 2
    else:
        draft = service.generate_for_subject(session, "client", training_request=FULL_BODY_REQUEST)
        items = TrainingLifecycleService.content(session, draft).items
        assert len(items) == 18
        assert all(
            sum(item.exercise_name.endswith(f"(Dia {day})") for item in items) == 6 for day in "ABC"
        )
        assert writer.calls == 3


@pytest.mark.parametrize("kind", ["openai", "ollama"])
def test_coverage_review_uses_the_existing_adapter_and_a_strict_bounded_contract(monkeypatch, kind):
    captured = []

    def respond(request, timeout):
        captured.append(json.loads(request.data))
        text = assessment().model_dump_json()
        payload = (
            {"message": {"content": text}}
            if kind == "ollama"
            else {"output": [{"content": [{"type": "output_text", "text": text}]}]}
        )
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 120))
        if kind == "ollama"
        else OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "existing-writer", 10))
    )
    result = provider.assess_training(
        {"training_schedule": SCHEDULE, "proposed_plan": routine().plan}
    )
    assert result == assessment()
    body = captured[0]
    schema = body["format"] if kind == "ollama" else body["text"]["format"]["schema"]
    assert body["model"] == "existing-writer" and schema["additionalProperties"] is False
    assert schema["properties"]["sessions"]["maxItems"] == 3
    assert schema["$defs"]["AiTrainingSessionAssessment"]["properties"]["label"]["enum"] == [
        "A",
        "B",
        "C",
    ]
    if kind == "ollama":
        assert body["options"]["temperature"] == 0
