"""Bounded professional plan projections and safe current-to-draft editing."""

import base64
import json
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.clients.models import Account, Client, Employee, PersonProfile
from app.modules.training.models import (
    TrainingAdaptationProposal,
    TrainingPlanVersion,
)
from app.modules.training.service import (
    ConcurrentTrainingUpdateError,
    TrainingLifecycleService,
    TrainingVersionNotFoundError,
)


class ExistingDraftConflict(Exception):
    def __init__(self, version: TrainingPlanVersion):
        self.draft = {"id": str(version.id), "name": version.name, "revision": version.revision}


def _marker(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 512:
            raise ValueError
        timestamp, identifier = json.loads(base64.urlsafe_b64decode(cursor))
        if not isinstance(timestamp, str) or not isinstance(identifier, str):
            raise ValueError
        value = datetime.fromisoformat(timestamp)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value, UUID(identifier)
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("Invalid cursor") from error


def _cursor(version: TrainingPlanVersion) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([version.approved_at.isoformat(), str(version.id)]).encode()
    ).decode()


def _query():
    client_person = aliased(PersonProfile)
    instructor_person = aliased(PersonProfile)
    return (
        select(
            TrainingPlanVersion,
            func.coalesce(client_person.first_name + " " + client_person.surname, Client.name),
            instructor_person.first_name + " " + instructor_person.surname,
        )
        .join(Client, Client.id == TrainingPlanVersion.client_id)
        .outerjoin(client_person, client_person.account_id == Client.account_id)
        .outerjoin(Employee, Employee.id == TrainingPlanVersion.responsible_employee_id)
        .outerjoin(instructor_person, instructor_person.account_id == Employee.account_id)
    ), client_person


def _projection(row) -> dict[str, object]:
    version, client_name, live_name = row
    return {
        "id": str(version.id),
        "name": version.name,
        "client_name": client_name,
        "status": version.status,
        "revision": version.revision,
        "approved_at": version.approved_at,
        "responsible_instructor_name": (live_name or version.responsible_name)
        if version.status == "current"
        else version.responsible_name,
    }


def current_collection(
    session: Session,
    *,
    subject: str,
    mine: bool,
    search: str,
    responsible: UUID | None,
    start: date | None,
    end: date | None,
    cursor: str | None,
    limit: int,
) -> dict[str, object]:
    if end == date.max or (start and end and start > end):
        raise ValueError("Invalid date range")
    statement, person = _query()
    statement = statement.where(TrainingPlanVersion.status == "current")
    if mine:
        statement = statement.where(
            TrainingPlanVersion.responsible_employee_id
            == select(Employee.id)
            .join(Account)
            .where(Account.keycloak_subject == subject)
            .scalar_subquery()
        )
    if search.strip():
        statement = statement.where(
            func.coalesce(person.first_name + " " + person.surname, Client.name).icontains(
                " ".join(search.split()), autoescape=True
            )
        )
    if responsible:
        reference = aliased(TrainingPlanVersion)
        statement = statement.where(
            TrainingPlanVersion.responsible_employee_id
            == select(reference.responsible_employee_id)
            .where(reference.id == responsible, reference.approved_at.is_not(None))
            .scalar_subquery()
        )
    zone = ZoneInfo("America/Sao_Paulo")
    if start:
        statement = statement.where(
            TrainingPlanVersion.approved_at
            >= datetime.combine(start, time.min, zone).astimezone(UTC)
        )
    if end:
        statement = statement.where(
            TrainingPlanVersion.approved_at
            < datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC)
        )
    marker = _marker(cursor)
    if marker:
        timestamp, identifier = marker
        statement = statement.where(
            or_(
                TrainingPlanVersion.approved_at < timestamp,
                and_(
                    TrainingPlanVersion.approved_at == timestamp,
                    TrainingPlanVersion.id < identifier,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(
            TrainingPlanVersion.approved_at.desc(), TrainingPlanVersion.id.desc()
        ).limit(limit + 1)
    ).all()
    return {
        "items": [_projection(row) for row in rows[:limit]],
        "next_cursor": _cursor(rows[limit - 1][0]) if len(rows) > limit else None,
    }


def responsible_options(session: Session, cursor: UUID | None, limit: int):
    # A retained approved-version reference selects responsibility without publishing Employee IDs.
    ranked = (
        select(
            TrainingPlanVersion.id.label("reference"),
            func.row_number()
            .over(
                partition_by=TrainingPlanVersion.responsible_employee_id,
                order_by=TrainingPlanVersion.id,
            )
            .label("rank"),
        )
        .where(
            TrainingPlanVersion.status == "current",
            TrainingPlanVersion.responsible_employee_id.is_not(None),
        )
        .subquery()
    )
    statement, _ = _query()
    statement = statement.join(ranked, ranked.c.reference == TrainingPlanVersion.id).where(
        ranked.c.rank == 1
    )
    if cursor:
        statement = statement.where(TrainingPlanVersion.id > cursor)
    rows = session.execute(statement.order_by(TrainingPlanVersion.id).limit(limit + 1)).all()
    return {
        "items": [
            {"reference": str(row[0].id), "name": row[2] or row[0].responsible_name}
            for row in rows[:limit]
        ],
        "next_cursor": str(rows[limit - 1][0].id) if len(rows) > limit else None,
    }


def approved_detail(session: Session, version_id: UUID) -> dict[str, object]:
    statement, _ = _query()
    row = session.execute(
        statement.where(
            TrainingPlanVersion.id == version_id,
            TrainingPlanVersion.status.in_(["current", "approved", "superseded"]),
            TrainingPlanVersion.approved_at.is_not(None),
        )
    ).first()
    if row is None:
        raise TrainingVersionNotFoundError
    return {
        **_projection(row),
        **TrainingLifecycleService.content(session, row[0]).model_dump(mode="json"),
    }


def approved_history(session: Session, version_id: UUID, cursor: str | None, limit: int):
    anchor = session.get(TrainingPlanVersion, version_id)
    if anchor is None or anchor.approved_at is None:
        raise TrainingVersionNotFoundError
    statement, _ = _query()
    statement = statement.where(
        TrainingPlanVersion.client_id == anchor.client_id,
        TrainingPlanVersion.approved_at.is_not(None),
        TrainingPlanVersion.status.in_(["current", "approved", "superseded"]),
    )
    marker = _marker(cursor)
    if marker:
        timestamp, identifier = marker
        statement = statement.where(
            or_(
                TrainingPlanVersion.approved_at < timestamp,
                and_(
                    TrainingPlanVersion.approved_at == timestamp,
                    TrainingPlanVersion.id < identifier,
                ),
            )
        )
    rows = session.execute(
        statement.order_by(
            TrainingPlanVersion.approved_at.desc(), TrainingPlanVersion.id.desc()
        ).limit(limit + 1)
    ).all()
    return {
        "items": [_projection(row) for row in rows[:limit]],
        "next_cursor": _cursor(rows[limit - 1][0]) if len(rows) > limit else None,
    }


def clone_current(
    session: Session,
    version_id: UUID,
    *,
    actor: str,
    expected_revision: int,
    discard_id: UUID | None,
    discard_revision: int | None,
) -> TrainingPlanVersion:
    lifecycle = TrainingLifecycleService()
    source = session.get(TrainingPlanVersion, version_id)
    if source is None:
        raise TrainingVersionNotFoundError
    source = lifecycle._version(session, source.plan_id, source.version_number, lock=True)
    if source.status != "current" or source.revision != expected_revision:
        raise ConcurrentTrainingUpdateError
    draft = session.scalar(
        select(TrainingPlanVersion)
        .where(
            TrainingPlanVersion.client_id == source.client_id,
            TrainingPlanVersion.status == "proposal",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if draft is not None and draft.submitted_for_review_at is None:
        raise ConcurrentTrainingUpdateError
    if draft is not None and discard_id is None:
        raise ExistingDraftConflict(draft)
    if discard_id is not None and (
        draft is None or draft.id != discard_id or draft.revision != discard_revision
    ):
        raise ConcurrentTrainingUpdateError
    try:
        if draft is not None:
            # Retain source records and their links; unapproved superseded drafts are never history.
            draft.status = "superseded"
            draft.revision += 1
            for adaptation in session.scalars(
                select(TrainingAdaptationProposal).where(
                    TrainingAdaptationProposal.resulting_version_id == draft.id,
                    TrainingAdaptationProposal.status == "pending_instructor_review",
                )
            ):
                adaptation.status = "superseded"
            session.flush()
        return lifecycle.create_revision(
            session,
            plan_id=source.plan_id,
            version_number=source.version_number,
            data=lifecycle.content(session, source),
            actor=actor,
            expected_revision=expected_revision,
        )
    except Exception:
        session.rollback()
        raise
