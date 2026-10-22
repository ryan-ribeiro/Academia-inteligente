from __future__ import annotations

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from training_fixtures import AcceptingTrainingReviewer, instructor

from app.database import Base
from app.integrations.ai import AiProviderError, AiTrainingAdaptationResponse
from app.modules.clients.models import Account, Client
from app.modules.equipment.models import EquipmentModel, EquipmentUnit
from app.modules.equipment.service import EquipmentService
from app.modules.training.adaptation_service import (
    AdaptationNotFoundError,
    AdaptationStateError,
    AdaptationUnavailableError,
    InvalidEquipmentReferenceError,
    TrainingAdaptationService,
)
from app.modules.training.models import (
    TrainingAdaptationOperation,
    TrainingAdaptationProposal,
    TrainingAiConversation,
    TrainingAiMessage,
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.schema import ManualPlanCreate, TrainingPlanItemInput
from app.modules.training.service import TrainingLifecycleService


class FakeAdaptationProvider(AcceptingTrainingReviewer):
    def __init__(self, response: AiTrainingAdaptationResponse | Exception) -> None:
        self.response = response
        self.calls = 0
        self.contexts: list[dict[str, object]] = []

    def generate_adaptation(self, context: dict[str, object]) -> AiTrainingAdaptationResponse:
        self.calls += 1
        self.contexts.append(context)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class RetryAdaptationProvider(FakeAdaptationProvider):
    def __init__(self) -> None:
        super().__init__(adjust_response())
        self.fail_once = True

    def generate_adaptation(self, context: dict[str, object]) -> AiTrainingAdaptationResponse:
        self.calls += 1
        self.contexts.append(context)
        if self.fail_once:
            self.fail_once = False
            raise AiProviderError("timeout", retryable=True)
        return self.response


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


def client(session: Session, subject: str, email: str) -> Client:
    value = Client(
        name=email.split("@")[0],
        account=Account(email=email, keycloak_subject=subject, account_active=True),
    )
    session.add(value)
    session.commit()
    return value


def current_plan(session: Session, owner: Client) -> TrainingPlanVersion:
    instructor(session, "instructor-1")
    lifecycle = TrainingLifecycleService()
    proposal = lifecycle.create_proposal(
        session,
        client_id=owner.id,
        data=ManualPlanCreate(
            client_id=str(owner.id),
            name="Força",
            objective="Ganhar força",
            items=[
                TrainingPlanItemInput(
                    exercise_name="Agachamento",
                    sets=3,
                    repetitions="8",
                    load_guidance="Carga confortável",
                    rest_seconds=90,
                ),
                TrainingPlanItemInput(
                    exercise_name="Remada",
                    sets=3,
                    repetitions="10",
                    load_guidance="Carga confortável",
                    rest_seconds=60,
                ),
            ],
        ),
        created_by="instructor-1",
        origin="instructor",
    )
    approved = lifecycle.approve(
        session,
        plan_id=proposal.plan_id,
        version_number=proposal.version_number,
        actor="instructor-1",
        expected_revision=proposal.revision,
    )
    return approved


def source_message(session: Session, owner: Client, request_id: UUID) -> None:
    conversation = TrainingAiConversation(client_id=owner.id)
    session.add(conversation)
    session.flush()
    session.add(
        TrainingAiMessage(
            conversation_id=conversation.id,
            role="user",
            content="O agachamento incomoda meu joelho.",
            sequence=1,
            client_request_id=request_id,
        )
    )
    session.commit()


def equipment_model(
    session: Session, name: str, *, active: bool = True, active_units: int = 1
) -> EquipmentModel:
    model = EquipmentModel(name=name, active=active)
    session.add(model)
    session.flush()
    session.add_all(
        EquipmentUnit(equipment_model_id=model.id, label=f"Unidade {index + 1}", active=True)
        for index in range(active_units)
    )
    session.commit()
    return model


def adjust_response() -> AiTrainingAdaptationResponse:
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


def test_client_confirmed_adaptation_creates_one_new_current_version(
    session: Session,
) -> None:
    ada = client(session, "ada", "ada@example.test")
    old_current = current_plan(session, ada)
    source_id, adaptation_id = uuid4(), uuid4()
    source_message(session, ada, source_id)
    provider = FakeAdaptationProvider(adjust_response())
    service = TrainingAdaptationService(provider)

    proposal = service.generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=adaptation_id,
        reason="O exercício incomoda meu joelho.",
    )
    duplicate = service.generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=adaptation_id,
        reason="O exercício incomoda meu joelho.",
    )
    assert proposal.id == duplicate.id
    assert provider.calls == 1
    assert old_current.status == "current"
    assert "grace@example.test" not in str(provider.contexts[0])

    service.client_decide(session, "ada", proposal.id, True)
    instructor(session, "instructor-2", "Outra")
    draft = session.get(TrainingPlanVersion, proposal.resulting_version_id)
    TrainingLifecycleService().approve(
        session,
        plan_id=draft.plan_id,
        version_number=draft.version_number,
        actor="instructor-2",
        expected_revision=draft.revision,
    )
    approved = proposal
    versions = list(
        session.scalars(
            select(TrainingPlanVersion)
            .where(TrainingPlanVersion.plan_id == old_current.plan_id)
            .order_by(TrainingPlanVersion.version_number)
        )
    )
    items = list(
        session.scalars(
            select(TrainingPlanItem)
            .where(TrainingPlanItem.version_id == approved.resulting_version_id)
            .order_by(TrainingPlanItem.position)
        )
    )
    assert approved.status == "approved"
    assert old_current.status == "superseded"
    assert [version.status for version in versions] == ["superseded", "current"]
    assert [item.exercise_name for item in items] == ["Agachamento", "Remada"]
    assert items[0].sets == 2 and items[1].sets == 3
    assert versions[-1].approved_by == "instructor-2"
    with pytest.raises(AdaptationStateError):
        service.client_decide(session, "ada", proposal.id, True)
    assert len(versions) == 2


@pytest.mark.parametrize("operation_type", ["add", "remove", "replace"])
def test_supported_operation_types_are_persisted_without_catalog_mutation(
    session: Session, operation_type: str
) -> None:
    ada = client(session, "ada", "ada@example.test")
    current_plan(session, ada)
    model = equipment_model(session, "Leg Press 45°")
    source_id = uuid4()
    source_message(session, ada, source_id)
    item = {
        "exercise_name": "Leg Press",
        "sets": 3,
        "repetitions": "10",
        "load_guidance": "Carga moderada",
        "rest_seconds": 90,
        "equipment_requirement": model.name,
        "equipment_model_id": str(model.id),
        "is_existing_exercise": False,
    }
    provider = FakeAdaptationProvider(
        AiTrainingAdaptationResponse(
            explanation="Proposta para revisão.",
            operations=[
                {
                    "operation_type": operation_type,
                    "target_position": None if operation_type == "add" else 1,
                    "item": None if operation_type == "remove" else item,
                }
            ],
        )
    )
    proposal = TrainingAdaptationService(provider).generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=uuid4(),
        reason="Quero uma alternativa.",
    )
    assert proposal.status == "proposed"
    assert session.scalar(select(TrainingPlan).where(TrainingPlan.is_current)) is not None
    assert provider.calls == 1


def test_adaptation_uses_active_catalog_models_and_persists_canonical_identity(
    session: Session,
) -> None:
    ada = client(session, "ada", "ada@example.test")
    current_plan(session, ada)
    allowed = equipment_model(session, "Leg Press 45°")
    equipment_model(session, "Modelo sem unidades", active_units=0)
    equipment_model(session, "Modelo inativo", active=False)
    blocked = equipment_model(session, "Modelo fora de serviço")
    blocked_unit = session.scalar(
        select(EquipmentUnit).where(EquipmentUnit.equipment_model_id == blocked.id)
    )
    EquipmentService().set_operational_state(session, blocked_unit.id, "out_of_order", 1)
    source_id = uuid4()
    source_message(session, ada, source_id)
    provider = FakeAdaptationProvider(
        AiTrainingAdaptationResponse(
            explanation="Substituição para revisão.",
            operations=[
                {
                    "operation_type": "replace",
                    "target_position": 1,
                    "item": {
                        "exercise_name": "Leg Press 45°",
                        "sets": 3,
                        "repetitions": "10",
                        "load_guidance": "Carga confortável",
                        "rest_seconds": 90,
                        "equipment_requirement": allowed.name,
                        "equipment_model_id": str(allowed.id),
                        "is_existing_exercise": False,
                    },
                }
            ],
        )
    )

    proposal = TrainingAdaptationService(provider).generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=uuid4(),
        reason="Quero usar a máquina.",
    )

    assert provider.contexts[0]["active_equipment_models"] == [
        {"id": str(allowed.id), "name": "Leg Press 45°"}
    ]
    operation = session.scalar(
        select(TrainingAdaptationOperation).where(
            TrainingAdaptationOperation.proposal_id == proposal.id
        )
    )
    assert operation is not None
    assert operation.equipment_model_id == allowed.id
    assert operation.equipment_requirement == allowed.name


@pytest.mark.parametrize(
    ("model_active", "unit_count", "model_reference", "equipment_requirement"),
    [
        (True, 0, "created", "Modelo sem unidades"),
        (False, 1, "created", "Modelo inativo"),
        (True, 1, "unknown", "Modelo desconhecido"),
        (True, 1, None, "Modelo sem referência"),
        (True, 1, "created", None),
        (True, 1, "out_of_order", "Modelo fora de serviço"),
    ],
)
def test_invalid_equipment_references_are_rejected_atomically(
    session: Session,
    model_active: bool,
    unit_count: int,
    model_reference: str | None,
    equipment_requirement: str | None,
) -> None:
    ada = client(session, "ada", "ada@example.test")
    current = current_plan(session, ada)
    model = equipment_model(
        session, "Modelo para validação", active=model_active, active_units=unit_count
    )
    source_id = uuid4()
    source_message(session, ada, source_id)
    if model_reference == "out_of_order":
        unit = session.scalar(
            select(EquipmentUnit).where(EquipmentUnit.equipment_model_id == model.id)
        )
        EquipmentService().set_operational_state(session, unit.id, "out_of_order", 1)
    reference = (
        str(model.id)
        if model_reference in {"created", "out_of_order"}
        else str(uuid4())
        if model_reference == "unknown"
        else None
    )
    provider = FakeAdaptationProvider(
        AiTrainingAdaptationResponse(
            explanation="Proposta inválida.",
            operations=[
                {
                    "operation_type": "replace",
                    "target_position": 1,
                    "item": {
                        "exercise_name": "Exercício na máquina",
                        "sets": 3,
                        "repetitions": "10",
                        "load_guidance": "Carga confortável",
                        "rest_seconds": 90,
                        "equipment_requirement": equipment_requirement,
                        "equipment_model_id": reference,
                        "is_existing_exercise": False,
                    },
                }
            ],
        )
    )

    with pytest.raises(InvalidEquipmentReferenceError):
        TrainingAdaptationService(provider).generate(
            session,
            "ada",
            source_client_request_id=source_id,
            client_request_id=uuid4(),
            reason="Preciso de uma alternativa.",
        )
    assert session.scalars(select(TrainingAdaptationProposal)).all() == []
    assert current.status == "current"


def test_renamed_or_deactivated_model_preserves_retained_proposal_history(
    session: Session,
) -> None:
    ada = client(session, "ada", "ada@example.test")
    current_plan(session, ada)
    model = equipment_model(session, "Leg Press 45°")
    source_id = uuid4()
    source_message(session, ada, source_id)
    provider = FakeAdaptationProvider(
        AiTrainingAdaptationResponse(
            explanation="Proposta para revisão.",
            operations=[
                {
                    "operation_type": "replace",
                    "target_position": 1,
                    "item": {
                        "exercise_name": "Leg Press 45°",
                        "sets": 3,
                        "repetitions": "10",
                        "load_guidance": "Carga confortável",
                        "rest_seconds": 90,
                        "equipment_requirement": model.name,
                        "equipment_model_id": str(model.id),
                        "is_existing_exercise": False,
                    },
                }
            ],
        )
    )
    service = TrainingAdaptationService(provider)
    proposal = service.generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=uuid4(),
        reason="Quero uma alternativa.",
    )
    EquipmentService().update_model(
        session,
        model.id,
        name="Leg Press inclinado",
        description=None,
        image_url=None,
        active=False,
    )
    with pytest.raises(AdaptationStateError):
        service.client_decide(session, "ada", proposal.id, True)
    session.refresh(proposal)
    assert proposal.status == "proposed" and proposal.resulting_version_id is None
    operation = session.scalar(
        select(TrainingAdaptationOperation).where(
            TrainingAdaptationOperation.proposal_id == proposal.id
        )
    )
    assert operation is not None
    assert operation.equipment_model_id == model.id
    assert operation.equipment_requirement == "Leg Press 45°"


def test_wrong_client_and_provider_failure_create_no_proposal(session: Session) -> None:
    ada = client(session, "ada", "ada@example.test")
    grace = client(session, "grace", "grace@example.test")
    current_plan(session, ada)
    current_plan(session, grace)
    source_id = uuid4()
    source_message(session, ada, source_id)
    service = TrainingAdaptationService(FakeAdaptationProvider(adjust_response()))
    with pytest.raises(AdaptationNotFoundError):
        service.generate(
            session,
            "grace",
            source_client_request_id=source_id,
            client_request_id=uuid4(),
            reason="Quero alterar.",
        )

    unavailable = TrainingAdaptationService(
        FakeAdaptationProvider(AiProviderError("configuration", retryable=False))
    )
    with pytest.raises(AdaptationUnavailableError):
        unavailable.generate(
            session,
            "ada",
            source_client_request_id=source_id,
            client_request_id=uuid4(),
            reason="Quero alterar.",
        )
    assert session.scalars(select(TrainingAdaptationProposal)).all() == []


def test_retryable_generation_failure_retries_once(session: Session) -> None:
    ada = client(session, "ada", "ada@example.test")
    current_plan(session, ada)
    source_id = uuid4()
    source_message(session, ada, source_id)
    provider = RetryAdaptationProvider()
    proposal = TrainingAdaptationService(provider).generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=uuid4(),
        reason="Quero ajustar o treino.",
    )
    assert proposal.status == "proposed"
    assert provider.calls == 2


def test_adaptation_carries_unchanged_approved_machine_item_through_outage(session):
    ada = client(session, "ada", "ada@example.test")
    base = current_plan(session, ada)
    model = equipment_model(session, "Máquina histórica")
    lifecycle = TrainingLifecycleService()
    content = lifecycle.content(session, base)
    item = content.items[1]
    item.equipment_model_id, item.equipment_requirement = model.id, model.name
    draft = lifecycle.create_revision(
        session, plan_id=base.plan_id, version_number=1, data=content, actor="instructor-1"
    )
    base = lifecycle.approve(
        session,
        plan_id=draft.plan_id,
        version_number=2,
        actor="instructor-1",
        expected_revision=draft.revision,
    )
    unit = session.scalar(select(EquipmentUnit).where(EquipmentUnit.equipment_model_id == model.id))
    EquipmentService().set_operational_state(session, unit.id, "out_of_order", 1)
    source_id = uuid4()
    source_message(session, ada, source_id)
    provider = FakeAdaptationProvider(adjust_response())
    service = TrainingAdaptationService(provider)
    proposal = service.generate(
        session,
        "ada",
        source_client_request_id=source_id,
        client_request_id=uuid4(),
        reason="Ajustar agachamento",
    )
    assert provider.contexts[0]["active_equipment_models"] == []
    service.client_decide(session, "ada", proposal.id, True)
    draft = session.get(TrainingPlanVersion, proposal.resulting_version_id)
    lifecycle.approve(
        session,
        plan_id=draft.plan_id,
        version_number=draft.version_number,
        actor="instructor-1",
        expected_revision=draft.revision,
    )
    assert lifecycle.content(session, draft).items[1] == item
    assert lifecycle.content(session, base) == content
