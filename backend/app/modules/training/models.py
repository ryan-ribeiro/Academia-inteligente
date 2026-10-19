"""Immutable, client-owned training plan and version persistence."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrainingKnowledgeEvidence:
    """Validated snapshot belongs to its client-owned message/proposal/version."""

    citations: Mapped[list[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list,
        server_default="[]",
    )
    knowledge_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="insufficient_evidence",
        server_default="insufficient_evidence",
    )
    knowledge_limitations: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )


class TrainingPlan(Base):
    __tablename__ = "training_plan"
    __table_args__ = (
        Index(
            "uq_client_current_training_plan",
            "client_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client.id"), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainingPlanVersion(TrainingKnowledgeEvidence, Base):
    __tablename__ = "training_plan_version"
    __table_args__ = (
        Index(
            "uq_client_training_plan_proposal",
            "client_id",
            unique=True,
            postgresql_where=text("status = 'proposal'"),
            sqlite_where=text("status = 'proposal'"),
        ),
        Index(
            "uq_training_plan_current_version",
            "plan_id",
            unique=True,
            postgresql_where=text("status = 'current'"),
            sqlite_where=text("status = 'current'"),
        ),
        UniqueConstraint("plan_id", "version_number", name="uq_training_plan_version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("training_plan.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposal")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_employee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("employee.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by: Mapped[str | None] = mapped_column(String(255))
    responsible_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee.id")
    )
    responsible_name: Mapped[str | None] = mapped_column(String(301))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_for_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TrainingPlanItem(Base):
    __tablename__ = "training_plan_item"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_training_plan_item_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_plan_version.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sets: Mapped[int] = mapped_column(Integer, nullable=False)
    repetitions: Mapped[str] = mapped_column(String(100), nullable=False)
    load_guidance: Mapped[str] = mapped_column(String(500), nullable=False)
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    equipment_requirement: Mapped[str | None] = mapped_column(String(200))
    equipment_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("equipment_model.id")
    )


class TrainingAiConversation(Base):
    """Client-owned raw training-chat context with independently bounded retention."""

    __tablename__ = "training_ai_conversation"
    __table_args__ = (Index("ix_training_ai_conversation_raw_expires_at", "raw_expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("client.id"), unique=True, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)
    raw_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TrainingAiMessage(TrainingKnowledgeEvidence, Base):
    """Sensitive client/assistant message retained only for the approved window."""

    __tablename__ = "training_ai_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_training_ai_message_sequence"),
        UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_training_ai_message_request"
        ),
        UniqueConstraint(
            "conversation_id",
            "reply_to_client_request_id",
            name="uq_training_ai_message_reply",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_ai_conversation.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reply_to_client_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    adaptation_suggested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    adaptation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainingAdaptationProposal(TrainingKnowledgeEvidence, Base):
    __tablename__ = "training_adaptation_proposal"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "base_version_id", "client_request_id", name="uq_adaptation_request"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("client.id"), nullable=False)
    base_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_plan_version.id"), nullable=False
    )
    source_client_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    client_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    client_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instructor_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instructor_id: Mapped[str | None] = mapped_column(String(255))
    resulting_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("training_plan_version.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TrainingAdaptationOperation(Base):
    __tablename__ = "training_adaptation_operation"
    __table_args__ = (
        UniqueConstraint("proposal_id", "position", name="uq_adaptation_operation_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_adaptation_proposal.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_position: Mapped[int | None] = mapped_column(Integer)
    exercise_name: Mapped[str | None] = mapped_column(String(200))
    sets: Mapped[int | None] = mapped_column(Integer)
    repetitions: Mapped[str | None] = mapped_column(String(100))
    load_guidance: Mapped[str | None] = mapped_column(String(500))
    rest_seconds: Mapped[int | None] = mapped_column(Integer)
    equipment_requirement: Mapped[str | None] = mapped_column(String(200))
    equipment_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("equipment_model.id")
    )
    is_existing_exercise: Mapped[bool | None] = mapped_column(Boolean)
