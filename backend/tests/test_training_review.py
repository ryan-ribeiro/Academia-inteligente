from uuid import uuid4

import pytest
from sqlalchemy import select
from test_clients import AsgiClient
from test_training_adaptations import FakeAdaptationProvider, adjust_response, source_message
from test_training_lifecycle import client_id, data
from test_training_lifecycle import session as session
from training_fixtures import instructor, submitted_draft

from app.database import get_database_session
from app.main import create_app
from app.modules.clients.models import Account, Client
from app.modules.identity import router as identity_router
from app.modules.identity.service import AuthenticatedIdentity
from app.modules.training.adaptation_service import AdaptationStateError, TrainingAdaptationService
from app.modules.training.models import (
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.review_service import responsible_name
from app.modules.training.service import (
    ActiveTrainingProposalExistsError,
    ConcurrentTrainingUpdateError,
    InvalidTrainingContentError,
    InvalidTrainingTransitionError,
    TrainingLifecycleService,
)


def draft(session):
    return submitted_draft(
        session,
        TrainingLifecycleService().create_proposal(
            session, client_id=client_id(session), data=data(), created_by="ai", origin="ai"
        ),
    )


def approve(session, version, actor="instructor-1", revision=None):
    return TrainingLifecycleService().approve(
        session,
        plan_id=version.plan_id,
        version_number=version.version_number,
        actor=actor,
        expected_revision=revision or version.revision,
    )


def test_save_and_approval_revision_guards_and_history_attribution(session):
    service = TrainingLifecycleService()
    first = draft(session)
    service.revise(
        session,
        plan_id=first.plan_id,
        version_number=1,
        data=data("Editado"),
        actor="instructor-1",
        expected_revision=1,
    )
    assert first.status == "proposal" and not session.get(TrainingPlan, first.plan_id).is_current
    with pytest.raises(ConcurrentTrainingUpdateError):
        approve(session, first, revision=1)
    approve(session, first, revision=2)
    original_name = first.responsible_name
    employee = instructor(session)
    assert first.responsible_employee_id == employee.id and first.approved_at
    employee.account.person_profile.first_name = "Nome novo"
    session.commit()
    assert responsible_name(session, first) == "Nome novo Silva"
    second = service.create_revision(
        session,
        plan_id=first.plan_id,
        version_number=1,
        data=data("Próximo"),
        actor="instructor-2",
        expected_revision=first.revision,
    )
    approve(session, second, "instructor-2")
    employee.active = False
    session.commit()
    assert first.status == "superseded"
    assert responsible_name(session, first) == original_name
    assert first.responsible_employee_id == employee.id
    assert second.responsible_employee_id != first.responsible_employee_id


def test_approval_rolls_back_prior_current_and_attribution_on_commit_failure(session, monkeypatch):
    service = TrainingLifecycleService()
    first = approve(session, draft(session))
    second = service.create_revision(
        session, plan_id=first.plan_id, version_number=1, data=data("Novo"), actor="instructor-2"
    )
    second_id = second.id
    with monkeypatch.context() as patch:
        patch.setattr(
            session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("test failure"))
        )
        with pytest.raises(RuntimeError):
            approve(session, second, "instructor-2")
    session.expire_all()
    assert first.status == "current"
    assert session.get(TrainingPlanVersion, second_id).status == "proposal"
    assert session.get(TrainingPlanVersion, second_id).responsible_employee_id is None


def test_approval_validates_complete_draft_and_local_employee(session):
    version = draft(session)
    with pytest.raises(InvalidTrainingTransitionError):
        approve(session, version, "unlinked-instructor")
    item = session.scalar(select(TrainingPlanItem).where(TrainingPlanItem.version_id == version.id))
    item.sets = 0
    session.commit()
    with pytest.raises(InvalidTrainingContentError):
        approve(session, version)
    assert version.status == "proposal"


def adaptation(session, base):
    client = session.get(Client, base.client_id)
    source = uuid4()
    source_message(session, client, source)
    service = TrainingAdaptationService(FakeAdaptationProvider(adjust_response()))
    proposal = service.generate(
        session,
        "client",
        source_client_request_id=source,
        client_request_id=uuid4(),
        reason="Ajustar carga",
    )
    return service, proposal


def test_accepted_adaptation_uses_single_draft_and_preserves_source(session):
    lifecycle = TrainingLifecycleService()
    base = approve(session, draft(session))
    service, proposal = adaptation(session, base)
    service.client_decide(session, "client", proposal.id, True)
    accepted = lifecycle.find_proposal(session, client_id=base.client_id)
    assert accepted.id == proposal.resulting_version_id
    assert accepted.status == "proposal" and base.status == "current"
    assert (
        service.client_decide(session, "client", proposal.id, True).resulting_version_id
        == accepted.id
    )
    for origin in ("ai", "instructor"):
        with pytest.raises(ActiveTrainingProposalExistsError):
            lifecycle.create_proposal(
                session, client_id=base.client_id, data=data(), created_by=origin, origin=origin
            )
    source_reason = proposal.reason
    approve(session, accepted)
    assert proposal.status == "approved" and proposal.reason == source_reason
    assert proposal.resulting_version_id == accepted.id
    assert base.status == "superseded"


def test_adaptation_conflict_never_overwrites_existing_draft(session):
    lifecycle = TrainingLifecycleService()
    base = approve(session, draft(session))
    service, proposal = adaptation(session, base)
    existing = lifecycle.create_revision(
        session,
        plan_id=base.plan_id,
        version_number=1,
        data=data("Existente"),
        actor="instructor-1",
    )
    with pytest.raises(ActiveTrainingProposalExistsError):
        service.client_decide(session, "client", proposal.id, True)
    assert existing.name == "Existente" and base.status == "current"
    assert proposal.status == "proposed" and proposal.resulting_version_id is None


def test_stale_base_is_not_merged_and_client_rejection_is_inert(session):
    lifecycle = TrainingLifecycleService()
    base = approve(session, draft(session))
    service, proposal = adaptation(session, base)
    newer = lifecycle.create_revision(
        session, plan_id=base.plan_id, version_number=1, data=data("Novo"), actor="instructor-1"
    )
    approve(session, newer)
    with pytest.raises(AdaptationStateError):
        service.client_decide(session, "client", proposal.id, True)
    assert proposal.status == "superseded"
    assert not lifecycle.find_proposal(session, client_id=base.client_id)


@pytest.fixture
def api(session, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_database_session] = lambda: session

    class FakeIdentity:
        identity = AuthenticatedIdentity("instructor-1", "instructor", ("instructor",))

        def get_identity(self, token):
            return self.identity

    fake = FakeIdentity()
    monkeypatch.setattr(identity_router, "identity_provider", fake)
    return AsgiClient(app), fake


def test_pending_api_minimization_pagination_detail_and_atomic_approval(session, api):
    client, identity = api
    version = draft(session)
    other = Client(
        name="Outro cliente", account=Account(email="other@test.test", account_active=True)
    )
    session.add(other)
    session.commit()
    TrainingLifecycleService().create_proposal(
        session,
        client_id=other.id,
        data=data("Outro plano"),
        created_by="instructor-2",
        origin="instructor",
    )
    page = client.get("/training/pending", {"limit": "1"})
    assert page.status_code == 200 and page.json()["next_offset"] == 1
    assert len(client.get("/training/pending", {"limit": "1", "offset": "1"}).json()["items"]) == 1
    detail = client.get(f"/training/pending/{version.id}").json()
    assert detail["client_name"] == "Cliente"
    assert "equipment_model_id" in detail["items"][0]
    assert "equipment_requirement" in detail["items"][0]
    for forbidden in (
        "cpf",
        "email",
        "phone",
        "account_id",
        "client_id",
        "created_by",
        "approved_by",
        "responsible_employee_id",
    ):
        assert forbidden not in detail
    path = f"/training/plans/{version.plan_id}/versions/1"
    assert (
        client.patch(
            path, {**data("Salvo").model_dump(mode="json"), "expected_revision": 1}
        ).status_code
        == 200
    )
    assert version.status == "proposal"
    assert client.post(f"{path}/approve", {"expected_revision": 1}).status_code == 409
    assert client.post(f"{path}/approve", {"expected_revision": 2}).status_code == 200
    assert client.post(f"{path}/approve", {"expected_revision": 2}).status_code == 409
    assert client.get(f"/training/pending/{version.id}").status_code == 404
    assert client.post(f"{path}/activate", {"expected_revision": 2}).status_code in (404, 405)
    assert client.get("/training/adaptations/review").status_code in (404, 405)
    assert client.post(
        f"/training/adaptations/{uuid4()}/instructor-decision", {"approve": True}
    ).status_code in (404, 405)
    identity.identity = AuthenticatedIdentity("client", "client", ("client",))
    current = client.get("/training/current").json()["plan"]
    assert current["responsible_instructor_name"] and current["approved_at"]
    assert "approved_by" not in current


@pytest.mark.parametrize("role", ["client", "admin", "employee", "attendant"])
def test_pending_and_writes_require_instructor(session, api, role):
    client, identity = api
    version = draft(session)
    identity.identity = AuthenticatedIdentity("client", "client", (role,))
    for method, path, body in [
        ("GET", "/training/pending", None),
        ("GET", f"/training/pending/{version.id}", None),
        (
            "PATCH",
            f"/training/plans/{version.plan_id}/versions/1",
            {**data().model_dump(mode="json"), "expected_revision": 1},
        ),
        ("POST", f"/training/plans/{version.plan_id}/versions/1/approve", {"expected_revision": 1}),
    ]:
        assert client.request(method, path, body).status_code == 403


def test_stale_instructor_token_is_denied(session, api):
    client, identity = api
    employee = instructor(session)
    employee.active = False
    session.commit()
    assert client.get("/training/pending").status_code == 401


def test_client_rejection_never_creates_a_draft(session):
    base = approve(session, draft(session))
    service, proposal = adaptation(session, base)
    service.client_decide(session, "client", proposal.id, False)
    assert proposal.status == "client_rejected"
    assert base.status == "current"
    assert not TrainingLifecycleService().find_proposal(session, client_id=base.client_id)


def test_acceptance_failure_rolls_back_draft_and_source(session, monkeypatch):
    base = approve(session, draft(session))
    service, proposal = adaptation(session, base)
    with monkeypatch.context() as patch:
        patch.setattr(
            session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("test failure"))
        )
        with pytest.raises(RuntimeError):
            service.client_decide(session, "client", proposal.id, True)
    session.expire_all()
    assert proposal.status == "proposed" and proposal.resulting_version_id is None
    assert base.status == "current"
    assert not TrainingLifecycleService().find_proposal(session, client_id=base.client_id)


def test_inflight_ai_response_cannot_overwrite_a_newer_instructor_edit(session):
    from app.integrations.ai import AiTrainingChatResponse
    from app.modules.training.chat_service import TrainingChatService

    version = draft(session)

    from training_fixtures import AcceptingTrainingReviewer

    class Provider(AcceptingTrainingReviewer):
        def training_chat(self, context):
            TrainingLifecycleService().revise(
                session,
                plan_id=version.plan_id,
                version_number=1,
                data=data("Salvo pelo instrutor"),
                actor="instructor-1",
                expected_revision=1,
            )
            return AiTrainingChatResponse(
                assistant_message="Atualizado",
                draft_update=data("Resposta antiga").model_dump(mode="json"),
            )

    with pytest.raises(ConcurrentTrainingUpdateError):
        TrainingChatService(Provider()).submit_for_subject(
            session, "client", message="Atualize o rascunho", client_request_id=uuid4()
        )
    assert version.name == "Salvo pelo instrutor" and version.revision == 2
