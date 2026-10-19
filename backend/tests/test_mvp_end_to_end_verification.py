"""Cross-module MVP verification using local storage and controlled adapters."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from training_fixtures import instructor

from app.database import Base, get_database_session
from app.integrations.ai import (
    AiProviderError,
    AiTrainingAdaptationResponse,
    AiTrainingChatResponse,
    AiTrainingGenerationResponse,
)
from app.main import create_app
from app.modules.clients.models import Account, Client
from app.modules.identity import router as identity_router
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training import router as training_router
from app.modules.training.adaptation_service import TrainingAdaptationService
from app.modules.training.chat_service import TrainingChatService
from app.modules.training.generation_service import InitialTrainingGenerationService


class MutableIdentityProvider:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self.identity = identity

    def get_identity(self, access_token: str) -> AuthenticatedIdentity:
        del access_token
        return self.identity


class GenerationProvider:
    def generate_training(self, context: dict[str, object]) -> AiTrainingGenerationResponse:
        assert context["completed_onboarding"]
        return AiTrainingGenerationResponse(
            plan={
                "name": "Plano inicial de força",
                "objective": "Ganhar força com progressão gradual",
                "items": [
                    {
                        "exercise_name": "Agachamento",
                        "sets": 3,
                        "repetitions": "8",
                        "load_guidance": "Carga confortável",
                        "rest_seconds": 90,
                    },
                    {
                        "exercise_name": "Remada",
                        "sets": 3,
                        "repetitions": "10",
                        "load_guidance": "Carga confortável",
                        "rest_seconds": 60,
                    },
                ],
            }
        )


class ChatProvider:
    def training_chat(self, context: dict[str, object]) -> AiTrainingChatResponse:
        assert context["current_training_plan"] is not None
        return AiTrainingChatResponse(
            assistant_message="Vamos preparar uma adaptação para revisão profissional.",
            adaptation_suggested=True,
            adaptation_reason="Desconforto relatado no agachamento.",
        )


class FailingChatProvider:
    def training_chat(self, context: dict[str, object]) -> AiTrainingChatResponse:
        del context
        raise AiProviderError("unavailable", retryable=False)


class AdaptationProvider:
    def generate_adaptation(self, context: dict[str, object]) -> AiTrainingAdaptationResponse:
        assert context["base_plan"]
        return AiTrainingAdaptationResponse(
            explanation="Vamos reduzir a exigência do agachamento para revisão profissional.",
            operations=[
                {
                    "operation_type": "adjust",
                    "target_position": 1,
                    "item": {
                        "exercise_name": "Agachamento",
                        "sets": 2,
                        "repetitions": "8",
                        "load_guidance": "Carga leve e confortável",
                        "rest_seconds": 90,
                        "equipment_requirement": None,
                        "is_existing_exercise": True,
                    },
                }
            ],
        )


@dataclass
class ApiResponse:
    status_code: int
    body: object


class AsgiClient:
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> ApiResponse:
        sent: list[dict[str, object]] = []
        request_body = json.dumps(payload).encode() if payload is not None else b""
        headers = [(b"authorization", b"Bearer verification-token")]
        if payload is not None:
            headers.append((b"content-type", b"application/json"))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": request_body, "more_body": False}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        asyncio.run(self.app(scope, receive, send))
        status_code = next(
            message["status"] for message in sent if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"") for message in sent if message["type"] == "http.response.body"
        )
        return ApiResponse(status_code=status_code, body=json.loads(body))


@pytest.fixture
def database_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
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


def test_client_critical_path_is_scoped_and_preserves_history(
    database_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_client(database_session, "ada", "ada@example.test")
    create_client(database_session, "grace", "grace@example.test")
    instructor(database_session, "instructor")
    app = create_app()

    def override_database_session() -> Generator[Session, None, None]:
        yield database_session

    app.dependency_overrides[get_database_session] = override_database_session
    api = AsgiClient(app)
    identity = MutableIdentityProvider(
        AuthenticatedIdentity("ada", "ada@example.test", ("client",))
    )
    monkeypatch.setattr(identity_router, "identity_provider", identity)
    monkeypatch.setattr(
        training_router,
        "generation_service",
        InitialTrainingGenerationService(provider=GenerationProvider()),
    )
    monkeypatch.setattr(training_router, "chat_service", TrainingChatService(ChatProvider()))
    monkeypatch.setattr(
        training_router,
        "adaptation_service",
        TrainingAdaptationService(AdaptationProvider()),
    )

    onboarding = {
        "training_goal": "Ganhar força",
        "training_experience": "beginner",
        "height_cm": 170,
        "weight_kg": "70.50",
        "has_limitations_or_complaints": True,
        "limitations_or_complaints": "Evitar impacto alto no joelho",
        "uses_medications": False,
        "has_health_conditions": False,
    }
    assert api.request("PATCH", "/onboarding/me", onboarding).status_code == 200
    assert api.request("POST", "/onboarding/me/completion").status_code == 200

    draft = api.request("POST", "/training/initial-proposal")
    assert draft.status_code == 201
    assert draft.body["status"] == "proposal"
    plan_id = draft.body["plan_id"]
    version_number = draft.body["version_number"]

    submitted = api.request(
        "POST",
        f"/training/drafts/{draft.body['id']}/submit",
        {"expected_revision": draft.body["revision"]},
    )
    assert submitted.status_code == 200
    assert submitted.body["submitted_for_review_at"] is not None

    identity.identity = AuthenticatedIdentity(
        "instructor", "instructor@example.test", ("instructor",)
    )
    approved = api.request(
        "POST",
        f"/training/plans/{plan_id}/versions/{version_number}/approve",
        {"expected_revision": submitted.body["revision"]},
    )
    assert approved.status_code == 200
    assert approved.body["status"] == "current"

    identity.identity = AuthenticatedIdentity("ada", "ada@example.test", ("client",))
    current = api.request("GET", "/training/current")
    assert current.status_code == 200
    assert current.body["plan"]["name"] == "Plano inicial de força"

    source_request_id = str(uuid4())
    chat = api.request(
        "POST",
        "/training/chat/messages",
        {"message": "Meu joelho incomoda no agachamento.", "client_request_id": source_request_id},
    )
    assert chat.status_code == 200
    assert chat.body["messages"][-1]["adaptation_suggested"] is True

    adaptation = api.request(
        "POST",
        "/training/adaptations",
        {
            "source_client_request_id": source_request_id,
            "client_request_id": str(uuid4()),
            "reason": "Desconforto relatado no agachamento.",
        },
    )
    assert adaptation.status_code == 201
    proposal_id = adaptation.body["id"]
    assert (
        api.request(
            "POST", f"/training/adaptations/{proposal_id}/client-decision", {"accept": True}
        ).status_code
        == 200
    )

    identity.identity = AuthenticatedIdentity(
        "instructor", "instructor@example.test", ("instructor",)
    )
    pending = api.request("GET", "/training/pending")
    assert pending.status_code == 200
    assert len(pending.body["items"]) == 1
    review = pending.body["items"][0]
    assert (
        api.request(
            "POST",
            f"/training/plans/{review['plan_id']}/versions/{review['version_number']}/approve",
            {"expected_revision": review["revision"]},
        ).status_code
        == 200
    )

    identity.identity = AuthenticatedIdentity("ada", "ada@example.test", ("client",))
    updated_current = api.request("GET", "/training/current")
    assert updated_current.body["plan"]["version_number"] == 2
    assert updated_current.body["plan"]["items"][0]["sets"] == 2
    assert updated_current.body["plan"]["items"][1]["exercise_name"] == "Remada"

    identity.identity = AuthenticatedIdentity("grace", "grace@example.test", ("client",))
    assert api.request("GET", "/training/current").body == {"plan": None}
    assert api.request("GET", "/training/chat").body == {"messages": [], "draft": None}
    assert api.request("GET", "/clients").status_code == 403

    identity.identity = AuthenticatedIdentity("ada", "ada@example.test", ("client",))
    monkeypatch.setattr(training_router, "chat_service", TrainingChatService(FailingChatProvider()))
    failed_chat = api.request(
        "POST",
        "/training/chat/messages",
        {"message": "Explique meu treino.", "client_request_id": str(uuid4())},
    )
    assert failed_chat.status_code == 503
    assert api.request("GET", "/training/current").body["plan"]["version_number"] == 2
    app.dependency_overrides.clear()
