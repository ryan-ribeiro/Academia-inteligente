"""Every AI sheet must pass exercise review, independently of its requested scope."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_adaptations import adjust_response, current_plan, source_message
from test_training_chat import FakeProvider as ChatProvider
from test_training_generation import FakeProvider, complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_rag import FakeKnowledge

from app.integrations.ai import (
    AiProviderError,
    AiTrainingChatResponse,
    AiTrainingPlanAssessment,
    AiTrainingRequestFocus,
)
from app.modules.training.adaptation_service import (
    AdaptationStateError,
    AdaptationUnavailableError,
    TrainingAdaptationService,
)
from app.modules.training.chat_service import (
    TrainingChatDraftUpdateError,
    TrainingChatService,
    TrainingChatUnavailableError,
)
from app.modules.training.completeness import (
    IncompleteTrainingPlanError,
    normalize_exercise_resource,
    training_review_context,
    validate_exercise_names,
)
from app.modules.training.generation_service import (
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
    TrainingGenerationUnavailableError,
)
from app.modules.training.models import TrainingAdaptationProposal, TrainingAiMessage
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import TrainingLifecycleService


@pytest.mark.parametrize(
    "scope,training_request",
    [
        ("targeted", "Sugira exercícios para bíceps."),
        ("unspecified", "Gere um treino para ganhar massa muscular."),
        (None, ""),
    ],
)
def test_targeted_unspecified_and_onboarding_only_generation_always_call_review(
    session, scope, training_request
):
    owner = create_client(session, "owner", "owner@example.test")
    complete_onboarding(session, "owner")
    create_client(session, "other", "other@example.test")
    complete_onboarding(
        session, "other", limitations_or_complaints="Other client's private context"
    )
    writer = FakeProvider(
        proposal(items=[{**proposal().plan["items"][0], "exercise_name": "Rosca direta"}])
    )
    if scope:
        writer.focus = AiTrainingRequestFocus(
            scope=scope, muscle_groups=["bíceps"] if scope == "targeted" else [], goal=None
        )
    knowledge = FakeKnowledge()
    result = InitialTrainingGenerationService(
        provider=writer, knowledge_service=knowledge
    ).generate_for_subject(session, "owner", training_request=training_request)
    assert result.client_id == owner.id and result.status == "proposal"
    assert len(writer.review_contexts) == 1
    review = writer.review_contexts[0]
    assert review["proposed_plan"] == TrainingPlanVersionInput.model_validate(
        writer.result.plan
    ).model_dump(mode="json")
    assert review["training_focus"] == (writer.focus.model_dump() if scope else None)
    assert review["training_schedule"] == {"session_labels": [""]}
    assert review["knowledge"] == writer.contexts[0]["knowledge"]
    assert review["completed_onboarding"] == writer.contexts[0]["completed_onboarding"]
    assert "Other client's private context" not in str(review)


class ReviewingWriter(FakeProvider):
    def __init__(self, outcome):
        super().__init__(proposal())
        self.outcome = outcome
        self.review_contexts = []

    def _name(self):
        return (
            "Movimento não identificável"
            if self.calls == 1 or self.outcome == "invalid"
            else "Agachamento com apoio"
        )

    def generate_training(self, context):
        self.calls += 1
        self.contexts.append(context)
        return proposal(items=[{**proposal().plan["items"][0], "exercise_name": self._name()}])

    def training_chat(self, context):
        response = self.generate_training(context)
        return AiTrainingChatResponse(
            assistant_message="Ficha revisada.", draft_update=response.plan
        )

    def generate_adaptation(self, context):
        self.calls += 1
        self.contexts.append(context)
        response = adjust_response()
        operations = deepcopy(response.operations)
        operations[0]["item"]["exercise_name"] = self._name()
        return response.model_copy(update={"operations": operations})

    def assess_training(self, context):
        self.review_contexts.append(context)
        if self.outcome in {"outage", "malformed"}:
            raise AiProviderError(
                "configuration" if self.outcome == "outage" else "malformed_structured_output",
                retryable=self.outcome == "malformed",
            )
        valid = all(
            not item["exercise_name"].startswith("Movimento")
            for item in context["proposed_plan"]["items"]
        )
        return AiTrainingPlanAssessment(
            sessions=[
                {
                    "label": label,
                    "complete": valid,
                    "issues": [] if valid else ["ambiguous_exercise"],
                }
                for label in context["training_schedule"]["session_labels"]
            ]
        )


@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
@pytest.mark.parametrize("outcome", ["corrected", "invalid", "outage", "malformed"])
def test_all_generation_paths_correct_rejected_sheets_or_preserve_saved_content(
    session, flow, outcome
):
    owner = create_client(session, "owner", "owner@example.test")
    complete_onboarding(session, "owner")
    lifecycle = TrainingLifecycleService()
    base = current_plan(session, owner)
    base_content = lifecycle.content(session, base)
    draft = None
    if flow != "adaptation":
        draft = lifecycle.create_revision(
            session,
            plan_id=base.plan_id,
            version_number=base.version_number,
            data=TrainingPlanVersionInput.model_validate(proposal().plan),
            actor="ai",
            origin="ai",
        )
        before = lifecycle.content(session, draft)
        revision = draft.revision
        submitted = draft.submitted_for_review_at
    writer = ReviewingWriter(outcome)
    knowledge = FakeKnowledge()
    if flow == "generation":
        service = InitialTrainingGenerationService(provider=writer, knowledge_service=knowledge)

        def run():
            return service.generate_for_subject(session, "owner", replace_existing=True)

        invalid_error, unavailable_error = (
            InvalidTrainingGenerationError,
            TrainingGenerationUnavailableError,
        )
    elif flow == "chat":
        service = TrainingChatService(writer, knowledge_service=knowledge)

        def run():
            return service.submit_for_subject(
                session, "owner", message="Atualize o rascunho.", client_request_id=uuid4()
            )

        invalid_error, unavailable_error = (
            TrainingChatDraftUpdateError,
            TrainingChatUnavailableError,
        )
    else:
        request_id = uuid4()
        source_message(session, owner, request_id)
        service = TrainingAdaptationService(writer, knowledge_service=knowledge)

        def run():
            return service.generate(
                session,
                "owner",
                source_client_request_id=request_id,
                client_request_id=uuid4(),
                reason="Ajuste o exercício para a limitação relatada.",
            )

        invalid_error, unavailable_error = AdaptationStateError, AdaptationUnavailableError
    message_count = len(session.scalars(select(TrainingAiMessage)).all())
    if outcome == "corrected":
        result = run()
        if flow == "adaptation":
            content = service._apply(session, base, result)
            assert result.status == "proposed" and result.resulting_version_id is None
            # The untouched row is included in the reviewed resulting sheet.
            assert content.items[1] == base_content.items[1]
        else:
            content = lifecycle.content(session, draft)
            assert draft.revision == revision + 1
        assert content.items[0].exercise_name == "Agachamento com apoio"
    else:
        with pytest.raises(
            unavailable_error if outcome in {"outage", "malformed"} else invalid_error
        ):
            run()
        if draft:
            assert lifecycle.content(session, draft) == before
            assert draft.revision == revision and draft.submitted_for_review_at == submitted
        assert session.scalars(select(TrainingAdaptationProposal)).all() == []
        messages = session.scalars(select(TrainingAiMessage)).all()
        assert len(messages) == message_count + (1 if flow == "chat" else 0)
    assert base.status == "current" and lifecycle.content(session, base) == base_content
    assert writer.calls == (2 if outcome in {"corrected", "invalid"} else 1)
    assert len(writer.review_contexts) == (1 if outcome == "outage" else 2)
    for review in writer.review_contexts:
        assert review["knowledge"] == writer.contexts[0]["knowledge"]
        assert review.get("completed_onboarding", review.get("relevant_onboarding"))
    if writer.calls == 2:
        correction = writer.contexts[1]["selection_correction"]
        assert correction["completeness_issues"][0]["issues"] == ["ambiguous_exercise"]
        assert writer.contexts[1]["knowledge"] == writer.contexts[0]["knowledge"]


@pytest.mark.parametrize(
    "name",
    [
        "Peso corporal",
        "PESO CORPORAL! (Dia A)",
        "Halteres (Dia B)",
        "Barra (Dia C)",
        "Máquina",
        "!!!",
        "Peso corporal — Pressão de joelho (Dia A)",
        "Peso corporal — Flexão de braço (Dia A)",
        "Halteres: Remada (Dia B)",
        "Flexão de perna (Dia B)",
        "Pressão de joelho (Dia C)",
        "Flexão de perna com peso corporal (Dia A)",
        "Flexão de pernas com halteres (Dia B)",
        "Pressão de joelho leve (Dia C)",
        "Flexão das pernas (Dia A)",
    ],
)
def test_resource_only_names_are_rejected_independently_of_the_model(name):
    plan = TrainingPlanVersionInput.model_validate(
        proposal(items=[{**proposal().plan["items"][0], "exercise_name": name}]).plan
    )
    with pytest.raises(IncompleteTrainingPlanError) as error:
        validate_exercise_names(plan)
    assert error.value.issues[0]["issues"] == ["ambiguous_exercise"]


@pytest.mark.parametrize(
    "name", ["Agachamento com peso corporal", "Rosca com halteres", "Barra fixa"]
)
def test_identifiable_movements_may_describe_their_resource(name):
    validate_exercise_names(
        TrainingPlanVersionInput.model_validate(
            proposal(items=[{**proposal().plan["items"][0], "exercise_name": name}]).plan
        )
    )


def test_resource_only_generation_cannot_pass_a_permissive_reviewer(session):
    owner = create_client(session, "owner", "owner@example.test")
    complete_onboarding(session, "owner")
    writer = FakeProvider(
        proposal(
            items=[
                {**proposal().plan["items"][0], "exercise_name": f"Peso corporal (Dia {day})"}
                for day in "ABC"
            ]
        )
    )
    with pytest.raises(InvalidTrainingGenerationError):
        InitialTrainingGenerationService(
            provider=writer, knowledge_service=FakeKnowledge()
        ).generate_for_subject(session, "owner")
    assert writer.calls == 2
    assert TrainingLifecycleService().find_proposal(session, client_id=owner.id) is None


def test_review_covers_each_actual_day_without_an_explicit_full_body_schedule():
    plan = TrainingPlanVersionInput.model_validate(
        proposal(
            items=[
                {**proposal().plan["items"][0], "exercise_name": f"Rosca direta (Dia {day})"}
                for day in "ABC"
            ]
        ).plan
    )
    context = {"training_schedule": {"session_labels": []}, "training_focus": None}
    review = training_review_context(plan, context)
    assert review["training_schedule"] == {"session_labels": ["A", "B", "C"]}
    assert context["training_schedule"] == {"session_labels": []}


def test_an_assessment_that_omits_a_localized_day_cannot_save_the_sheet(session):
    owner = create_client(session, "owner", "owner@example.test")
    complete_onboarding(session, "owner")
    writer = FakeProvider(
        proposal(
            items=[
                {**proposal().plan["items"][0], "exercise_name": f"Rosca direta (Dia {day})"}
                for day in "AB"
            ]
        )
    )
    writer.focus = AiTrainingRequestFocus(scope="targeted", muscle_groups=["bíceps"])
    reviews = []

    def incomplete_review(context):
        reviews.append(context)
        return AiTrainingPlanAssessment(sessions=[{"label": "A", "complete": True, "issues": []}])

    writer.assess_training = incomplete_review
    with pytest.raises(InvalidTrainingGenerationError):
        InitialTrainingGenerationService(
            provider=writer, knowledge_service=FakeKnowledge()
        ).generate_for_subject(session, "owner", training_request="Sugira exercícios para bíceps.")
    assert writer.calls == len(reviews) == 2
    assert all(review["training_schedule"]["session_labels"] == ["A", "B"] for review in reviews)
    assert TrainingLifecycleService().find_proposal(session, client_id=owner.id) is None


def test_conversation_without_a_sheet_does_not_call_the_reviewer(session):
    owner = create_client(session, "owner", "owner@example.test")
    current_plan(session, owner)
    writer = ChatProvider(AiTrainingChatResponse(assistant_message="Seu treino está disponível."))
    TrainingChatService(writer, knowledge_service=FakeKnowledge()).submit_for_subject(
        session, "owner", message="Onde consulto meu treino?", client_request_id=uuid4()
    )
    assert writer.calls == 1
    assert not getattr(writer, "review_contexts", [])


def test_resource_normalization_preserves_movement_day_and_prescription_without_mutating_input():
    item = TrainingPlanVersionInput.model_validate(
        proposal(
            items=[
                {
                    **proposal().plan["items"][0],
                    "exercise_name": "Peso corporal — Flexão de braço (Dia B)",
                }
            ]
        ).plan
    ).items[0]
    original = item.model_dump()
    normalized = normalize_exercise_resource(item)
    assert normalized.exercise_name == "Flexão de braço (Dia B)"
    assert normalized.load_guidance == f"Peso corporal; {item.load_guidance}"
    assert normalized.model_dump(exclude={"exercise_name", "load_guidance"}) == item.model_dump(
        exclude={"exercise_name", "load_guidance"}
    )
    assert item.model_dump() == original
    assert normalize_exercise_resource(normalized) == normalized


@pytest.mark.parametrize("flow", ["generation", "chat", "adaptation"])
@pytest.mark.parametrize("ambiguous", [False, True])
def test_resource_prefixes_are_separated_but_ambiguous_movements_are_never_saved(
    session, flow, ambiguous
):
    owner = create_client(session, "owner", "owner@example.test")
    complete_onboarding(session, "owner")
    base = current_plan(session, owner)
    lifecycle = TrainingLifecycleService()
    original = lifecycle.content(session, base)
    writer = ReviewingWriter("prefix")
    writer._name = lambda: (
        "Peso corporal — Pressão de joelho" if ambiguous else "Peso corporal — Agachamento"
    )
    knowledge = FakeKnowledge()
    if flow == "generation":

        def run():
            draft = InitialTrainingGenerationService(
                provider=writer, knowledge_service=knowledge
            ).generate_for_subject(session, "owner")
            return lifecycle.content(session, draft)

        error = InvalidTrainingGenerationError
    elif flow == "chat":
        draft = lifecycle.create_revision(
            session,
            plan_id=base.plan_id,
            version_number=base.version_number,
            data=original,
            actor="ai",
            origin="ai",
        )

        def run():
            TrainingChatService(writer, knowledge_service=knowledge).submit_for_subject(
                session, "owner", message="Atualize o rascunho.", client_request_id=uuid4()
            )
            return lifecycle.content(session, draft)

        error = TrainingChatDraftUpdateError
    else:
        source_id = uuid4()
        source_message(session, owner, source_id)
        service = TrainingAdaptationService(writer, knowledge_service=knowledge)

        def run():
            result = service.generate(
                session,
                "owner",
                source_client_request_id=source_id,
                client_request_id=uuid4(),
                reason="Ajuste o exercício.",
            )
            return service._apply(session, base, result)

        error = AdaptationStateError
    if ambiguous:
        with pytest.raises(error):
            run()
        assert writer.calls == 2 and writer.review_contexts == []
    else:
        content = run()
        assert content.items[0].exercise_name == "Agachamento"
        assert content.items[0].load_guidance.count("Peso corporal") == 1
        assert writer.review_contexts[0]["proposed_plan"] == content.model_dump(mode="json")
        assert writer.calls == 1
    assert base.status == "current" and lifecycle.content(session, base) == original
