from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_database_session
from app.modules.clients.instructor_service import create_first_draft
from app.modules.equipment.models import EquipmentModel
from app.modules.identity.authorization import require_roles
from app.modules.identity.router import get_authenticated_identity
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training.adaptation_service import (
    AdaptationNotFoundError,
    AdaptationStateError,
    AdaptationUnavailableError,
    CurrentTrainingPlanRequiredError,
    TrainingAdaptationService,
)
from app.modules.training.chat_service import (
    TrainingChatDraftUpdateError,
    TrainingChatNotFoundError,
    TrainingChatService,
    TrainingChatState,
    TrainingChatUnavailableError,
)
from app.modules.training.current_service import CurrentTrainingPlanService
from app.modules.training.generation_service import (
    CompletedOnboardingRequiredError,
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
    TrainingGenerationUnavailableError,
)
from app.modules.training.models import (
    TrainingAdaptationOperation,
    TrainingAdaptationProposal,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.presentation import adaptation_preview, proposal_preview
from app.modules.training.review_service import (
    pending_version,
    pending_versions,
    responsible_name,
    review_metadata,
)
from app.modules.training.schema import (
    AdaptationClientDecision,
    AdaptationGenerationInput,
    AppendToCurrentAction,
    ManualPlanCreate,
    ProposalUpdate,
    TrainingKnowledgeResponse,
    VersionAction,
)
from app.modules.training.service import (
    ActiveTrainingProposalExistsError,
    ConcurrentTrainingUpdateError,
    ImmutableTrainingVersionError,
    InvalidTrainingContentError,
    InvalidTrainingTransitionError,
    TrainingLifecycleService,
    TrainingVersionNotFoundError,
)

router = APIRouter(prefix="/training", tags=["training"])
service = TrainingLifecycleService()
generation_service = InitialTrainingGenerationService()
current_service = CurrentTrainingPlanService()
chat_service = TrainingChatService()
adaptation_service = TrainingAdaptationService()
Instructor = Annotated[
    AuthenticatedIdentity, Depends(require_roles(get_authenticated_identity, "instructor"))
]
DatabaseSession = Annotated[Session, Depends(get_database_session)]


class TrainingChatMessageRequest(BaseModel):
    message: str = Field(max_length=4000)
    client_request_id: UUID

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class TrainingChatMessageResponse(TrainingKnowledgeResponse):
    role: str
    content: str
    created_at: datetime
    client_request_id: UUID | None = None
    reply_to_client_request_id: UUID | None = None
    adaptation_suggested: bool = False
    adaptation_reason: str | None = None


class TrainingChatResponse(BaseModel):
    messages: list[TrainingChatMessageResponse]
    draft: dict[str, object] | None = None


Client = Annotated[
    AuthenticatedIdentity, Depends(require_roles(get_authenticated_identity, "client"))
]


def training_chat_response(
    state: TrainingChatState, session: Session, subject: str
) -> TrainingChatResponse:
    drafts = current_service.find_drafts_for_subject(session, subject)
    return TrainingChatResponse(
        draft=version_response(session, drafts[0]) if drafts else None,
        messages=[
            TrainingChatMessageResponse(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                client_request_id=message.client_request_id,
                reply_to_client_request_id=message.reply_to_client_request_id,
                adaptation_suggested=message.adaptation_suggested,
                adaptation_reason=message.adaptation_reason,
                citations=message.citations,
                knowledge_status=message.knowledge_status,
                knowledge_limitations=message.knowledge_limitations,
            )
            for message in state.messages
        ],
    )


def adaptation_response(
    session: Session, proposal: TrainingAdaptationProposal
) -> dict[str, object]:
    base = session.get(TrainingPlanVersion, proposal.base_version_id)
    preview = adaptation_preview(TrainingAdaptationService._apply(session, base, proposal))
    base_items = session.scalars(
        select(TrainingPlanItem)
        .where(TrainingPlanItem.version_id == proposal.base_version_id)
        .order_by(TrainingPlanItem.position)
    )
    operations = list(
        session.scalars(
            select(TrainingAdaptationOperation)
            .where(TrainingAdaptationOperation.proposal_id == proposal.id)
            .order_by(TrainingAdaptationOperation.position)
        )
    )
    equipment_model_names = {
        model.id: model.name
        for model in session.scalars(
            select(EquipmentModel).where(
                EquipmentModel.id.in_(
                    [
                        operation.equipment_model_id
                        for operation in operations
                        if operation.equipment_model_id
                    ]
                )
            )
        )
    }
    return {
        "id": str(proposal.id),
        "status": proposal.status,
        "base_version_id": str(proposal.base_version_id),
        "source_client_request_id": str(proposal.source_client_request_id),
        "reason": proposal.reason,
        "explanation": proposal.explanation,
        "preview": preview,
        "citations": proposal.citations,
        "knowledge_status": proposal.knowledge_status,
        "knowledge_limitations": proposal.knowledge_limitations,
        "client_reviewed_at": (
            proposal.client_reviewed_at.isoformat() if proposal.client_reviewed_at else None
        ),
        "instructor_reviewed_at": (
            proposal.instructor_reviewed_at.isoformat() if proposal.instructor_reviewed_at else None
        ),
        "resulting_version_id": str(proposal.resulting_version_id)
        if proposal.resulting_version_id
        else None,
        "base_items": [
            {
                "position": item.position,
                "equipment_requirement": item.equipment_requirement,
                "equipment_model_id": str(item.equipment_model_id)
                if item.equipment_model_id
                else None,
                "exercise_name": item.exercise_name,
                "sets": item.sets,
                "repetitions": item.repetitions,
                "load_guidance": item.load_guidance,
                "rest_seconds": item.rest_seconds,
            }
            for item in base_items
        ],
        "operations": [
            {
                "operation_type": item.operation_type,
                "target_position": item.target_position,
                "exercise_name": item.exercise_name,
                "sets": item.sets,
                "repetitions": item.repetitions,
                "load_guidance": item.load_guidance,
                "rest_seconds": item.rest_seconds,
                "equipment_requirement": item.equipment_requirement,
                "equipment_model_id": str(item.equipment_model_id)
                if item.equipment_model_id
                else None,
                "equipment_model_name": equipment_model_names.get(item.equipment_model_id),
                "is_existing_exercise": item.is_existing_exercise,
            }
            for item in operations
        ],
    }


def adaptation_error(error: Exception) -> HTTPException:
    if isinstance(error, AdaptationNotFoundError):
        return HTTPException(404, "Adaptation proposal not found")
    if isinstance(error, AdaptationUnavailableError):
        return HTTPException(503, "AI adaptation is temporarily unavailable")
    if isinstance(error, CurrentTrainingPlanRequiredError):
        return HTTPException(422, "A current training plan is required for an adaptation")
    return HTTPException(409, "Adaptation proposal cannot be changed in its current state")


def version_response(session: Session, version: TrainingPlanVersion) -> dict[str, object]:
    return {
        "id": str(version.id),
        "plan_id": str(version.plan_id),
        "version_number": version.version_number,
        "status": version.status,
        "name": version.name,
        "objective": version.objective,
        "origin": version.origin,
        "created_at": version.created_at.isoformat(),
        "responsible_instructor_name": responsible_name(session, version),
        "updated_at": version.updated_at.isoformat(),
        "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        "revision": version.revision,
        "submitted_for_review_at": (
            version.submitted_for_review_at.isoformat() if version.submitted_for_review_at else None
        ),
        "preview": proposal_preview(session, version) if version.status == "proposal" else None,
        "citations": version.citations,
        "knowledge_status": version.knowledge_status,
        "knowledge_limitations": version.knowledge_limitations,
        "items": [
            {
                "exercise_name": item.exercise_name,
                "sets": item.sets,
                "repetitions": item.repetitions,
                "load_guidance": item.load_guidance,
                "rest_seconds": item.rest_seconds,
                "position": item.position,
                "equipment_requirement": item.equipment_requirement,
                "equipment_model_id": str(item.equipment_model_id)
                if item.equipment_model_id
                else None,
            }
            for item in session.scalars(
                select(TrainingPlanItem)
                .where(TrainingPlanItem.version_id == version.id)
                .order_by(TrainingPlanItem.position)
            )
        ],
    }


def lifecycle_error(error: Exception) -> HTTPException:
    if isinstance(error, InvalidTrainingContentError):
        return HTTPException(422, "Training content or equipment reference is invalid")
    if isinstance(error, TrainingVersionNotFoundError):
        return HTTPException(404, "Training version not found")
    if isinstance(error, ConcurrentTrainingUpdateError):
        return HTTPException(409, "Training version changed; reload before saving")
    if isinstance(error, ActiveTrainingProposalExistsError):
        return HTTPException(409, "Client already has a training proposal")
    if isinstance(error, ImmutableTrainingVersionError):
        return HTTPException(409, "Approved, current, and historical versions are immutable")
    return HTTPException(409, "Invalid training version transition")


@router.get("/pending")
def get_pending_plans(
    session: DatabaseSession,
    instructor: Instructor,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    versions = pending_versions(session, offset, limit + 1)
    return {
        "items": [
            dict(version_response(session, version), **review_metadata(session, version))
            for version in versions[:limit]
        ],
        "next_offset": offset + limit if len(versions) > limit else None,
    }


@router.get("/pending/{version_id}")
def get_pending_plan(
    version_id: UUID, session: DatabaseSession, instructor: Instructor
) -> dict[str, object]:
    try:
        version = pending_version(session, version_id)
        return dict(version_response(session, version), **review_metadata(session, version))
    except TrainingVersionNotFoundError as error:
        raise lifecycle_error(error) from None


@router.post("/pending/{version_id}/append-to-current")
def append_pending_to_current(
    version_id: UUID,
    payload: AppendToCurrentAction,
    session: DatabaseSession,
    instructor: Instructor,
) -> dict[str, object]:
    try:
        version = service.append_to_current(
            session,
            version_id=version_id,
            expected_revision=payload.expected_revision,
            current_version_id=payload.current_version_id,
            expected_current_revision=payload.expected_current_revision,
            selected_positions=payload.selected_positions,
        )
        return dict(version_response(session, version), **review_metadata(session, version))
    except (
        TrainingVersionNotFoundError,
        ConcurrentTrainingUpdateError,
        InvalidTrainingTransitionError,
        InvalidTrainingContentError,
    ) as error:
        raise lifecycle_error(error) from None


@router.get("/current")
def get_current_plan(
    session: DatabaseSession,
    client_user: Annotated[
        AuthenticatedIdentity, Depends(require_roles(get_authenticated_identity, "client"))
    ],
) -> dict[str, object | None]:
    """Return the current version for only the caller's resolved client."""
    version = current_service.find_for_subject(session, client_user.subject)
    return {"plan": version_response(session, version) if version else None}


@router.get("/drafts")
def get_own_training_drafts(
    session: DatabaseSession,
    client_user: Annotated[
        AuthenticatedIdentity, Depends(require_roles(get_authenticated_identity, "client"))
    ],
) -> list[dict[str, object]]:
    """Show only the caller's unapproved plan versions, never another client's drafts."""
    return [
        version_response(session, version)
        for version in current_service.find_drafts_for_subject(session, client_user.subject)
    ]


@router.post("/drafts/{version_id}/submit")
def submit_training_draft(
    version_id: UUID, payload: VersionAction, session: DatabaseSession, client_user: Client
) -> dict[str, object]:
    """Request instructor review of only the caller's unchanged draft."""
    try:
        version = service.submit_for_review(
            session,
            subject=client_user.subject,
            version_id=version_id,
            expected_revision=payload.expected_revision,
        )
        return version_response(session, version)
    except (
        TrainingVersionNotFoundError,
        ConcurrentTrainingUpdateError,
        InvalidTrainingTransitionError,
    ) as error:
        raise lifecycle_error(error) from None


@router.get("/chat", response_model=TrainingChatResponse)
def get_training_chat(session: DatabaseSession, client_user: Client) -> TrainingChatResponse:
    """Return raw training chat only to the client who owns it."""
    try:
        return training_chat_response(
            chat_service.state_for_subject(session, client_user.subject),
            session,
            client_user.subject,
        )
    except TrainingChatNotFoundError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authenticated client not found"
        ) from None


@router.post("/chat/messages", response_model=TrainingChatResponse)
def send_training_chat_message(
    payload: TrainingChatMessageRequest,
    session: DatabaseSession,
    client_user: Client,
) -> TrainingChatResponse:
    """Persist a client message and its plain conversational AI response."""
    try:
        return training_chat_response(
            chat_service.submit_for_subject(
                session,
                client_user.subject,
                message=payload.message,
                client_request_id=payload.client_request_id,
            ),
            session,
            client_user.subject,
        )
    except TrainingChatNotFoundError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authenticated client not found"
        ) from None
    except TrainingChatUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI training chat is temporarily unavailable",
        ) from None
    except TrainingChatDraftUpdateError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "AI draft update could not be validated",
        ) from None
    except ConcurrentTrainingUpdateError as error:
        raise lifecycle_error(error) from None


@router.get("/adaptations")
def get_own_adaptations(session: DatabaseSession, client_user: Client) -> list[dict[str, object]]:
    try:
        return [
            adaptation_response(session, item)
            for item in adaptation_service.own_proposals(session, client_user.subject)
        ]
    except AdaptationNotFoundError as error:
        raise adaptation_error(error) from None


@router.post("/adaptations", status_code=status.HTTP_201_CREATED)
def generate_adaptation(
    payload: AdaptationGenerationInput, session: DatabaseSession, client_user: Client
) -> dict[str, object]:
    try:
        return adaptation_response(
            session,
            adaptation_service.generate(
                session,
                client_user.subject,
                source_client_request_id=payload.source_client_request_id,
                client_request_id=payload.client_request_id,
                reason=payload.reason,
            ),
        )
    except ActiveTrainingProposalExistsError as error:
        raise lifecycle_error(error) from None
    except (AdaptationNotFoundError, AdaptationStateError, AdaptationUnavailableError) as error:
        raise adaptation_error(error) from None


@router.post("/adaptations/{proposal_id}/client-decision")
def decide_adaptation_as_client(
    proposal_id: UUID,
    payload: AdaptationClientDecision,
    session: DatabaseSession,
    client_user: Client,
) -> dict[str, object]:
    try:
        return adaptation_response(
            session,
            adaptation_service.client_decide(
                session, client_user.subject, proposal_id, payload.accept
            ),
        )
    except ActiveTrainingProposalExistsError as error:
        raise lifecycle_error(error) from None
    except (AdaptationNotFoundError, AdaptationStateError) as error:
        raise adaptation_error(error) from None


@router.post("/initial-proposal", status_code=status.HTTP_201_CREATED)
def generate_initial_proposal(
    session: DatabaseSession,
    client_user: Annotated[
        AuthenticatedIdentity, Depends(require_roles(get_authenticated_identity, "client"))
    ],
) -> dict[str, object]:
    """Create only an AI proposal for the authenticated client's completed onboarding."""
    try:
        proposal = generation_service.generate_for_subject(session, client_user.subject)
        return version_response(session, proposal)
    except CompletedOnboardingRequiredError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Completed onboarding is required before generating a training proposal",
        ) from None
    except InvalidTrainingGenerationError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI training proposal could not be validated",
        ) from None
    except TrainingGenerationUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI training generation is temporarily unavailable",
        ) from None


@router.post("/plans", status_code=status.HTTP_201_CREATED)
def create_manual_proposal(
    payload: ManualPlanCreate, session: DatabaseSession, instructor: Instructor
) -> dict[str, object]:
    try:
        version = create_first_draft(session, UUID(payload.client_id), instructor.subject, payload)
        return version_response(session, version)
    except ValueError:
        raise HTTPException(422, "Invalid client identifier") from None
    except (
        InvalidTrainingContentError,
        ActiveTrainingProposalExistsError,
        TrainingVersionNotFoundError,
        ConcurrentTrainingUpdateError,
    ) as error:
        raise lifecycle_error(error) from None


@router.patch("/plans/{plan_id}/versions/{version_number}")
def revise_proposal(
    plan_id: UUID,
    version_number: int,
    payload: ProposalUpdate,
    session: DatabaseSession,
    instructor: Instructor,
) -> dict[str, object]:
    try:
        return version_response(
            session,
            service.revise(
                session,
                plan_id=plan_id,
                version_number=version_number,
                data=payload,
                actor=instructor.subject,
                expected_revision=payload.expected_revision,
            ),
        )
    except (
        InvalidTrainingContentError,
        TrainingVersionNotFoundError,
        ImmutableTrainingVersionError,
        ConcurrentTrainingUpdateError,
        InvalidTrainingTransitionError,
    ) as error:
        raise lifecycle_error(error) from None


@router.post("/plans/{plan_id}/versions/{version_number}/approve")
def approve_proposal(
    plan_id: UUID,
    version_number: int,
    payload: VersionAction,
    session: DatabaseSession,
    instructor: Instructor,
) -> dict[str, object]:
    try:
        return version_response(
            session,
            service.approve(
                session,
                plan_id=plan_id,
                version_number=version_number,
                actor=instructor.subject,
                expected_revision=payload.expected_revision,
            ),
        )
    except (
        InvalidTrainingContentError,
        TrainingVersionNotFoundError,
        ImmutableTrainingVersionError,
        ConcurrentTrainingUpdateError,
        InvalidTrainingTransitionError,
    ) as error:
        raise lifecycle_error(error) from None


@router.post(
    "/plans/{plan_id}/versions/{version_number}/revisions", status_code=status.HTTP_201_CREATED
)
def create_revision(
    plan_id: UUID,
    version_number: int,
    payload: ProposalUpdate,
    session: DatabaseSession,
    instructor: Instructor,
) -> dict[str, object]:
    try:
        return version_response(
            session,
            service.create_revision(
                session,
                plan_id=plan_id,
                version_number=version_number,
                data=payload,
                actor=instructor.subject,
                expected_revision=payload.expected_revision,
            ),
        )
    except (
        InvalidTrainingContentError,
        TrainingVersionNotFoundError,
        ImmutableTrainingVersionError,
        ConcurrentTrainingUpdateError,
        ActiveTrainingProposalExistsError,
        InvalidTrainingTransitionError,
    ) as error:
        raise lifecycle_error(error) from None
