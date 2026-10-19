"""Client-scoped conversational support and explicitly requested proposal edits."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.integrations.ai import (
    AiProviderError,
    AiTrainingChatResponse,
    TrainingChatProvider,
    training_chat_provider_from_environment,
)
from app.integrations.ai_diagnostics import observe_turn, record_retry, record_turn
from app.modules.clients.models import Account, Client
from app.modules.equipment.service import EquipmentService
from app.modules.knowledge.service import KnowledgeCitationError, KnowledgeResult, KnowledgeService
from app.modules.onboarding.draft_service import OnboardingDraftService
from app.modules.onboarding.models import Onboarding
from app.modules.training.generation_service import (
    CompletedOnboardingRequiredError,
    InitialTrainingGenerationService,
    InvalidTrainingGenerationError,
    TrainingGenerationUnavailableError,
)
from app.modules.training.models import (
    TrainingAiConversation,
    TrainingAiMessage,
    TrainingPlan,
    TrainingPlanItem,
    TrainingPlanVersion,
)
from app.modules.training.presentation import proposal_preview
from app.modules.training.schema import TrainingPlanVersionInput
from app.modules.training.selection import (
    RedundantTrainingExerciseError,
    request_selected_training,
)
from app.modules.training.service import (
    ConcurrentTrainingUpdateError,
    ImmutableTrainingVersionError,
    InvalidTrainingContentError,
    TrainingLifecycleService,
)


class TrainingChatNotFoundError(Exception):
    pass


class TrainingChatUnavailableError(Exception):
    pass


class TrainingChatDraftUpdateError(Exception):
    """The provider proposed an invalid or stale change to the AI draft."""


@dataclass(frozen=True)
class TrainingChatMessage:
    role: str
    content: str
    created_at: datetime
    client_request_id: UUID | None
    reply_to_client_request_id: UUID | None
    adaptation_suggested: bool
    adaptation_reason: str | None
    citations: list[dict] = field(default_factory=list)
    knowledge_status: str = "insufficient_evidence"
    knowledge_limitations: str = ""


@dataclass(frozen=True)
class TrainingChatState:
    messages: list[TrainingChatMessage]


class TrainingChatService:
    """Client-scoped chat; the sole active proposal may be revised by the AI."""

    def __init__(
        self,
        provider: TrainingChatProvider | None = None,
        *,
        generation_service: InitialTrainingGenerationService | None = None,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._provider = provider or training_chat_provider_from_environment()
        self._generation = generation_service or InitialTrainingGenerationService()
        self._knowledge = knowledge_service or KnowledgeService()
        self._lifecycle = TrainingLifecycleService()
        self._recent_message_limit = int(os.environ.get("AI_RECENT_MESSAGE_LIMIT", "6"))
        self._summary_limit = int(os.environ.get("AI_TRAINING_CHAT_SUMMARY_LIMIT", "2000"))

    def state_for_subject(self, session: Session, subject: str) -> TrainingChatState:
        client_id = self._client_id(session, subject)
        self.purge_expired_content(session)
        conversation = self._conversation(session, client_id)
        return TrainingChatState(self._messages(session, conversation.id))

    @observe_turn("training_chat")
    def submit_for_subject(
        self, session: Session, subject: str, *, message: str, client_request_id: UUID
    ) -> TrainingChatState:
        client_id = self._client_id(session, subject)
        self.purge_expired_content(session)
        session.scalar(select(Client.id).where(Client.id == client_id).with_for_update())
        conversation = self._conversation(session, client_id, commit=False)
        reply = session.scalar(
            select(TrainingAiMessage).where(
                TrainingAiMessage.conversation_id == conversation.id,
                TrainingAiMessage.reply_to_client_request_id == client_request_id,
            )
        )
        if reply is not None:
            record_turn(outcome="cached", path="cached")
            return TrainingChatState(self._messages(session, conversation.id))

        user = session.scalar(
            select(TrainingAiMessage).where(
                TrainingAiMessage.conversation_id == conversation.id,
                TrainingAiMessage.client_request_id == client_request_id,
            )
        )
        if user is None:
            user = TrainingAiMessage(
                conversation_id=conversation.id,
                role="user",
                content=message,
                sequence=self._next(session, conversation.id),
                client_request_id=client_request_id,
            )
            session.add(user)
            conversation.raw_expires_at = self._expiry()
            session.flush()

        newer = session.scalar(
            select(TrainingAiMessage.id)
            .where(
                TrainingAiMessage.conversation_id == conversation.id,
                TrainingAiMessage.role == "user",
                TrainingAiMessage.sequence > user.sequence,
            )
            .limit(1)
        )
        if newer:
            raise ConcurrentTrainingUpdateError
        message = user.content
        context = self._context(session, client_id, conversation, message, user.id)
        editable_draft = self._editable_ai_draft(session, client_id)
        draft_revision = editable_draft.revision if editable_draft else None
        try:
            initial_reply = self._initial_plan_reply(session, subject, client_id, context)
            if initial_reply is not None:
                # This preview comes from validated domain content, not provider
                # prose; it is not subject to the writing adapter's text limit.
                response = AiTrainingChatResponse.model_construct(assistant_message=initial_reply)
                proposal = self._lifecycle.find_proposal(session, client_id=client_id)
                knowledge = KnowledgeResult(
                    list(proposal.citations) if proposal else [],
                    proposal.knowledge_status if proposal else "insufficient_evidence",
                    proposal.knowledge_limitations
                    if proposal
                    else (
                        "Esta mensagem orienta o fluxo; não fornece fundamentação para um treino."
                    ),
                )
            else:
                # Retrieval uses only this client's message and scoped plan context.
                evidence = self._knowledge.retrieve(session, client_id, message)
                context["knowledge"] = evidence.as_context()
                record_turn(path="model")
                try:
                    if context["rules"]["may_update_ai_draft"]:
                        response = request_selected_training(
                            lambda selected_context: self._retry(
                                lambda: self._provider.training_chat(selected_context)
                            ),
                            context,
                            plan_field="draft_update",
                        )
                    else:
                        response = self._retry(lambda: self._provider.training_chat(context))
                    knowledge = evidence.resolve_citations(
                        response.citations,
                        response.knowledge_status
                        if "knowledge_status" in response.model_fields_set
                        else None,
                    )
                except (
                    KnowledgeCitationError,
                    ValidationError,
                    RedundantTrainingExerciseError,
                ) as error:
                    record_turn(
                        reason=(
                            "invalid_training_schema"
                            if isinstance(error, ValidationError)
                            else "invalid_training_citations"
                            if isinstance(error, KnowledgeCitationError)
                            else "redundant_exercise_prescription"
                        )
                    )
                    raise TrainingChatDraftUpdateError from None
        except (TrainingChatUnavailableError, TrainingChatDraftUpdateError):
            session.commit()  # Preserve only the original client message for retry.
            raise
        content = response.assistant_message
        if response.draft_update is not None:
            if editable_draft is not None and context["rules"]["may_update_ai_draft"]:
                self._apply_draft_update(
                    session, editable_draft, response.draft_update, draft_revision
                )
                editable_draft.citations = list(knowledge.citations)
                editable_draft.knowledge_status = knowledge.knowledge_status
                editable_draft.knowledge_limitations = knowledge.knowledge_limitations
                record_turn(outcome="draft_saved")
                content = (
                    "Atualizei o rascunho conforme solicitado. "
                    "Confira as alterações abaixo ou em Meu treino. Quando estiver satisfeito, "
                    "use Enviar rascunho para minha revisão. "
                    "As alterações ainda dependem da aprovação do instrutor. "
                    "Seu plano atual não foi alterado."
                )
                content += "\n\n" + proposal_preview(session, editable_draft)
            else:
                record_turn(
                    outcome="draft_blocked",
                    reason="request_not_authorized" if editable_draft else "no_editable_draft",
                )
                content = (
                    "Não alterei nenhum plano. Diga qual mudança deseja fazer no rascunho."
                    if editable_draft
                    else "Não alterei nenhum plano: "
                    "não há um único rascunho disponível para edição. "
                    "Seu plano atual só pode mudar após revisão profissional."
                )
        elif initial_reply is None and self._claims_saved_change(content):
            record_turn(outcome="draft_blocked", reason="unsupported_save_claim")
            content = (
                "Nenhuma alteração foi salva no treino nesta mensagem. "
                "Diga qual mudança deseja fazer no rascunho para eu ajudar."
            )
        elif (
            initial_reply is None
            and context["current_training_plan"] is None
            and self._offers_initial_plan(content)
        ):
            # Ground an offer in real capabilities; the next confirmation is
            # handled by the backend, never sent back to the model to ask again.
            content = self._initial_plan_guidance(context)
        can_suggest_adaptation = context["current_training_plan"] is not None
        assistant = TrainingAiMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            sequence=self._next(session, conversation.id),
            reply_to_client_request_id=client_request_id,
            adaptation_suggested=response.adaptation_suggested and can_suggest_adaptation,
            adaptation_reason=response.adaptation_reason
            if response.adaptation_suggested and can_suggest_adaptation
            else None,
            citations=knowledge.citations,
            knowledge_status=knowledge.knowledge_status,
            knowledge_limitations=knowledge.knowledge_limitations,
        )
        session.add(assistant)
        conversation.raw_expires_at = self._expiry()
        session.flush()
        conversation.summary = self._bounded_summary(session, conversation.id)
        session.commit()
        return TrainingChatState(self._messages(session, conversation.id))

    def purge_expired_content(self, session: Session, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        affected = session.scalars(
            select(TrainingAiMessage.conversation_id)
            .where(TrainingAiMessage.created_at <= current_time - timedelta(days=30))
            .distinct()
        ).all()
        if affected:
            session.execute(
                update(TrainingAiConversation)
                .where(TrainingAiConversation.id.in_(affected))
                .values(summary=None)
            )
        deleted = session.execute(
            delete(TrainingAiMessage).where(
                TrainingAiMessage.created_at <= current_time - timedelta(days=30)
            )
        ).rowcount
        expired_summaries = session.scalars(
            select(TrainingAiConversation).where(
                TrainingAiConversation.raw_expires_at.is_not(None),
                TrainingAiConversation.raw_expires_at <= current_time,
            )
        ).all()
        if expired_summaries:
            ids = [conversation.id for conversation in expired_summaries]
            session.execute(
                update(TrainingAiConversation)
                .where(TrainingAiConversation.id.in_(ids))
                .values(summary=None, raw_expires_at=None)
            )
        if deleted or expired_summaries:
            session.commit()
        return deleted or 0

    def _context(
        self,
        session: Session,
        client_id: UUID,
        conversation: TrainingAiConversation,
        message: str,
        message_id: UUID,
    ) -> dict[str, object]:
        history = self._messages(session, conversation.id, message_id)[
            -self._recent_message_limit :
        ]
        current_plan = self._current_plan(session, client_id)
        draft = self._editable_ai_draft(session, client_id)
        draft_content = self._draft_context(session, draft) if draft else None
        may_update = draft_content is not None and self._requests_draft_change(
            message, history, [item["exercise_name"] for item in draft_content["items"]]
        )
        health_context = " ".join(
            [*(item.content for item in history if item.role == "user"), message]
        )
        return {
            "current_user_message": message,
            "conversation_summary": self._bounded_summary(session, conversation.id, message_id),
            "recent_messages": [{"role": item.role, "content": item.content} for item in history],
            "current_training_plan": current_plan,
            "active_equipment_models": EquipmentService().training_context(session)
            if draft
            else [],
            "editable_training_draft": draft_content,
            "relevant_onboarding": self._onboarding_context(session, client_id, health_context),
            "onboarding_completed": OnboardingDraftService().has_valid_completed_onboarding(
                session, client_id
            ),
            "rules": {
                "language": "pt-BR",
                "must_not_diagnose": True,
                "must_not_mutate_current_or_approved_training_plan": True,
                "may_suggest_adaptation": current_plan is not None,
                "may_update_ai_draft": may_update,
                "client_reports_are_not_completed_onboarding_edits": True,
                "summary_contains_only_client_statements": True,
                "initial_generation_requires_explicit_request": True,
            },
        }

    def _initial_plan_reply(
        self, session: Session, subject: str, client_id: UUID, context: dict
    ) -> str | None:
        message = context["current_user_message"]
        exercise_request = self._requests_exercise_suggestion(message)
        if not exercise_request and not self._requests_initial_plan(
            message, context["recent_messages"]
        ):
            return None
        record_turn(path="direct")
        existing = self._lifecycle.find_proposal(session, client_id=client_id)
        detailed = exercise_request or bool(
            re.search(
                r"\b(?:para|objetivo|muscular|dias|corpo|somente|apenas)\b",
                self._normalized(message),
            )
        )
        # Request UUIDs handle transport retries in submit_for_subject. Repeated
        # text can be a fresh instruction or follow a failed generation, so it
        # cannot establish that the saved draft fulfills the current request.
        if existing is not None and not detailed:
            return (
                "Seu rascunho já está disponível em Meu treino. "
                "Você pode pedir uma alteração nesse rascunho. Quando estiver satisfeito, "
                "use Enviar rascunho para minha revisão."
                "\n\n" + proposal_preview(session, existing)
            )
        if not context["onboarding_completed"]:
            return self._initial_plan_guidance(context)
        try:
            # Keep the proposal, reply and request UUID atomic. A failed
            # generation rolls back only its savepoint, preserving the message.
            with session.begin_nested():
                proposal = self._generation.generate_for_subject(
                    session,
                    subject,
                    commit=False,
                    training_request=message,
                    replace_existing=existing is not None,
                )
        except CompletedOnboardingRequiredError:
            return "Revise e conclua seu onboarding antes de gerar o rascunho de treino."
        except TrainingGenerationUnavailableError:
            raise TrainingChatUnavailableError from None
        except InvalidTrainingGenerationError:
            raise TrainingChatDraftUpdateError from None
        record_turn(outcome="draft_saved")
        return (
            "Criei seu rascunho de treino com base no onboarding concluído. "
            "Confira a ficha abaixo ou em Meu treino. Quando estiver satisfeito, "
            "use Enviar rascunho para minha revisão. Ela ainda precisa da aprovação "
            "profissional antes de se tornar seu plano atual."
            "\n\n" + proposal_preview(session, proposal)
        )

    @staticmethod
    def _initial_plan_guidance(context: dict) -> str:
        if context["editable_training_draft"] is not None:
            return (
                "Seu rascunho já está disponível em Meu treino. "
                "Você pode pedir uma alteração nesse rascunho ou, quando estiver satisfeito, "
                "usar Enviar rascunho para minha revisão."
            )
        if not context["onboarding_completed"]:
            return "Revise e conclua seu onboarding antes de gerar o rascunho de treino."
        return (
            "Posso gerar seu rascunho inicial com base no onboarding concluído, "
            "para revisão do instrutor. Quer que eu prepare seu rascunho de treino?"
        )

    @classmethod
    def _offers_initial_plan(cls, message: str) -> bool:
        text = cls._normalized(message)
        return bool(
            re.search(r"\b(?:prepar\w*|gerar|gere|montar|monte|criar|crie|elabor\w*)\b", text)
            and re.search(r"\b(?:plano|treino|rascunho|ficha|proposta)\b", text)
            and re.search(r"\b(?:quer|quero|deseja|gostaria|posso|vou|vamos)\b", text)
        )

    @classmethod
    def _requests_exercise_suggestion(cls, message: str) -> bool:
        text = cls._normalized(message).strip()
        text = re.sub(r"^(?:ola[!,. ]+|por favor[, ]+)", "", text)
        if re.search(r"\bnao (?:quero|sugira|recomende|gere|crie)\b|\bevitar\b", text):
            return False
        return bool(
            re.match(r"(?:que|quais)(?: sao os)? exercicios?\b", text)
            and re.search(
                r"\b(?:posso fazer|recomenda|sugere|para|ganho|ganhar|hipertrofia)\b", text
            )
            or re.match(r"(?:sugira|recomende|indique)\b.*\b(?:exercicios|treino|ficha)\b", text)
            or re.match(r"como (?:posso )?treinar\b", text)
            or re.match(r"(?:exercicios|treino|ficha) (?:para|de)\b", text)
            or re.match(
                r"(?:quero|preciso de|gostaria de) (?:um |uma )?(?:exercicios|treino|ficha)\b",
                text,
            )
            or re.match(
                r"(?:pode|poderia) (?:me )?(?:sugerir|recomendar|indicar|montar) "
                r"(?:(?:um|uma|alguns|algumas|os|as|meu|minha) )*"
                r"(?:exercicios|treino|ficha)\b",
                text,
            )
        )

    @classmethod
    def _requests_new_plan(cls, message: str) -> bool:
        text = cls._normalized(message)
        return cls._requests_initial_plan(message, []) and bool(
            re.search(
                r"\b(?:sugestao de treino|novo (?:treino|plano)|"
                r"(?:treino|plano) novo|corpo inteiro|todo o corpo|full body)\b",
                text,
            )
        )

    @classmethod
    def _requests_initial_plan(cls, message: str, history: list[dict]) -> bool:
        text = cls._normalized(message).strip()
        # Full matches intentionally exclude conditions, negation, health
        # corrections and ambiguous compound answers from consent.
        if re.fullmatch(
            r"(?:sim(?:[,!]\s*|\s+))?(?:sim|quero|pode|pode sim|confirmo|"
            r"pode fazer|pode preparar|pode gerar|pode criar|pode montar)"
            r"(?:[, ]+por favor)?[.!]*",
            text,
        ):
            questions = re.findall(r"[^.!?]*\?", history[-1]["content"]) if history else []
            return bool(
                history
                and history[-1]["role"] == "assistant"
                and len(questions) == 1
                and cls._offers_initial_plan(questions[0])
                and not re.search(r"\bnao\b", cls._normalized(questions[0]))
            )
        # Detailed requests can include a goal, frequency and division. They are
        # still explicit generation requests, not generic chat about an old exercise.
        if re.search(
            r"\b(?:se|caso|desde que|antes|depois|quando)\b|"
            r"\bnao (?:gere|crie|monte|prepare|agora)\b",
            text,
        ):
            return False
        return bool(
            re.match(
                r"(?:por favor[, ]+)?(?:quero que (?:voce )?|"
                r"(?:pode|poderia|quero|gostaria de) )?"
                r"(?:prepare|preparar|gere|gerar|monte|montar|crie|criar|elabore|elaborar) "
                r"(?:(?:um|uma|o|meu|novo|primeiro|seu) )*"
                r"(?:sugestao de treino|plano(?: de treino)?|treino|"
                r"rascunho(?: de treino)?|ficha)\b",
                text,
            )
        )

    @staticmethod
    def _editable_ai_draft(session: Session, client_id: UUID) -> TrainingPlanVersion | None:
        drafts = session.scalars(
            select(TrainingPlanVersion)
            .where(
                TrainingPlanVersion.client_id == client_id,
                TrainingPlanVersion.status == "proposal",
            )
            .order_by(TrainingPlanVersion.created_at.desc())
        ).all()
        # Do not silently choose between legacy duplicate drafts.
        return drafts[0] if len(drafts) == 1 else None

    @staticmethod
    def _draft_context(session: Session, version: TrainingPlanVersion) -> dict[str, object]:
        return {
            "name": version.name,
            "objective": version.objective,
            "items": [
                {
                    "exercise_name": item.exercise_name,
                    "sets": item.sets,
                    "repetitions": item.repetitions,
                    "load_guidance": item.load_guidance,
                    "rest_seconds": item.rest_seconds,
                    "equipment_requirement": item.equipment_requirement,
                    "equipment_model_id": str(item.equipment_model_id)
                    if item.equipment_model_id
                    else None,
                }
                for item in session.scalars(
                    select(TrainingPlanItem)
                    .where(TrainingPlanItem.version_id == version.id)
                    .order_by(TrainingPlanItem.position)
                )
            ],
        }

    def _apply_draft_update(
        self,
        session: Session,
        version: TrainingPlanVersion,
        update: dict[str, object],
        expected_revision: int,
    ) -> None:
        try:
            data = TrainingPlanVersionInput.model_validate(update)
            self._lifecycle.revise(
                session,
                plan_id=version.plan_id,
                version_number=version.version_number,
                data=data,
                actor="ai",
                expected_revision=expected_revision,
                commit=False,
            )
        except ImmutableTrainingVersionError:
            raise ConcurrentTrainingUpdateError from None
        except (ValidationError, InvalidTrainingContentError) as error:
            record_turn(
                reason=(
                    "invalid_training_schema"
                    if isinstance(error, ValidationError)
                    else "invalid_training_equipment"
                )
            )
            raise TrainingChatDraftUpdateError from None

    def _current_plan(self, session: Session, client_id: UUID) -> dict[str, object] | None:
        version = session.scalar(
            select(TrainingPlanVersion)
            .join(TrainingPlan, TrainingPlanVersion.plan_id == TrainingPlan.id)
            .where(
                TrainingPlan.client_id == client_id,
                TrainingPlan.is_current,
                TrainingPlanVersion.status == "current",
            )
        )
        if version is None:
            return None
        return {
            "name": version.name,
            "objective": version.objective,
            "items": [
                {
                    "exercise_name": item.exercise_name,
                    "sets": item.sets,
                    "repetitions": item.repetitions,
                    "load_guidance": item.load_guidance,
                    "rest_seconds": item.rest_seconds,
                }
                for item in session.scalars(
                    select(TrainingPlanItem)
                    .where(TrainingPlanItem.version_id == version.id)
                    .order_by(TrainingPlanItem.position)
                )
            ],
        }

    @staticmethod
    def _onboarding_context(session: Session, client_id: UUID, message: str) -> dict[str, object]:
        onboarding = session.scalar(select(Onboarding).where(Onboarding.client_id == client_id))
        if onboarding is None or onboarding.status != "completed":
            return {}
        context: dict[str, object] = {
            "training_goal": onboarding.training_goal,
            "training_experience": onboarding.training_experience,
        }
        health_terms = (
            "dor",
            "lesao",
            "limit",
            "queixa",
            "medica",
            "remedio",
            "saude",
            "condic",
            "desconfort",
            "incomoda",
        )
        if any(term in TrainingChatService._normalized(message) for term in health_terms):
            context.update(
                {
                    "limitations_or_complaints": onboarding.limitations_or_complaints,
                    "medications": onboarding.medications,
                    "health_conditions": onboarding.health_conditions,
                }
            )
        return {key: value for key, value in context.items() if value is not None}

    def _bounded_summary(
        self, session: Session, conversation_id: UUID, exclude: UUID | None = None
    ) -> str | None:
        # Rebuild from retained sources, never from the previous generated summary.
        older = self._messages(session, conversation_id, exclude)[: -self._recent_message_limit]
        statements = []
        for item in reversed(older):
            if item.role != "user":
                continue
            entry = {"reported_at": item.created_at.isoformat(), "client_statement": item.content}
            candidate = [entry, *statements]
            if len(json.dumps(candidate, ensure_ascii=False)) > self._summary_limit:
                break  # Never cut a correction/negation midway or restore older stale facts.
            statements = candidate
        return json.dumps(statements, ensure_ascii=False) if statements else None

    @staticmethod
    def _normalized(text: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFKD", text.lower())
            if not unicodedata.combining(char)
        )

    @classmethod
    def _requests_draft_change(
        cls, message: str, history: list[TrainingChatMessage], exercise_names: list[str]
    ) -> bool:
        text = cls._normalized(message).strip()
        if re.search(r"\bnao (?:quero|precisa|altere|mude|troque|atualize|modifique)\b", text):
            return False
        if re.match(
            r"(?:como|por que|qual|o que|sera que|vale a pena|explique|devo|posso|seria)\b", text
        ):
            return False
        action = (
            r"\b(?:alter(?:e|ar)|mud(?:e|ar)|tro(?:que|car)|substitu(?:a|ir)|"
            r"atualiz(?:e|ar)|ajust(?:e|ar)|reduz(?:a|ir)|aument(?:e|ar)|"
            r"remov(?:a|er)|inclu(?:a|ir)|adicion(?:e|ar))\b"
        )
        target = r"\b(?:rascunho|treino|plano|ficha|exercicio|series?|repeticoes|carga|descanso)\b"
        names_targeted = any(cls._normalized(name) in text for name in exercise_names)
        request = re.search(r"\b(?:quero|gostaria de|preciso que|pode|poderia)\b", text)
        imperative = re.search(
            r"(?:^|[,;.!]\s*)(?:por favor[,]?\s+)?"
            r"(?:altere|mude|troque|substitua|atualize|ajuste|reduza|aumente|remova|inclua|adicione)\b",
            text,
        )
        informational = re.search(r"\b(?:saber|entender|explicar|opiniao)\b", text)
        if (
            re.search(action, text)
            and (re.search(target, text) or names_targeted)
            and (request or imperative)
            and not informational
        ):
            return True
        if re.fullmatch(r"(?:sim|pode|pode sim|confirmo|pode fazer)[.!]?", text) and history:
            previous = history[-1]
            proposal = cls._normalized(previous.content)
            return (
                previous.role == "assistant"
                and "?" in proposal
                and "rascunho" in proposal
                and bool(re.search(action, proposal))
            )
        return False

    @classmethod
    def _claims_saved_change(cls, message: str) -> bool:
        text = cls._normalized(message)
        return bool(
            re.search(
                r"\b(?:atualizei|alterei|salvei|modifiquei|troquei|substitui|aprovei|ativei|"
                r"criei|gerei|preparei|montei)\b",
                text,
            )
        ) or bool(
            re.search(
                r"\b(?:plano|treino|rascunho|ficha)\b.{0,60}\b(?:foi|esta) "
                r"(?:atualizad|alterad|aprovad|ativad|salv)",
                text,
            )
        )

    @staticmethod
    def _client_id(session: Session, subject: str) -> UUID:
        client_id = session.scalar(
            select(Client.id)
            .join(Account, Client.account_id == Account.id)
            .where(
                Account.keycloak_subject == subject, Account.account_active, Client.active.is_(True)
            )
        )
        if client_id is None:
            raise TrainingChatNotFoundError
        return client_id

    @staticmethod
    def _conversation(
        session: Session, client_id: UUID, *, commit: bool = True
    ) -> TrainingAiConversation:
        conversation = session.scalar(
            select(TrainingAiConversation).where(TrainingAiConversation.client_id == client_id)
        )
        if conversation is None:
            conversation = TrainingAiConversation(client_id=client_id)
            session.add(conversation)
            session.flush()
            if commit:
                session.commit()
        return conversation

    @staticmethod
    def _retry(operation):
        for attempt in range(2):
            try:
                return operation()
            except AiProviderError as error:
                record_retry(error.category, not attempt and error.retryable)
                if attempt or not error.retryable:
                    raise TrainingChatUnavailableError from None
        raise TrainingChatUnavailableError

    @staticmethod
    def _expiry() -> datetime:
        return datetime.now(UTC) + timedelta(days=30)

    @staticmethod
    def _next(session: Session, conversation_id: UUID) -> int:
        return (
            session.scalar(
                select(func.max(TrainingAiMessage.sequence)).where(
                    TrainingAiMessage.conversation_id == conversation_id
                )
            )
            or 0
        ) + 1

    @staticmethod
    def _messages(
        session: Session, conversation_id: UUID, exclude: UUID | None = None
    ) -> list[TrainingChatMessage]:
        statement = select(TrainingAiMessage).where(
            TrainingAiMessage.conversation_id == conversation_id
        )
        if exclude is not None:
            statement = statement.where(TrainingAiMessage.id != exclude)
        return [
            TrainingChatMessage(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                client_request_id=message.client_request_id,
                reply_to_client_request_id=message.reply_to_client_request_id,
                adaptation_suggested=message.adaptation_suggested,
                adaptation_reason=message.adaptation_reason,
                citations=message.citations,
                knowledge_status=message.knowledge_status,
                knowledge_limitations=message.knowledge_limitations,
            )
            for message in session.scalars(statement.order_by(TrainingAiMessage.sequence)).all()
        ]
