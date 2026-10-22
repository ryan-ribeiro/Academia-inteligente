"""Opt-in local demo identities, independent of normal administrative registration."""

import os
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.clients.models import Account, Client, Employee, PersonProfile
from app.modules.identity.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakIdentityConflictError,
    KeycloakProvisioningError,
)


@dataclass(frozen=True)
class DemoAccount:
    email: str
    name: str
    roles: frozenset[str]
    cpf: str | None = None

    @property
    def account_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"academia:local-demo:{self.email}")


DEMO_ACCOUNTS = (
    DemoAccount("admin@academia.test", "Administrador", frozenset({"admin"})),
    DemoAccount("cliente@academia.test", "Cliente", frozenset({"client"}), "90000000175"),
    DemoAccount("funcionario@academia.test", "Funcionário", frozenset({"employee"})),
    DemoAccount("atendente@academia.test", "Atendente", frozenset({"employee", "attendant"})),
    DemoAccount(
        "instrutor@academia.test", "Instrutor", frozenset({"employee", "instructor"}), "90000000256"
    ),
)


class DemoIdentityProvisioner(Protocol):
    def ensure_demo_identity(
        self, email: str, first_name: str, reconciliation_id: UUID, roles: set[str], password: str
    ) -> str: ...


def seed_demo_accounts(
    session: Session, provisioner: DemoIdentityProvisioner, password: str
) -> None:
    if not password:
        raise RuntimeError("DEMO_ACCOUNT_PASSWORD must be configured for demo initialization")
    for demo in DEMO_ACCOUNTS:
        account = session.get(Account, demo.account_id)
        if account is None:
            if session.scalar(select(Account.id).where(Account.email == demo.email)) is not None:
                raise KeycloakIdentityConflictError("Demo email belongs to an existing account")
            account = Account(id=demo.account_id, email=demo.email, account_active=True)
            if demo.cpf:
                account.person_profile = PersonProfile(
                    first_name=demo.name,
                    surname="Demonstração",
                    cpf=demo.cpf,
                    phone="11999990000",
                    postal_code="01001000",
                    street="Praça da Sé",
                    number="1",
                    neighborhood="Sé",
                    city="São Paulo",
                    state="SP",
                )
                if "client" in demo.roles:
                    account.client = Client(name=f"{demo.name} Demonstração", active=True)
                else:
                    account.employee = Employee(specialization="instructor", active=True)
            session.add(account)
            # Persist the ownership marker before I/O so interrupted creation is resumable.
            session.commit()
        if account.keycloak_subject:
            # Completed seeds must preserve subsequent edits and deactivation.
            continue
        account.keycloak_subject = provisioner.ensure_demo_identity(
            account.email, demo.name, account.id, set(demo.roles), password
        )
        session.commit()


def main() -> None:
    if os.environ.get("SEED_DEMO_ACCOUNTS", "false").lower() != "true":
        return
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL must be configured")
    password = os.environ.get("DEMO_ACCOUNT_PASSWORD", "")
    for attempt in range(30):
        try:
            with SessionLocal() as session:
                seed_demo_accounts(session, KeycloakAdminClient(), password)
            return
        except KeycloakIdentityConflictError:
            raise
        except KeycloakProvisioningError:
            if attempt == 29:
                raise
            # Keycloak can still be importing its realm when Compose starts initialization.
            time.sleep(2)


if __name__ == "__main__":
    main()
