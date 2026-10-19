"""Local professional fixtures; no external identity service calls."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.clients.models import Account, Employee, PersonProfile


def submitted_draft(session, version):
    """Arrange a draft whose client confirmation predates the review under test."""
    version.submitted_for_review_at = datetime.now(UTC)
    session.commit()
    return version


def instructor(session, subject="instructor-1", name="Instrutor"):
    employee = session.scalar(
        select(Employee).join(Account).where(Account.keycloak_subject == subject)
    )
    if employee:
        return employee
    index = len(session.scalars(select(Employee)).all())
    account = Account(
        email=f"{subject}@example.test", keycloak_subject=subject, account_active=True
    )
    account.person_profile = PersonProfile(
        first_name=name,
        surname="Silva",
        cpf=f"{index:011d}",
        phone="11998765432",
        postal_code="01001000",
        street="Rua de teste",
        number="1",
        complement=None,
        neighborhood="Centro",
        city="São Paulo",
        state="SP",
    )
    employee = Employee(account=account, specialization="instructor", active=True)
    session.add(employee)
    session.commit()
    return employee
