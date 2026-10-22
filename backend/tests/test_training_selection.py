"""Regression coverage for competing prescriptions in generated sheets/draft edits."""

import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_training_generation import complete_onboarding, create_client, proposal
from test_training_generation import session as session
from test_training_rag import CHUNK_ID, FakeKnowledge
from training_fixtures import AcceptingTrainingReviewer

from app.integrations.ai import AiTrainingChatResponse
from app.modules.training.chat_service import TrainingChatDraftUpdateError, TrainingChatService
from app.modules.training.generation_service import (
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
)
from app.modules.training.models import TrainingAiMessage, TrainingPlanVersion
from app.modules.training.presentation import adaptation_preview
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.selection import (
    RedundantTrainingExerciseError,
    validate_exercise_selection,
)
from app.modules.training.service import TrainingLifecycleService


def exercise(name="Flexão do cotovelo", **changes):
    return {**proposal().plan["items"][0], "exercise_name": name, **changes}


def sheet(items):
    return TrainingPlanVersionInput.model_validate(proposal(items=items).plan)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"sets": 4},
        {"repetitions": "12 a 15"},
        {"load_guidance": "Carga leve"},
        {"equipment_requirement": "Halteres"},
        {"rest_seconds": 60},
        {"exercise_name": "  FLEXAO   DO COTOVELO!  "},
    ],
)
def test_same_exercise_is_redundant_despite_different_prescriptions(changes):
    with pytest.raises(RedundantTrainingExerciseError):
        validate_exercise_selection(sheet([exercise(), {**exercise(), **changes}]))


@pytest.mark.parametrize(
    "names,repetitions",
    [
        (["Flexão do cotovelo (Dia A)", "Flexão do cotovelo (Dia A)"], "12"),
        (["Flexão do cotovelo (Dia A)", "Flexão do cotovelo (Dia 1)"], "12"),
        (["Flexão do cotovelo", "Flexão do cotovelo (Dia B)"], "12"),
    ],
)
def test_missing_or_same_day_prescriptions_are_rejected(names, repetitions):
    with pytest.raises(RedundantTrainingExerciseError):
        validate_exercise_selection(
            sheet(
                [
                    exercise(names[0]),
                    exercise(names[1], repetitions=repetitions),
                ]
            )
        )


@pytest.mark.parametrize("repetitions", ["8", "12"])
def test_different_days_are_retained_and_visible_even_with_the_same_prescription(repetitions):
    plan = sheet(
        [
            exercise("Flexão do cotovelo (Dia A)"),
            exercise("Flexão do cotovelo (Dia B)", repetitions=repetitions),
        ]
    )
    validate_exercise_selection(plan)
    preview = adaptation_preview(plan)
    assert "Treino A —" in preview and "Treino B —" in preview
    assert preview.count("| 1 | Flexão do cotovelo |") == 2


def test_distinct_complementary_exercises_are_not_collapsed():
    validate_exercise_selection(sheet([exercise("Rosca direta"), exercise("Rosca martelo")]))


class SelectingWriter(AcceptingTrainingReviewer):
    def __init__(self, flow, outcome):
        self.flow = flow
        self.outcome = outcome
        self.contexts = []

    def respond(self, context):
        self.contexts.append(context)
        items = [exercise(), exercise(repetitions="12")]
        if len(self.contexts) > 1 and self.outcome != "duplicates":
            # The selected row is deliberately NOT the first candidate.
            items = [items[1]]
        citations = ["invented"] if self.outcome == "invalid_citation" else [CHUNK_ID]
        if self.flow == "generation":
            return proposal(items=items).model_copy(update={"citations": citations})
        return AiTrainingChatResponse(
            assistant_message="Selecionei a alternativa adequada ao pedido.",
            draft_update=proposal(items=items).plan,
            citations=citations,
        )

    generate_training = respond
    training_chat = respond


@pytest.mark.parametrize("flow", ["generation", "chat"])
@pytest.mark.parametrize("outcome", ["selected", "duplicates", "invalid_citation"])
def test_selection_is_retried_once_and_only_valid_final_content_is_saved(
    session, flow, outcome, caplog
):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    owner = create_client(session, "client", "client@example.test")
    complete_onboarding(session, "client")
    writer = SelectingWriter(flow, outcome)
    knowledge = FakeKnowledge()
    lifecycle = TrainingLifecycleService()
    draft = lifecycle.create_proposal(
        session,
        client_id=owner.id,
        data=sheet([exercise("Rosca direta")]),
        created_by="ai",
        origin="ai",
    )
    original = lifecycle.content(session, draft)
    revision = draft.revision
    if flow == "generation":
        service = InitialTrainingGenerationService(provider=writer, knowledge_service=knowledge)

        def run():
            return service.generate_for_subject(session, "client", replace_existing=True)

        error = InvalidTrainingGenerationError
    else:
        service = TrainingChatService(writer, knowledge_service=knowledge)

        def run():
            return service.submit_for_subject(
                session,
                "client",
                message="Atualize o rascunho para duas séries.",
                client_request_id=uuid4(),
            )

        error = TrainingChatDraftUpdateError
    if outcome == "selected":
        run()
        content = lifecycle.content(session, draft)
        assert len(content.items) == 1 and content.items[0].repetitions == "12"
        assert draft.revision == revision + 1 and draft.status == "proposal"
        assert draft.citations[0]["chunk_id"] == CHUNK_ID
    else:
        with pytest.raises(error):
            run()
        assert lifecycle.content(session, draft) == original and draft.revision == revision
        assert (
            session.scalars(
                select(TrainingAiMessage).where(TrainingAiMessage.role == "assistant")
            ).all()
            == []
        )
    assert session.scalars(select(TrainingPlanVersion)).all() == [draft]
    assert len(writer.contexts) == 2
    assert "selection_correction" not in writer.contexts[0]
    assert writer.contexts[1]["knowledge"] == writer.contexts[0]["knowledge"]
    assert len(knowledge.calls) == (2 if flow == "generation" else 1)
    if flow == "chat":
        event = next(
            json.loads(record.message)
            for record in caplog.records
            if record.name == "uvicorn.error.ai"
            and json.loads(record.message)["event"] == "ai_turn"
        )
        assert event["retry_count"] == 1
        assert event["reason"] == (
            "invalid_training_citations"
            if outcome == "invalid_citation"
            else "redundant_exercise_prescription"
        )
        assert event["outcome"] == ("draft_saved" if outcome == "selected" else "draft_blocked")
        assert "Atualize o rascunho" not in caplog.text
        assert "client@example.test" not in caplog.text and str(owner.id) not in caplog.text
