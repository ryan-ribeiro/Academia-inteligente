"""Client-confirmed, instructor-approved adaptation proposals."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.ai import (
    AiProviderError,
    TrainingAdaptationProvider,
    training_adaptation_provider_from_environment,
)
from app.modules.clients.models import Account, Client
from app.modules.equipment.service import EquipmentService
from app.modules.knowledge.service import KnowledgeCitationError, KnowledgeService
from app.modules.onboarding.models import Onboarding
from app.modules.training.knowledge_query import retrieve_training_knowledge
from app.modules.training.models import (
    TrainingAdaptationOperation,
    TrainingAdaptationProposal,
    TrainingAiConversation,
    TrainingAiMessage,
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.schema import (
    AdaptationOperationInput,
    TrainingPlanItemInput,
    TrainingPlanVersionInput,
)
from app.modules.training.service import (
    ActiveTrainingProposalExistsError,
    InvalidTrainingContentError,
    TrainingLifecycleService,
)


class AdaptationError(Exception):
    pass


class AdaptationNotFoundError(AdaptationError):
    pass


class AdaptationUnavailableError(AdaptationError):
    pass


class AdaptationStateError(AdaptationError):
    pass


class CurrentTrainingPlanRequiredError(AdaptationStateError):
    pass


class InvalidEquipmentReferenceError(AdaptationStateError):
    pass


class TrainingAdaptationService:
    """Keeps proposed changes separate from plans until instructor approval."""

    def __init__(
        self,
        provider: TrainingAdaptationProvider | None = None,
        *,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._provider = provider or training_adaptation_provider_from_environment()
        self._equipment = EquipmentService()
        self._knowledge = knowledge_service or KnowledgeService()

    def generate(
        self,
        session: Session,
        subject: str,
        *,
        source_client_request_id: UUID,
        client_request_id: UUID,
        reason: str,
    ) -> TrainingAdaptationProposal:
        client_id = self._client_id(session, subject)
        base = self._current(session, client_id)
        existing = session.scalar(
            select(TrainingAdaptationProposal).where(
                TrainingAdaptationProposal.client_id == client_id,
                TrainingAdaptationProposal.base_version_id == base.id,
                TrainingAdaptationProposal.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            return existing

        if TrainingLifecycleService().find_proposal(session, client_id=client_id):
            raise ActiveTrainingProposalExistsError

        source = self._source_message(session, client_id, source_client_request_id)
        context = self._context(session, client_id, base, source, reason.strip())
        evidence = retrieve_training_knowledge(
            self._knowledge,
            session,
            client_id,
            source.content,
            context["relevant_onboarding"],
        )
        context["knowledge"] = evidence.as_context()
        response = self._retry(lambda: self._provider.generate_adaptation(context))
        try:
            operations = [
                AdaptationOperationInput.model_validate(value) for value in response.operations
            ]
            knowledge = evidence.resolve_citations(
                response.citations,
                (
                    response.knowledge_status
                    if "knowledge_status" in response.model_fields_set
                    else None
                ),
            )
        except (ValidationError, KnowledgeCitationError) as error:
            raise AdaptationStateError from error
        # Match the lifecycle lock order after the external call, before equipment
        # locks/persistence. This avoids a model/client lock inversion at approval.
        TrainingLifecycleService._lock_client(session, client_id)
        session.refresh(base)
        if not self._is_current(session, base):
            raise AdaptationStateError
        self._validate_operations(session, base, operations)

        proposal = TrainingAdaptationProposal(
            client_id=client_id,
            base_version_id=base.id,
            source_client_request_id=source_client_request_id,
            client_request_id=client_request_id,
            reason=reason.strip(),
            explanation=response.explanation.strip(),
            status="proposed",
            citations=knowledge.citations,
            knowledge_status=knowledge.knowledge_status,
            knowledge_limitations=knowledge.knowledge_limitations,
        )
        session.add(proposal)
        session.flush()
        self._replace_operations(session, proposal, operations)
        session.flush()
        try:
            # The client must be able to preview the exact complete plan that
            # acceptance will submit, before any professional-review write.
            self._apply(session, base, proposal)
        except ValidationError:
            session.rollback()
            raise AdaptationStateError from None
        session.commit()
        session.refresh(proposal)
        return proposal

    def client_decide(
        self, session: Session, subject: str, proposal_id: UUID, accept: bool
    ) -> TrainingAdaptationProposal:
        client_id = self._client_id(session, subject)
        lifecycle = TrainingLifecycleService()
        lifecycle._lock_client(session, client_id)
        proposal = session.scalar(
            select(TrainingAdaptationProposal)
            .where(
                TrainingAdaptationProposal.id == proposal_id,
                TrainingAdaptationProposal.client_id == client_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if proposal is None:
            raise AdaptationNotFoundError
        if (
            accept
            and proposal.status == "pending_instructor_review"
            and proposal.resulting_version_id
        ):
            return proposal
        if proposal.status != "proposed":
            raise AdaptationStateError
        if accept:
            base = session.get(TrainingPlanVersion, proposal.base_version_id)
            if base is None or not self._is_current(session, base):
                proposal.status = "superseded"
                session.commit()
                raise AdaptationStateError
            if lifecycle.find_proposal(session, client_id=client_id):
                raise ActiveTrainingProposalExistsError
            try:
                data = self._apply(session, base, proposal)
                draft = lifecycle.create_revision(
                    session,
                    plan_id=base.plan_id,
                    version_number=base.version_number,
                    data=data,
                    actor="ai",
                    origin="ai",
                    commit=False,
                )
                proposal.resulting_version_id = draft.id
                draft.submitted_for_review_at = datetime.now(UTC)
                draft.citations = list(proposal.citations)
                draft.knowledge_status = proposal.knowledge_status
                draft.knowledge_limitations = proposal.knowledge_limitations
            except (ValidationError, InvalidTrainingContentError):
                session.rollback()
                raise AdaptationStateError from None
            except Exception:
                session.rollback()
                raise
        proposal.status = "pending_instructor_review" if accept else "client_rejected"
        proposal.client_reviewed_at = datetime.now(UTC)
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise
        session.refresh(proposal)
        return proposal

    def own_proposals(self, session: Session, subject: str) -> list[TrainingAdaptationProposal]:
        client_id = self._client_id(session, subject)
        return list(
            session.scalars(
                select(TrainingAdaptationProposal)
                .where(TrainingAdaptationProposal.client_id == client_id)
                .order_by(TrainingAdaptationProposal.created_at.desc())
            )
        )

    @staticmethod
    def _client_id(session: Session, subject: str) -> UUID:
        client_id = session.scalar(
            select(Client.id)
            .join(Account, Client.account_id == Account.id)
            .where(
                Account.keycloak_subject == subject, Account.account_active, Client.active.is_(True)
            )
        )
        if client_id is None:
            raise AdaptationNotFoundError
        return client_id

    @staticmethod
    def _current(session: Session, client_id: UUID) -> TrainingPlanVersion:
        version = session.scalar(
            select(TrainingPlanVersion)
            .join(TrainingPlan, TrainingPlanVersion.plan_id == TrainingPlan.id)
            .where(
                TrainingPlan.client_id == client_id,
                TrainingPlan.is_current,
                TrainingPlanVersion.status == "current",
            )
        )
        if version is None:
            raise CurrentTrainingPlanRequiredError
        return version

    def _owned(
        self, session: Session, subject: str, proposal_id: UUID
    ) -> TrainingAdaptationProposal:
        proposal = self._proposal(session, proposal_id)
        if proposal.client_id != self._client_id(session, subject):
            raise AdaptationNotFoundError
        return proposal

    @staticmethod
    def _proposal(session: Session, proposal_id: UUID) -> TrainingAdaptationProposal:
        proposal = session.get(TrainingAdaptationProposal, proposal_id)
        if proposal is None:
            raise AdaptationNotFoundError
        return proposal

    @staticmethod
    def _source_message(session: Session, client_id: UUID, request_id: UUID) -> TrainingAiMessage:
        message = session.scalar(
            select(TrainingAiMessage)
            .join(
                TrainingAiConversation,
                TrainingAiMessage.conversation_id == TrainingAiConversation.id,
            )
            .where(
                TrainingAiConversation.client_id == client_id,
                TrainingAiMessage.role == "user",
                TrainingAiMessage.client_request_id == request_id,
            )
        )
        if message is None:
            raise AdaptationNotFoundError
        return message

    @staticmethod
    def _is_current(session: Session, version: TrainingPlanVersion) -> bool:
        return version.status == "current" and bool(
            session.scalar(
                select(TrainingPlan.is_current).where(TrainingPlan.id == version.plan_id)
            )
        )

    def _context(
        self,
        session: Session,
        client_id: UUID,
        base: TrainingPlanVersion,
        source: TrainingAiMessage,
        reason: str,
    ) -> dict[str, object]:
        chat = session.scalar(
            select(TrainingAiConversation).where(TrainingAiConversation.client_id == client_id)
        )
        recent: list[TrainingAiMessage] = []
        if chat is not None:
            recent = list(
                session.scalars(
                    select(TrainingAiMessage)
                    .where(TrainingAiMessage.conversation_id == chat.id)
                    .order_by(TrainingAiMessage.sequence.desc())
                    .limit(6)
                )
            )
        onboarding = session.scalar(
            select(Onboarding).where(
                Onboarding.client_id == client_id, Onboarding.status == "completed"
            )
        )
        health: dict[str, object | None] = {}
        if onboarding is not None:
            health = {
                "training_goal": onboarding.training_goal,
                "training_experience": onboarding.training_experience,
                "limitations_or_complaints": onboarding.limitations_or_complaints,
                "medications": onboarding.medications,
                "health_conditions": onboarding.health_conditions,
            }
        items = session.scalars(
            select(TrainingPlanItem)
            .where(TrainingPlanItem.version_id == base.id)
            .order_by(TrainingPlanItem.position)
        )
        return {
            "reason": reason,
            "source_client_message": source.content,
            "base_plan": {
                "name": base.name,
                "objective": base.objective,
                "items": [
                    {
                        "position": item.position,
                        "exercise_name": item.exercise_name,
                        "sets": item.sets,
                        "repetitions": item.repetitions,
                        "load_guidance": item.load_guidance,
                        "rest_seconds": item.rest_seconds,
                        "equipment_requirement": item.equipment_requirement,
                        "equipment_model_id": str(item.equipment_model_id)
                        if item.equipment_model_id
                        else None,
                    }
                    for item in items
                ],
            },
            "recent_messages": [
                {"role": item.role, "content": item.content} for item in reversed(recent)
            ],
            "conversation_summary": chat.summary if chat else None,
            "relevant_onboarding": {
                key: value for key, value in health.items() if value is not None
            },
            "active_equipment_models": self._equipment.training_context(session),
        }

    def _validate_operations(
        self,
        session: Session,
        base: TrainingPlanVersion,
        operations: list[AdaptationOperationInput],
    ) -> None:
        positions = set(
            session.scalars(
                select(TrainingPlanItem.position).where(TrainingPlanItem.version_id == base.id)
            )
        )
        for operation in operations:
            if operation.operation_type == "add":
                if operation.item is None:
                    raise AdaptationStateError
            elif operation.target_position not in positions:
                raise AdaptationStateError
            elif operation.operation_type in {"replace", "adjust"} and operation.item is None:
                raise AdaptationStateError
        candidates = [
            TrainingPlanItemInput.model_validate(
                operation.item.model_dump(exclude={"is_existing_exercise"})
            )
            for operation in operations
            if operation.item is not None
        ]
        if candidates:
            try:
                TrainingLifecycleService.validate_equipment(
                    session,
                    TrainingPlanVersionInput(
                        name=base.name,
                        objective=base.objective,
                        items=candidates,
                    ),
                )
            except InvalidTrainingContentError:
                raise InvalidEquipmentReferenceError from None

    @staticmethod
    def _replace_operations(
        session: Session,
        proposal: TrainingAdaptationProposal,
        operations: list[AdaptationOperationInput],
    ) -> None:
        current = session.scalars(
            select(TrainingAdaptationOperation).where(
                TrainingAdaptationOperation.proposal_id == proposal.id
            )
        )
        for operation in current:
            session.delete(operation)
        session.flush()
        for position, operation in enumerate(operations, 1):
            item = operation.item
            session.add(
                TrainingAdaptationOperation(
                    proposal_id=proposal.id,
                    position=position,
                    operation_type=operation.operation_type,
                    target_position=operation.target_position,
                    exercise_name=item.exercise_name if item else None,
                    sets=item.sets if item else None,
                    repetitions=item.repetitions if item else None,
                    load_guidance=item.load_guidance if item else None,
                    rest_seconds=item.rest_seconds if item else None,
                    equipment_requirement=item.equipment_requirement if item else None,
                    equipment_model_id=item.equipment_model_id if item else None,
                    is_existing_exercise=item.is_existing_exercise if item else None,
                )
            )

    @staticmethod
    def _apply(
        session: Session, base: TrainingPlanVersion, proposal: TrainingAdaptationProposal
    ) -> TrainingPlanVersionInput:
        items = {
            item.position: TrainingPlanItemInput(
                exercise_name=item.exercise_name,
                sets=item.sets,
                repetitions=item.repetitions,
                load_guidance=item.load_guidance,
                rest_seconds=item.rest_seconds,
                equipment_requirement=item.equipment_requirement,
                equipment_model_id=item.equipment_model_id,
            )
            for item in session.scalars(
                select(TrainingPlanItem).where(TrainingPlanItem.version_id == base.id)
            )
        }
        operations = session.scalars(
            select(TrainingAdaptationOperation)
            .where(TrainingAdaptationOperation.proposal_id == proposal.id)
            .order_by(TrainingAdaptationOperation.position)
        )
        for operation in operations:
            if operation.operation_type == "remove":
                items.pop(operation.target_position, None)
                continue
            item = TrainingPlanItemInput(
                exercise_name=operation.exercise_name or "",
                sets=operation.sets or 0,
                repetitions=operation.repetitions or "",
                load_guidance=operation.load_guidance or "",
                rest_seconds=(operation.rest_seconds if operation.rest_seconds is not None else -1),
                equipment_requirement=operation.equipment_requirement,
                equipment_model_id=operation.equipment_model_id,
            )
            if operation.operation_type == "add":
                items[max(items, default=0) + 1] = item
            else:
                items[operation.target_position or 0] = item
        return TrainingPlanVersionInput(
            name=base.name,
            objective=base.objective,
            items=[items[position] for position in sorted(items)],
        )

    @staticmethod
    def _retry(operation):
        for attempt in range(2):
            try:
                return operation()
            except AiProviderError as error:
                if attempt or not error.retryable:
                    raise AdaptationUnavailableError from None
        raise AdaptationUnavailableError
