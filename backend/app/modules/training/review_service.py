"""Minimized instructor review queries; the lifecycle owns all writes."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clients.models import Client, Employee
from app.modules.training.models import TrainingAdaptationProposal, TrainingPlanVersion
from app.modules.training.service import TrainingLifecycleService, TrainingVersionNotFoundError


def responsible_name(session: Session, version: TrainingPlanVersion) -> str | None:
    if version.status == "current" and version.responsible_employee_id:
        employee = session.get(Employee, version.responsible_employee_id)
        if employee and employee.account.person_profile:
            return employee.account.person_profile.full_name
    return version.responsible_name


def pending_versions(session: Session, offset: int, limit: int) -> list[TrainingPlanVersion]:
    return list(
        session.scalars(
            select(TrainingPlanVersion)
            .where(
                TrainingPlanVersion.status == "proposal",
                TrainingPlanVersion.submitted_for_review_at.is_not(None),
            )
            .order_by(TrainingPlanVersion.created_at, TrainingPlanVersion.id)
            .offset(offset)
            .limit(limit)
        )
    )


def pending_version(session: Session, version_id: UUID) -> TrainingPlanVersion:
    version = session.get(TrainingPlanVersion, version_id)
    if version is None or version.status != "proposal" or version.submitted_for_review_at is None:
        raise TrainingVersionNotFoundError
    return version


def review_metadata(session: Session, version: TrainingPlanVersion) -> dict[str, object]:
    client = session.get(Client, version.client_id)
    profile = client.account.person_profile if client else None
    current = session.scalar(
        select(TrainingPlanVersion).where(
            TrainingPlanVersion.client_id == version.client_id,
            TrainingPlanVersion.status == "current",
        )
    )
    adaptation = session.scalar(
        select(TrainingAdaptationProposal.id).where(
            TrainingAdaptationProposal.resulting_version_id == version.id,
        )
    )
    return {
        "id": str(version.id),
        "client_name": profile.full_name if profile else client.name if client else "",
        "source": "adaptation" if adaptation else version.origin,
        "append_target": {
            "id": str(current.id),
            "revision": current.revision,
            **TrainingLifecycleService.content(session, current).model_dump(mode="json"),
        }
        if current and current.plan_id != version.plan_id and not adaptation
        else None,
        "current_responsible_instructor_name": responsible_name(session, current)
        if current
        else None,
    }
