"""Lifecycle service shared by future AI and manual training callers."""

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.clients.models import Account, Client, Employee
from app.modules.equipment.service import EquipmentService
from app.modules.knowledge.service import KnowledgeResult
from app.modules.training.models import (
    TrainingAdaptationProposal,
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.schema import PlanOrigin, TrainingPlanItemInput, TrainingPlanVersionInput


class TrainingLifecycleError(Exception):
    pass


class TrainingVersionNotFoundError(TrainingLifecycleError):
    pass


class ImmutableTrainingVersionError(TrainingLifecycleError):
    pass


class ConcurrentTrainingUpdateError(TrainingLifecycleError):
    pass


class InvalidTrainingTransitionError(TrainingLifecycleError):
    pass


class ActiveTrainingProposalExistsError(TrainingLifecycleError):
    pass


class InvalidTrainingContentError(TrainingLifecycleError):
    pass


class TrainingLifecycleService:
    def find_proposal(self, session: Session, *, client_id: UUID) -> TrainingPlanVersion | None:
        return session.scalar(
            select(TrainingPlanVersion)
            .where(
                TrainingPlanVersion.client_id == client_id,
                TrainingPlanVersion.status == "proposal",
            )
            .order_by(TrainingPlanVersion.created_at.desc())
        )

    def create_proposal(
        self,
        session: Session,
        *,
        client_id: UUID,
        data: TrainingPlanVersionInput,
        created_by: str,
        origin: PlanOrigin,
        created_employee_id: UUID | None = None,
        knowledge: KnowledgeResult | None = None,
        commit: bool = True,
    ) -> TrainingPlanVersion:
        self._lock_client(session, client_id)
        if self.find_proposal(session, client_id=client_id) is not None:
            raise ActiveTrainingProposalExistsError
        try:
            plan = TrainingPlan(client_id=client_id)
            session.add(plan)
            session.flush()
            return self._new_version(
                session,
                plan.id,
                client_id,
                1,
                data,
                created_by,
                origin,
                created_employee_id=created_employee_id,
                knowledge=knowledge,
                commit=commit,
            )
        except IntegrityError:
            if not commit:
                raise  # The caller owns the transaction/savepoint.
            session.rollback()
            if self.find_proposal(session, client_id=client_id) is not None:
                raise ActiveTrainingProposalExistsError from None
            raise
        except Exception:
            if commit:
                session.rollback()
            raise

    def revise(
        self,
        session: Session,
        *,
        plan_id: UUID,
        version_number: int,
        data: TrainingPlanVersionInput,
        actor: str,
        expected_revision: int,
        commit: bool = True,
        standalone: bool = False,
    ) -> TrainingPlanVersion:
        version = self._version(session, plan_id, version_number, lock=True)
        if version.status != "proposal":
            raise ImmutableTrainingVersionError
        if version.revision != expected_revision:
            raise ConcurrentTrainingUpdateError
        if actor != "ai" and version.submitted_for_review_at is None:
            raise InvalidTrainingTransitionError
        self.validate_equipment(session, data, None if standalone else version)
        try:
            if standalone:
                # A newly requested sheet replaces the editable draft's content,
                # not its approved base. Keep it appendable even when the sole
                # draft previously represented an edit of the current plan.
                historical = session.scalar(
                    select(TrainingPlanVersion.id)
                    .where(
                        TrainingPlanVersion.plan_id == version.plan_id,
                        TrainingPlanVersion.id != version.id,
                    )
                    .limit(1)
                )
                if historical is not None:
                    plan = TrainingPlan(client_id=version.client_id)
                    session.add(plan)
                    session.flush()
                    version.plan_id, version.version_number = plan.id, 1
                for adaptation in session.scalars(
                    select(TrainingAdaptationProposal)
                    .where(TrainingAdaptationProposal.resulting_version_id == version.id)
                    .with_for_update()
                ):
                    # Retain the original operations as history, independently
                    # from this explicitly requested replacement sheet.
                    adaptation.status = "superseded"
                    adaptation.resulting_version_id = None
            self._replace_content(session, version, data)
            if actor == "ai":
                version.submitted_for_review_at = None
            # A manual edit may invalidate the old AI claim-to-evidence mapping.
            if actor != "ai":
                version.citations = []
                version.knowledge_status = "insufficient_evidence"
                version.knowledge_limitations = (
                    "O conteúdo foi editado pelo instrutor; a fundamentação anterior "
                    "não foi revalidada para esta versão."
                )
            version.revision += 1
            version.updated_at = datetime.now(UTC)
            if commit:
                session.commit()
            else:
                session.flush()
        except Exception:
            session.rollback()
            raise
        session.refresh(version)
        return version

    def create_revision(
        self,
        session: Session,
        *,
        plan_id: UUID,
        version_number: int,
        data: TrainingPlanVersionInput,
        actor: str,
        expected_revision: int | None = None,
        origin: PlanOrigin = "instructor",
        commit: bool = True,
    ) -> TrainingPlanVersion:
        source = self._version(session, plan_id, version_number, lock=True)
        if source.status != "current":
            raise InvalidTrainingTransitionError
        if expected_revision is not None and source.revision != expected_revision:
            raise ConcurrentTrainingUpdateError
        self._lock_client(session, source.client_id)
        if self.find_proposal(session, client_id=source.client_id) is not None:
            raise ActiveTrainingProposalExistsError
        next_number = (
            session.scalar(
                select(func.max(TrainingPlanVersion.version_number)).where(
                    TrainingPlanVersion.plan_id == plan_id
                )
            )
            or 0
        ) + 1
        return self._new_version(
            session,
            plan_id,
            source.client_id,
            next_number,
            data,
            actor,
            origin,
            commit=commit,
            preserved=source,
        )

    def append_to_current(
        self,
        session: Session,
        *,
        version_id: UUID,
        expected_revision: int,
        current_version_id: UUID,
        expected_current_revision: int,
        selected_positions: list[int],
    ) -> TrainingPlanVersion:
        draft = session.get(TrainingPlanVersion, version_id)
        if draft is None:
            raise TrainingVersionNotFoundError
        self._lock_client(session, draft.client_id)
        draft = session.scalar(
            select(TrainingPlanVersion)
            .where(TrainingPlanVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if draft is None:
            raise TrainingVersionNotFoundError
        if draft.status != "proposal" or draft.submitted_for_review_at is None:
            raise InvalidTrainingTransitionError
        if draft.revision != expected_revision:
            raise ConcurrentTrainingUpdateError
        current = session.scalar(
            select(TrainingPlanVersion)
            .join(TrainingPlan)
            .where(
                TrainingPlanVersion.id == current_version_id,
                TrainingPlanVersion.client_id == draft.client_id,
                TrainingPlanVersion.status == "current",
                TrainingPlan.is_current,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None or current.revision != expected_current_revision:
            raise ConcurrentTrainingUpdateError
        adaptation = session.scalar(
            select(TrainingAdaptationProposal.id).where(
                TrainingAdaptationProposal.resulting_version_id == draft.id
            )
        )
        if draft.plan_id == current.plan_id or adaptation is not None:
            # Such drafts already contain the base plan; appending would duplicate it.
            raise InvalidTrainingTransitionError
        base = self.content(session, current)
        additions = self.content(session, draft)
        if (
            not selected_positions
            or len(set(selected_positions)) != len(selected_positions)
            or any(
                type(position) is not int or not 1 <= position <= len(additions.items)
                for position in selected_positions
            )
        ):
            raise InvalidTrainingContentError
        selected = [
            item
            for position, item in enumerate(additions.items, 1)
            if position in selected_positions
        ]
        try:
            merged = TrainingPlanVersionInput(
                name=base.name, objective=base.objective, items=[*base.items, *selected]
            )
        except ValidationError:
            raise InvalidTrainingContentError from None
        self.validate_equipment(session, merged, current)
        next_number = (
            session.scalar(
                select(func.max(TrainingPlanVersion.version_number)).where(
                    TrainingPlanVersion.plan_id == current.plan_id
                )
            )
            + 1
        )
        try:
            # A proposal is editable. Move this sole draft onto the current plan's
            # next version, keeping its stable review ID and all approved history.
            draft.plan_id = current.plan_id
            draft.version_number = next_number
            self._replace_content(session, draft, merged)
            draft.citations = []
            draft.knowledge_status = "insufficient_evidence"
            draft.knowledge_limitations = (
                "O instrutor incorporou os exercícios ao treino atual. A fundamentação da "
                "sugestão original não foi revalidada para a ficha combinada."
            )
            draft.revision += 1
            draft.updated_at = datetime.now(UTC)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return draft

    def approve(
        self,
        session: Session,
        *,
        plan_id: UUID,
        version_number: int,
        actor: str,
        expected_revision: int,
    ) -> TrainingPlanVersion:
        version = self._version(session, plan_id, version_number, lock=True)
        if version.status != "proposal":
            raise InvalidTrainingTransitionError
        if version.revision != expected_revision:
            raise ConcurrentTrainingUpdateError
        if version.submitted_for_review_at is None:
            raise InvalidTrainingTransitionError
        employee = session.scalar(
            select(Employee)
            .join(Account)
            .where(
                Account.keycloak_subject == actor,
                Account.account_active,
                Employee.active,
                Employee.specialization == "instructor",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if employee is None or employee.account.person_profile is None:
            raise InvalidTrainingTransitionError
        # Validate the complete persisted draft, not only the last patch.
        data = self.content(session, version)
        self.validate_equipment(session, data, version)
        source = session.scalar(
            select(TrainingAdaptationProposal)
            .where(
                TrainingAdaptationProposal.resulting_version_id == version.id,
                TrainingAdaptationProposal.status == "pending_instructor_review",
            )
            .with_for_update()
        )
        if source is not None:
            base = session.get(TrainingPlanVersion, source.base_version_id)
            if base is None or base.status != "current":
                raise ConcurrentTrainingUpdateError
        plan = session.scalar(
            select(TrainingPlan).where(TrainingPlan.id == plan_id).with_for_update()
        )
        if plan is None:
            raise TrainingVersionNotFoundError
        # Lock the client row so concurrent activations for distinct plans cannot
        # both pass the client-wide current-plan constraint.
        session.scalar(select(Client).where(Client.id == plan.client_id).with_for_update())
        current_plans = session.scalars(
            select(TrainingPlan)
            .where(TrainingPlan.client_id == plan.client_id, TrainingPlan.is_current)
            .with_for_update()
        ).all()
        current_versions = session.scalars(
            select(TrainingPlanVersion)
            .where(
                TrainingPlanVersion.plan_id.in_([item.id for item in current_plans]),
                TrainingPlanVersion.status == "current",
            )
            .with_for_update()
        ).all()
        try:
            for current in current_versions:
                current.status = "superseded"
            for current_plan in current_plans:
                current_plan.is_current = False
            session.flush()
            version.status = "current"
            version.approved_by = actor
            version.responsible_employee_id = employee.id
            version.responsible_name = employee.account.person_profile.full_name
            version.approved_at = datetime.now(UTC)
            version.revision += 1
            version.updated_at = version.approved_at
            plan.is_current = True
            if source is not None:
                source.status = "approved"
                source.instructor_id = actor
                source.instructor_reviewed_at = version.approved_at
            session.commit()
        except Exception:
            session.rollback()
            raise
        session.refresh(version)
        return version

    def _new_version(
        self,
        session: Session,
        plan_id: UUID,
        client_id: UUID,
        number: int,
        data: TrainingPlanVersionInput,
        actor: str,
        origin: PlanOrigin,
        *,
        commit: bool = True,
        preserved: TrainingPlanVersion | None = None,
        created_employee_id: UUID | None = None,
        knowledge: KnowledgeResult | None = None,
    ) -> TrainingPlanVersion:
        self.validate_equipment(session, data, preserved)
        version = TrainingPlanVersion(
            plan_id=plan_id,
            client_id=client_id,
            version_number=number,
            status="proposal",
            name=data.name.strip(),
            objective=data.objective.strip(),
            origin=origin,
            created_by=actor,
            submitted_for_review_at=datetime.now(UTC) if origin == "instructor" else None,
            created_employee_id=created_employee_id,
            citations=knowledge.citations if knowledge else [],
            knowledge_status=knowledge.knowledge_status if knowledge else "insufficient_evidence",
            knowledge_limitations=knowledge.knowledge_limitations if knowledge else "",
        )
        session.add(version)
        session.flush()
        self._replace_content(session, version, data)
        if commit:
            session.commit()
            session.refresh(version)
        return version

    def submit_for_review(
        self,
        session: Session,
        *,
        subject: str,
        version_id: UUID,
        expected_revision: int,
    ) -> TrainingPlanVersion:
        owned = session.scalar(
            select(TrainingPlanVersion)
            .join(Client, Client.id == TrainingPlanVersion.client_id)
            .join(Account, Account.id == Client.account_id)
            .where(
                TrainingPlanVersion.id == version_id,
                Account.keycloak_subject == subject,
                Account.account_active,
                Client.active,
            )
        )
        if owned is None:
            raise TrainingVersionNotFoundError
        version = self._version(session, owned.plan_id, owned.version_number, lock=True)
        if version.status != "proposal":
            raise InvalidTrainingTransitionError
        if version.revision != expected_revision:
            raise ConcurrentTrainingUpdateError
        if version.submitted_for_review_at is None:
            version.submitted_for_review_at = datetime.now(UTC)
            version.updated_at = version.submitted_for_review_at
            version.revision += 1
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise
        return version

    def _replace_content(
        self, session: Session, version: TrainingPlanVersion, data: TrainingPlanVersionInput
    ) -> None:
        version.name, version.objective = data.name.strip(), data.objective.strip()
        for item in session.scalars(
            select(TrainingPlanItem).where(TrainingPlanItem.version_id == version.id)
        ).all():
            session.delete(item)
        # Free the version/position unique slots before adding the replacement
        # items. Without this flush, a same-position replacement can be
        # inserted before SQLAlchemy emits the deletes.
        session.flush()
        for position, item in enumerate(data.items, start=1):
            session.add(
                TrainingPlanItem(version_id=version.id, position=position, **item.model_dump())
            )
        session.flush()

    @staticmethod
    def _version(
        session: Session, plan_id: UUID, number: int, *, lock: bool
    ) -> TrainingPlanVersion:
        statement = select(TrainingPlanVersion).where(
            TrainingPlanVersion.plan_id == plan_id, TrainingPlanVersion.version_number == number
        )
        if lock:
            client_id = session.scalar(
                select(TrainingPlan.client_id).where(TrainingPlan.id == plan_id)
            )
            if client_id is None:
                raise TrainingVersionNotFoundError
            TrainingLifecycleService._lock_client(session, client_id)
            statement = statement.with_for_update().execution_options(populate_existing=True)
        version = session.scalar(statement)
        if version is None:
            raise TrainingVersionNotFoundError
        return version

    @staticmethod
    def _lock_client(session: Session, client_id: UUID) -> None:
        client = session.scalar(select(Client).where(Client.id == client_id).with_for_update())
        if client is None:
            raise TrainingVersionNotFoundError

    @staticmethod
    def content(session: Session, version: TrainingPlanVersion) -> TrainingPlanVersionInput:
        try:
            return TrainingPlanVersionInput(
                name=version.name,
                objective=version.objective,
                items=[
                    TrainingPlanItemInput.model_validate(item, from_attributes=True)
                    for item in session.scalars(
                        select(TrainingPlanItem)
                        .where(TrainingPlanItem.version_id == version.id)
                        .order_by(TrainingPlanItem.position)
                    )
                ],
            )
        except ValidationError as error:
            raise InvalidTrainingContentError from error

    @staticmethod
    def validate_equipment(
        session: Session,
        data: TrainingPlanVersionInput,
        preserved: TrainingPlanVersion | None = None,
    ) -> None:
        # Only exact approved content is grandfathered, never a newly saved draft
        # or a whole model ID. Multiplicity prevents duplicating an exempt item.
        baseline = preserved
        if baseline is not None and baseline.status == "proposal":
            baseline = session.scalar(
                select(TrainingPlanVersion).where(
                    TrainingPlanVersion.plan_id == baseline.plan_id,
                    TrainingPlanVersion.status == "current",
                )
            )
        retained = (
            Counter(
                item.model_dump_json()
                for item in TrainingLifecycleService.content(session, baseline).items
            )
            if baseline is not None and baseline.status == "current"
            else Counter()
        )
        equipment = EquipmentService()
        references = {item.equipment_model_id for item in data.items if item.equipment_model_id}
        equipment.lock_models(session, references)
        usable = {
            model.id for model in equipment.usable_models_with_units(session, model_ids=references)
        }
        for item in data.items:
            signature = item.model_dump_json()
            if retained[signature]:
                retained[signature] -= 1
                continue
            if bool(item.equipment_requirement) != bool(item.equipment_model_id):
                raise InvalidTrainingContentError
            if item.equipment_model_id and item.equipment_model_id not in usable:
                raise InvalidTrainingContentError
