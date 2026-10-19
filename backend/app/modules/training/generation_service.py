"""Initial AI proposal generation over completed, client-owned onboarding."""

from typing import Callable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.ai import (
    AiProviderError,
    AiTrainingGenerationResponse,
    TrainingGenerationProvider,
    training_generation_provider_from_environment,
)
from app.integrations.ai_diagnostics import record_retry, record_turn
from app.modules.equipment.service import EquipmentService
from app.modules.knowledge.service import KnowledgeCitationError, KnowledgeContext, KnowledgeService
from app.modules.onboarding.draft_service import (
    ClientOnboardingScope,
    OnboardingDraftService,
)
from app.modules.onboarding.models import Onboarding
from app.modules.training.completeness import (
    IncompleteTrainingPlanError,
    requested_training_schedule,
    split_training_day,
)
from app.modules.training.focus import InvalidTrainingFocusError, analyze_training_focus
from app.modules.training.knowledge_query import retrieve_training_knowledge
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.selection import (
    RedundantTrainingExerciseError,
    request_selected_training,
)
from app.modules.training.service import (
    ActiveTrainingProposalExistsError,
    InvalidTrainingContentError,
    TrainingLifecycleService,
)


class CompletedOnboardingRequiredError(Exception):
    """Generation is allowed only after authoritative onboarding completion."""


class TrainingGenerationUnavailableError(Exception):
    """The external AI adapter could not produce a usable response."""


class InvalidTrainingGenerationError(Exception):
    """The provider response did not satisfy the approved plan schema."""


class InitialTrainingGenerationService:
    """Validates external output before creating the client's sole proposal version."""

    def __init__(
        self,
        *,
        provider: TrainingGenerationProvider | None = None,
        draft_service: OnboardingDraftService | None = None,
        lifecycle_service: TrainingLifecycleService | None = None,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._provider = provider or training_generation_provider_from_environment()
        self._drafts = draft_service or OnboardingDraftService()
        self._lifecycle = lifecycle_service or TrainingLifecycleService()
        self._knowledge = knowledge_service or KnowledgeService()

    def generate_for_subject(
        self,
        session: Session,
        subject: str,
        *,
        commit: bool = True,
        training_request: str = "",
        replace_existing: bool = False,
    ):
        scope = self._drafts.resolve_client_scope(session, subject)
        return self.generate_for_scope(
            session,
            scope,
            commit=commit,
            training_request=training_request,
            replace_existing=replace_existing,
        )

    def generate_for_scope(
        self,
        session: Session,
        scope: ClientOnboardingScope,
        *,
        commit: bool = True,
        training_request: str = "",
        replace_existing: bool = False,
    ):
        onboarding = session.scalar(
            select(Onboarding).where(Onboarding.client_id == scope.client_id)
        )
        if onboarding is None or not self._drafts.has_valid_completed_onboarding(
            session, scope.client_id
        ):
            raise CompletedOnboardingRequiredError

        # Every client has at most one proposal, regardless of its creator.
        # Reusing it prevents a provider call and preserves the single-draft rule.
        existing = self._lifecycle.find_proposal(session, client_id=scope.client_id)
        if existing is not None and not replace_existing:
            return existing
        expected_revision = existing.revision if existing else None

        try:
            focus = (
                analyze_training_focus(
                    lambda focus_context: self._retry(
                        lambda: self._provider.analyze_training_request(focus_context)
                    ),
                    training_request,
                )
                if training_request
                else None
            )
        except InvalidTrainingFocusError:
            raise InvalidTrainingGenerationError from None

        # `completion_data` is the shared form/conversation-independent source
        # of truth. The provider never receives another client's data or identity.
        context = {
            "training_request": training_request,
            "training_focus": focus,
            "training_schedule": requested_training_schedule(training_request, focus),
            "active_equipment_models": EquipmentService().training_context(session),
            "completed_onboarding": self._drafts.completion_data(onboarding).model_dump(),
            "proposal_rules": {
                "status": "proposal",
                "must_not_approve_or_activate": True,
                "instructor_review_required": True,
                "client_submission_required": True,
            },
        }
        onboarding_data = context["completed_onboarding"]
        evidence = retrieve_training_knowledge(
            self._knowledge,
            session,
            scope.client_id,
            training_request,
            onboarding_data,
            focus=focus,
        )
        context["knowledge"] = evidence.as_context()
        # Keep the actual requested scope beside the final writing instruction.
        context["training_focus"] = context.pop("training_focus")
        context["training_request"] = context.pop("training_request")
        try:
            response = self._generate_complete_routine(context, evidence)
            proposal = TrainingPlanVersionInput.model_validate(response.plan)
            knowledge = evidence.resolve_citations(
                response.citations,
                (
                    response.knowledge_status
                    if "knowledge_status" in response.model_fields_set
                    else None
                ),
            )
        except (
            ValidationError,
            KnowledgeCitationError,
            RedundantTrainingExerciseError,
            IncompleteTrainingPlanError,
        ) as error:
            record_turn(
                reason=(
                    "incomplete_training_plan"
                    if isinstance(error, IncompleteTrainingPlanError)
                    else "invalid_training_schema"
                    if isinstance(error, ValidationError)
                    else "invalid_training_citations"
                    if isinstance(error, KnowledgeCitationError)
                    else "redundant_exercise_prescription"
                )
            )
            raise InvalidTrainingGenerationError from error

        # Validation happens before lifecycle persistence, so malformed output
        # cannot create a partial plan or version.
        try:
            if existing is not None:
                revised = self._lifecycle.revise(
                    session,
                    plan_id=existing.plan_id,
                    version_number=existing.version_number,
                    data=proposal,
                    actor="ai",
                    expected_revision=expected_revision,
                    commit=False,
                    standalone=True,
                )
                revised.citations = list(knowledge.citations)
                revised.knowledge_status = knowledge.knowledge_status
                revised.knowledge_limitations = knowledge.knowledge_limitations
                if commit:
                    session.commit()
                else:
                    session.flush()
                return revised
            return self._lifecycle.create_proposal(
                session,
                client_id=scope.client_id,
                data=proposal,
                created_by="ai",
                origin="ai",
                knowledge=knowledge,
                commit=commit,
            )
        except ActiveTrainingProposalExistsError:
            # Another request created the sole draft while the provider was running.
            existing = self._lifecycle.find_proposal(session, client_id=scope.client_id)
            if existing is not None:
                return existing
            raise
        except InvalidTrainingContentError:
            record_turn(reason="invalid_training_equipment")
            raise InvalidTrainingGenerationError from None

    def _generate_complete_routine(self, context: dict, evidence: KnowledgeContext):
        labels = context["training_schedule"]["session_labels"]
        if len(labels) < 2:
            return self._generate_session(context)
        responses = []
        statuses = []
        citations = []
        for label in labels:
            session_context = {
                **context,
                "training_session": {"label": label, "all_session_labels": labels},
                "training_schedule": {"session_labels": [label]},
                "previous_sessions": [
                    {"label": previous_label, "plan": previous.plan}
                    for previous_label, previous in zip(labels, responses)
                ],
            }
            response = self._generate_session(session_context)
            knowledge = evidence.resolve_citations(
                response.citations,
                response.knowledge_status
                if "knowledge_status" in response.model_fields_set
                else None,
            )
            responses.append(response)
            statuses.append(knowledge.knowledge_status)
            citations.extend(citation["chunk_id"] for citation in knowledge.citations)
        # No session is persisted independently. The complete combined content
        # passes the ordinary plan/citation validation before the sole draft changes.
        priority = {"supported": 0, "insufficient_evidence": 1, "outdated": 2, "unavailable": 3}
        return AiTrainingGenerationResponse(
            plan={
                "name": f"Corpo inteiro — {len(labels)} dias",
                "objective": responses[0].plan["objective"],
                "items": [item for response in responses for item in response.plan["items"]],
            },
            citations=list(dict.fromkeys(citations)),
            knowledge_status=max(statuses, key=priority.get),
        )

    def _generate_session(self, context: dict):
        focus = context["training_focus"]

        def write(selected_context):
            response = self._retry(lambda: self._provider.generate_training(selected_context))
            label = selected_context.get("training_session", {}).get("label")
            items = response.plan.get("items")
            if label and isinstance(items, list):
                # The server requested exactly this session. Assign its label
                # without altering any prescription or overwriting a conflicting
                # provider-assigned day, which the ordinary validator rejects.
                items = [
                    {**item, "exercise_name": f"{item['exercise_name']} (Dia {label})"}
                    if isinstance(item, dict)
                    and isinstance(item.get("exercise_name"), str)
                    and not split_training_day(item["exercise_name"])[0]
                    else item
                    for item in items
                ]
                response = response.model_copy(update={"plan": {**response.plan, "items": items}})
            return response

        return request_selected_training(
            write,
            context,
            plan_field="plan",
            assess=(
                lambda review_context: self._retry(
                    lambda: self._provider.assess_training(review_context)
                )
            )
            if focus and focus["scope"] == "full_body"
            else None,
        )

    @staticmethod
    def _retry(operation: Callable[[], object]):
        for attempt in range(2):
            try:
                return operation()
            except AiProviderError as error:
                record_retry(error.category, will_retry=not attempt and error.retryable)
                if attempt or not error.retryable:
                    raise TrainingGenerationUnavailableError from None
        raise TrainingGenerationUnavailableError
