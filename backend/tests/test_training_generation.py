import asyncio
import json
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_database_session
from app.integrations.ai import (
    AiProviderError,
    AiTrainingGenerationResponse,
    AiTrainingPlanAssessment,
    AiTrainingRequestFocus,
)
from app.main import create_app
from app.modules.clients.models import Account, Client
from app.modules.identity import router as identity_router
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.onboarding.draft_service import OnboardingDraftService
from app.modules.onboarding.schema import OnboardingDraftUpdate
from app.modules.training import router as training_router
from app.modules.training.generation_service import (
    CompletedOnboardingRequiredError,
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
    TrainingGenerationUnavailableError,
)
from app.modules.training.models import TrainingPlan, TrainingPlanVersion
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.service import TrainingLifecycleService


class FakeProvider:
    focus = AiTrainingRequestFocus(scope="unspecified", muscle_groups=[], goal=None)

    def analyze_training_request(self, context):
        return self.focus

    def __init__(self, result: AiTrainingGenerationResponse | Exception) -> None:
        self.result = result
        self.contexts: list[dict[str, object]] = []
        self.calls = 0

    def generate_training(self, context: dict[str, object]) -> AiTrainingGenerationResponse:
        self.calls += 1
        self.contexts.append(context)
        if isinstance(self.result, Exception):
            raise self.result
        if "training_session" in context:
            label = context["training_session"]["label"]
            return self.result.model_copy(
                update={
                    "plan": {
                        **self.result.plan,
                        "items": [
                            item
                            for item in self.result.plan["items"]
                            if item["exercise_name"].endswith(f"(Dia {label})")
                        ],
                    }
                }
            )
        return self.result

    def assess_training(self, context):
        return AiTrainingPlanAssessment(
            sessions=[
                {"label": label, "complete": True, "issues": []}
                for label in context["training_schedule"]["session_labels"] or [""]
            ]
        )


class RetryProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__(proposal())
        self.fail_once = True

    def generate_training(self, context: dict[str, object]) -> AiTrainingGenerationResponse:
        self.calls += 1
        self.contexts.append(context)
        if self.fail_once:
            self.fail_once = False
            raise AiProviderError("timeout", retryable=True)
        return self.result


class FakeIdentityProvider:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self.identity = identity

    def get_identity(self, access_token: str) -> AuthenticatedIdentity:
        del access_token
        return self.identity


def proposal(**overrides: object) -> AiTrainingGenerationResponse:
    value: dict[str, object] = {
        "name": "Plano inicial de força",
        "objective": "Ganhar força com progressão gradual",
        "items": [
            {
                "exercise_name": "Agachamento",
                "sets": 3,
                "repetitions": "8",
                "load_guidance": "Carga confortável e técnica controlada",
                "rest_seconds": 90,
            }
        ],
    }
    value.update(overrides)
    return AiTrainingGenerationResponse(plan=value)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    value = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield value
    finally:
        value.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_client(session: Session, subject: str, email: str) -> Client:
    client = Client(
        name=email.split("@")[0],
        account=Account(email=email, keycloak_subject=subject, account_active=True),
    )
    session.add(client)
    session.commit()
    return client


def complete_onboarding(session: Session, subject: str, **overrides: object) -> None:
    service = OnboardingDraftService()
    values: dict[str, object] = {
        "training_goal": "Ganhar força",
        "training_experience": "beginner",
        "height_cm": 170,
        "weight_kg": "70.50",
        "has_limitations_or_complaints": True,
        "limitations_or_complaints": "Evitar impacto alto no joelho",
        "uses_medications": False,
        "has_health_conditions": True,
        "health_conditions": "Histórico informado pelo cliente",
    }
    values.update(overrides)
    scope = service.resolve_client_scope(session, subject)
    service.save_draft(session, scope, OnboardingDraftUpdate(**values))
    service.complete_draft(session, scope)


def test_requires_completed_authoritative_onboarding(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    service = InitialTrainingGenerationService(provider=FakeProvider(proposal()))
    with pytest.raises(CompletedOnboardingRequiredError):
        service.generate_for_subject(session, "ada")
    assert session.scalars(select(TrainingPlanVersion)).all() == []


def test_generates_only_client_scoped_proposal_using_completed_onboarding(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    grace = create_client(session, "grace", "grace@example.test")
    complete_onboarding(session, "ada")
    complete_onboarding(session, "grace", training_goal="Condicionamento")
    provider = FakeProvider(proposal())

    result = InitialTrainingGenerationService(provider=provider).generate_for_subject(
        session, "ada"
    )

    assert result.status == "proposal" and result.origin == "ai" and result.created_by == "ai"
    assert result.plan_id is not None
    onboarding_context = provider.contexts[0]["completed_onboarding"]
    assert isinstance(onboarding_context, dict)
    assert onboarding_context["training_goal"] == "Ganhar força"
    assert onboarding_context["limitations_or_complaints"] == ("Evitar impacto alto no joelho")
    assert "Condicionamento" not in json.dumps(provider.contexts[0], default=str)
    assert (
        session.scalar(select(TrainingPlan.client_id).where(TrainingPlan.id == result.plan_id))
        == ada.id
    )
    assert ada.id != grace.id


def test_reuses_the_single_active_draft_without_calling_the_provider_again(
    session: Session,
) -> None:
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    provider = FakeProvider(proposal())
    service = InitialTrainingGenerationService(provider=provider)

    first = service.generate_for_subject(session, "ada")
    second = service.generate_for_subject(session, "ada")

    assert first.id == second.id
    assert provider.calls == 1
    assert len(session.scalars(select(TrainingPlanVersion)).all()) == 1


def test_reuses_an_instructor_draft_without_calling_the_provider(session: Session) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    draft = TrainingLifecycleService().create_proposal(
        session,
        client_id=ada.id,
        data=TrainingPlanVersionInput.model_validate(proposal().plan),
        created_by="instructor-1",
        origin="instructor",
    )
    provider = FakeProvider(proposal())

    result = InitialTrainingGenerationService(provider=provider).generate_for_subject(
        session, "ada"
    )

    assert result.id == draft.id
    assert result.origin == "instructor"
    assert provider.calls == 0


def test_invalid_or_unavailable_provider_response_persists_nothing(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    malformed = InitialTrainingGenerationService(provider=FakeProvider(proposal(items=[])))
    with pytest.raises(InvalidTrainingGenerationError):
        malformed.generate_for_subject(session, "ada")
    unavailable = InitialTrainingGenerationService(
        provider=FakeProvider(AiProviderError("network", retryable=False))
    )
    with pytest.raises(TrainingGenerationUnavailableError):
        unavailable.generate_for_subject(session, "ada")
    assert session.scalars(select(TrainingPlanVersion)).all() == []


def test_retryable_provider_failure_retries_once(session: Session) -> None:
    create_client(session, "ada", "ada@example.test")
    complete_onboarding(session, "ada")
    provider = RetryProvider()
    result = InitialTrainingGenerationService(provider=provider).generate_for_subject(
        session, "ada"
    )
    assert result.status == "proposal" and provider.calls == 2


def app_for(session: Session) -> FastAPI:
    app = create_app()

    def override_database_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_database_session] = override_database_session
    return app


def request(app: FastAPI, authorization: str | None) -> tuple[int, dict[str, object]]:
    sent: list[dict[str, object]] = []
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/training/initial-proposal",
        "raw_path": b"/training/initial-proposal",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = next(message["body"] for message in sent if message["type"] == "http.response.body")
    return status, json.loads(body)


def test_generation_api_requires_authenticated_client_role(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_client(session, "ada", "ada@example.test")
    app = app_for(session)
    assert request(app, None) == (401, {"detail": "Unauthenticated"})
    monkeypatch.setattr(
        identity_router,
        "identity_provider",
        FakeIdentityProvider(AuthenticatedIdentity("admin", "admin@example.test", ("admin",))),
    )
    assert request(app, "Bearer token") == (403, {"detail": "Forbidden"})
    app.dependency_overrides.clear()


def test_client_generation_api_resolves_only_its_authenticated_identity(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    ada = create_client(session, "ada", "ada@example.test")
    create_client(session, "grace", "grace@example.test")
    complete_onboarding(session, "ada")
    complete_onboarding(session, "grace", training_goal="Condicionamento")
    monkeypatch.setattr(
        training_router,
        "generation_service",
        InitialTrainingGenerationService(provider=FakeProvider(proposal())),
    )
    monkeypatch.setattr(
        identity_router,
        "identity_provider",
        FakeIdentityProvider(AuthenticatedIdentity("ada", "ada@example.test", ("client",))),
    )
    app = app_for(session)
    response_status, response = request(app, "Bearer token")
    assert response_status == 201 and response["status"] == "proposal"
    plan_id = UUID(response["plan_id"])
    actual_client_id = session.scalar(
        select(TrainingPlan.client_id).where(TrainingPlan.id == plan_id)
    )
    assert actual_client_id == ada.id
    app.dependency_overrides.clear()
