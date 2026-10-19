"""Minimal active-client workspace for professional training work."""

import base64
import json
import unicodedata
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.clients.models import Account, Client, Employee, PersonProfile
from app.modules.onboarding.models import Onboarding
from app.modules.training.models import TrainingPlanVersion
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import (
    ConcurrentTrainingUpdateError,
    TrainingLifecycleService,
    TrainingVersionNotFoundError,
)


def name_key(value):
    # PostgreSQL built-ins avoid an extra unaccent extension/dependency.
    accents = "áàâãäåéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÅÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
    plain = "aaaaaaeeeeiiiiooooouuuucnAAAAAAEEEEIIIIOOOOOUUUUCN"
    value = func.lower(func.translate(value, accents, plain))
    for whitespace in ("\t", "\n", "\r"):
        value = func.replace(value, whitespace, " ")
    for _ in range(9):
        value = func.replace(value, "  ", " ")
    return func.trim(value)


def normalize_search(value: str) -> str:
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))
        .lower()
        .split()
    )


def _query():
    draft, current = aliased(TrainingPlanVersion), aliased(TrainingPlanVersion)
    person, professional = aliased(PersonProfile), aliased(PersonProfile)
    name = func.coalesce(person.first_name + " " + person.surname, Client.name)
    key = name_key(name)
    statement = (
        select(
            Client.id,
            name.label("name"),
            key.label("sort_name"),
            Onboarding.status.label("onboarding"),
            case((draft.submitted_for_review_at.is_not(None), draft.id), else_=None).label(
                "draft_id"
            ),
            current.id.label("current_id"),
            func.coalesce(
                professional.first_name + " " + professional.surname, current.responsible_name
            ).label("responsible_name"),
        )
        .join(Account, Client.account_id == Account.id)
        .outerjoin(person, person.account_id == Client.account_id)
        .outerjoin(Onboarding, Onboarding.client_id == Client.id)
        .outerjoin(draft, and_(draft.client_id == Client.id, draft.status == "proposal"))
        .outerjoin(current, and_(current.client_id == Client.id, current.status == "current"))
        .outerjoin(Employee, Employee.id == current.responsible_employee_id)
        .outerjoin(professional, professional.account_id == Employee.account_id)
        .where(Client.active, Account.account_active)
    )
    return statement, key, draft, current


def projection(row):
    return {
        "id": str(row.id),
        "name": row.name,
        "onboarding_status": "completed" if row.onboarding == "completed" else "draft",
        "draft_id": str(row.draft_id) if row.draft_id else None,
        "current_id": str(row.current_id) if row.current_id else None,
        "responsible_instructor_name": row.responsible_name,
    }


def search_clients(
    session: Session,
    *,
    subject: str,
    search: str,
    onboarding: str,
    training: str,
    responsibility: str,
    responsible: UUID | None,
    cursor: str | None,
    limit: int,
):
    statement, key, draft, current = _query()
    if search.strip():
        statement = statement.where(key.contains(normalize_search(search), autoescape=True))
    if onboarding == "completed":
        statement = statement.where(Onboarding.status == "completed")
    elif onboarding == "incomplete":
        statement = statement.where(
            or_(Onboarding.status.is_(None), Onboarding.status != "completed")
        )
    if training == "none":
        statement = statement.where(draft.id.is_(None), current.id.is_(None))
    elif training == "pending":
        statement = statement.where(draft.submitted_for_review_at.is_not(None))
    elif training == "current":
        statement = statement.where(current.id.is_not(None))
    if responsibility == "none":
        statement = statement.where(current.responsible_employee_id.is_(None))
    elif responsibility == "me":
        statement = statement.where(
            current.responsible_employee_id
            == select(Employee.id)
            .join(Account)
            .where(Account.keycloak_subject == subject)
            .scalar_subquery()
        )
    elif responsibility == "specific":
        if responsible is None:
            raise ValueError("Select a responsible instructor")
        statement = statement.where(
            current.responsible_employee_id
            == select(TrainingPlanVersion.responsible_employee_id)
            .where(
                TrainingPlanVersion.id == responsible, TrainingPlanVersion.approved_at.is_not(None)
            )
            .scalar_subquery()
        )
    if cursor:
        try:
            name, identifier = json.loads(base64.urlsafe_b64decode(cursor))
            identifier = UUID(identifier)
            if not isinstance(name, str) or len(name) > 301:
                raise ValueError
        except (ValueError, TypeError) as error:
            raise ValueError("Invalid cursor") from error
        statement = statement.where(or_(key > name, and_(key == name, Client.id > identifier)))
    rows = session.execute(statement.order_by(key, Client.id).limit(limit + 1)).all()
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps([rows[limit - 1].sort_name, str(rows[limit - 1].id)]).encode()
        ).decode()
        if len(rows) > limit
        else None
    )
    return {"items": [projection(row) for row in rows[:limit]], "next_cursor": next_cursor}


def workspace(session: Session, client_id: UUID):
    statement, *_ = _query()
    row = session.execute(statement.where(Client.id == client_id)).first()
    if row is None:
        raise TrainingVersionNotFoundError
    return projection(row)


def create_first_draft(
    session: Session, client_id: UUID, actor: str, data: TrainingPlanVersionInput
):
    lifecycle = TrainingLifecycleService()
    lifecycle._lock_client(session, client_id)
    state = workspace(session, client_id)
    if state["current_id"] or lifecycle.find_proposal(session, client_id=client_id):
        raise ConcurrentTrainingUpdateError
    employee = session.scalar(
        select(Employee)
        .join(Account)
        .where(
            Account.keycloak_subject == actor,
            Account.account_active,
            Employee.active,
            Employee.specialization == "instructor",
        )
    )
    if employee is None:
        raise TrainingVersionNotFoundError
    return lifecycle.create_proposal(
        session,
        client_id=client_id,
        data=data,
        created_by=actor,
        origin="instructor",
        created_employee_id=employee.id,
    )
