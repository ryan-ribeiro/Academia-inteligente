"""Local startup accounts use real persistence and a fake identity adapter transport."""

from copy import deepcopy
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from test_clients import AsgiClient

from app.database import Base, get_database_session
from app.main import create_app
from app.modules.clients.models import Account, Client, Employee, PersonProfile
from app.modules.clients.service import normalize_cpf
from app.modules.identity import demo_accounts, router
from app.modules.identity.demo_accounts import DEMO_ACCOUNTS, seed_demo_accounts
from app.modules.identity.keycloak_admin import (
    KeycloakAdminClient,
    KeycloakIdentityConflictError,
    KeycloakProvisioningError,
)
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.knowledge import startup


class FakeKeycloak(KeycloakAdminClient):
    def __init__(self):
        super().__init__()
        self.users = {}
        self.roles = {}
        self.fail_roles_once = False
        self.calls = []

    def _access_token(self):
        return "fake-service-token"

    def _request(self, method, path, token, payload=None, subject=None):
        self.calls.append((method, path))
        resource = path.split("/realms/academia/")[1]
        if resource.startswith("users?"):
            query = parse_qs(urlparse(path).query)["q"][0].split(":", 1)[1]
            return [
                deepcopy(user)
                for user in self.users.values()
                if query in user["attributes"]["academia_provisioning_id"]
            ]
        if method == "POST" and resource == "users":
            if any(user["email"] == payload["email"] for user in self.users.values()):
                raise KeycloakIdentityConflictError("Existing email")
            identifier = str(uuid4())
            self.users[identifier] = {**deepcopy(payload), "id": identifier}
            self.roles[identifier] = set()
            return f"http://identity.test/admin/realms/academia/users/{identifier}"
        if resource.startswith("roles/"):
            name = resource.split("/")[-1]
            return {"id": name, "name": name}
        if resource.endswith("/role-mappings/realm"):
            identifier = resource.split("/")[1]
            if self.fail_roles_once:
                self.fail_roles_once = False
                raise KeycloakProvisioningError("Unavailable")
            if method == "GET":
                return [{"id": name, "name": name} for name in self.roles[identifier]]
            names = {role["name"] for role in payload}
            if method == "POST":
                self.roles[identifier].update(names)
            elif method == "DELETE":
                self.roles[identifier].difference_update(names)
            return None
        if method == "GET" and resource.startswith("users/"):
            return deepcopy(self.users[resource.split("/")[1]])
        raise AssertionError((method, path))


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as current:
        yield current
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_seed_creates_exact_roles_linked_profiles_and_preserves_changes_on_restart(session):
    identity = FakeKeycloak()
    seed_demo_accounts(session, identity, "123")
    assert session.scalar(select(func.count()).select_from(Account)) == 5
    assert session.scalar(select(func.count()).select_from(Client)) == 1
    assert session.scalar(select(func.count()).select_from(Employee)) == 1
    assert session.scalar(select(func.count()).select_from(PersonProfile)) == 2
    for demo in DEMO_ACCOUNTS:
        account = session.get(Account, demo.account_id)
        assert account.account_active
        user = identity.users[account.keycloak_subject]
        assert user["email"] == demo.email
        assert user["username"] == demo.email
        assert user["enabled"]
        assert user["credentials"] == [{"type": "password", "value": "123", "temporary": False}]
        assert identity.roles[account.keycloak_subject] == demo.roles
        if demo.cpf:
            assert normalize_cpf(account.person_profile.cpf) == demo.cpf
    client = session.scalar(select(Client))
    client.name = "Nome alterado"
    client.active = False
    client.account.account_active = False
    user["credentials"][0]["value"] = "changed-by-user"
    session.commit()
    calls = len(identity.calls)
    seed_demo_accounts(session, identity, "another-initial-password")
    assert len(identity.calls) == calls
    assert len(identity.users) == 5
    assert user["credentials"][0]["value"] == "changed-by-user"
    assert client.name == "Nome alterado"
    assert not client.active
    assert not client.account.account_active


def test_interrupted_creation_resumes_without_duplicates_or_password_reset(session):
    identity = FakeKeycloak()
    identity.fail_roles_once = True
    with pytest.raises(KeycloakProvisioningError):
        seed_demo_accounts(session, identity, "123")
    assert len(identity.users) == 1
    account = session.get(Account, DEMO_ACCOUNTS[0].account_id)
    assert account.keycloak_subject is None
    subject = next(iter(identity.users))
    identity.users[subject]["credentials"][0]["value"] = "already-changed"
    seed_demo_accounts(session, identity, "123")
    assert len(identity.users) == 5
    assert account.keycloak_subject == subject
    assert identity.roles[subject] == {"admin"}
    assert identity.users[subject]["credentials"][0]["value"] == "already-changed"


def test_seed_refuses_existing_local_email(session):
    account = Account(email=DEMO_ACCOUNTS[0].email, keycloak_subject="unrelated")
    session.add(account)
    session.commit()
    identity = FakeKeycloak()
    with pytest.raises(KeycloakIdentityConflictError):
        seed_demo_accounts(session, identity, "123")
    assert identity.calls == []
    assert account.keycloak_subject == "unrelated"


def test_seed_refuses_existing_external_email(session):
    identity = FakeKeycloak()
    identity.users["unrelated"] = {
        "email": DEMO_ACCOUNTS[0].email,
        "attributes": {"academia_provisioning_id": ["another-owner"]},
    }
    before = deepcopy(identity.users)
    with pytest.raises(KeycloakIdentityConflictError):
        seed_demo_accounts(session, identity, "123")
    assert identity.users == before
    assert session.get(Account, DEMO_ACCOUNTS[0].account_id).keycloak_subject is None


def test_all_demo_roles_are_accepted_and_only_admin_has_administrative_access(session, monkeypatch):
    identity = FakeKeycloak()
    seed_demo_accounts(session, identity, "123")
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: session
    client = AsgiClient(app)
    for demo in DEMO_ACCOUNTS:
        account = session.get(Account, demo.account_id)
        authenticated = AuthenticatedIdentity(
            account.keycloak_subject, demo.email, tuple(demo.roles)
        )
        monkeypatch.setattr(router.identity_provider, "get_identity", lambda _: authenticated)
        response = client.get("/identity/me")
        assert response.status_code == 200
        assert set(response.json()["roles"]) == demo.roles
        expected = 200 if "admin" in demo.roles else 403
        assert client.get("/identity/admin").status_code == expected
        assert client.get("/clients").status_code == expected


def test_demo_initialization_disabled_by_default_and_explicitly(monkeypatch):
    monkeypatch.delenv("SEED_DEMO_ACCOUNTS", raising=False)
    monkeypatch.setattr(demo_accounts, "SessionLocal", None)
    demo_accounts.main()
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "false")
    demo_accounts.main()


def test_demo_initialization_retries_unavailable_identity_provider(session, monkeypatch):
    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.setenv("DEMO_ACCOUNT_PASSWORD", "123")
    monkeypatch.setattr(demo_accounts, "SessionLocal", lambda: session)
    identity = FakeKeycloak()
    identity.fail_roles_once = True
    monkeypatch.setattr(demo_accounts, "KeycloakAdminClient", lambda: identity)
    sleeps = []
    monkeypatch.setattr(demo_accounts.time, "sleep", sleeps.append)
    demo_accounts.main()
    assert sleeps == [2]
    assert len(identity.users) == 5


def test_empty_password_does_not_create_accounts(session):
    identity = FakeKeycloak()
    with pytest.raises(RuntimeError, match="DEMO_ACCOUNT_PASSWORD"):
        seed_demo_accounts(session, identity, "")
    assert not identity.calls
    assert session.scalar(select(func.count()).select_from(Account)) == 0


def test_startup_initializes_demo_accounts_after_migrations(monkeypatch):
    events = []
    monkeypatch.setattr(startup.subprocess, "run", lambda *a, **kw: events.append("migrate"))
    monkeypatch.setattr(startup, "seed_demo_accounts", lambda: events.append("demo"))
    monkeypatch.setattr(startup, "seed_knowledge", lambda: events.append("knowledge"))
    startup.main()
    assert events == ["migrate", "demo", "knowledge"]
