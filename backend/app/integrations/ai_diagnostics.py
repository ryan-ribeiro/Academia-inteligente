"""Allowlisted AI operational metadata; never log prompts, identities or answers."""

import json
import logging
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

# Inherit the application's existing console configuration under Uvicorn.
logger = logging.getLogger("uvicorn.error.ai")
_turn: ContextVar[dict | None] = ContextVar("ai_turn_diagnostic", default=None)
_OUTCOMES = {
    "answered",
    "ready",
    "clarification",
    "cached",
    "provider_failure",
    "conflict",
    "unavailable",
    "unexpected_error",
    "draft_saved",
    "draft_blocked",
}
_REASONS = {
    "none",
    "unsupported_answer",
    "invalid_measurement",
    "multiple_measurements",
    "uncertain_answer",
    "conflicting_answer",
    "correction_target_unknown",
    "invalid_extraction",
    "timeout_or_network",
    "malformed_structured_output",
    "provider_server",
    "configuration",
    "confirmation_declined",
    "request_not_authorized",
    "no_editable_draft",
    "unsupported_save_claim",
    "unclassified",
    "invalid_training_focus",
    "redundant_exercise_prescription",
    "invalid_training_schema",
    "invalid_training_citations",
    "invalid_training_equipment",
    "incomplete_training_plan",
}
_PATHS = {"none", "model", "direct", "confirmation", "cached"}
_OPERATIONS = {"onboarding", "training_chat", "training_generation", "training_adaptation"}


def _allowed(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def record_turn(*, outcome=None, path=None, reason=None, accepted_count=None, fallback=None):
    current = _turn.get()
    if current is None:
        return
    for name, value, choices, default in (
        ("outcome", outcome, _OUTCOMES, "unexpected_error"),
        ("path", path, _PATHS, "none"),
        ("reason", reason, _REASONS, "unclassified"),
    ):
        if value is not None:
            current[name] = _allowed(value, choices, default)
    if type(accepted_count) is int:
        current["accepted_count"] = min(10, max(0, accepted_count))
    if type(fallback) is bool:
        current["fallback"] = fallback


def record_retry(reason: str, will_retry: bool):
    record_turn(reason=reason)
    current = _turn.get()
    if current is not None and will_retry:
        current["retry_count"] += 1


def observe_turn(operation: str):
    def decorate(function):
        @wraps(function)
        def observed(*args, **kwargs):
            started = perf_counter()
            metadata = {
                "event": "ai_turn",
                "operation": _allowed(operation, _OPERATIONS, "unknown"),
                "outcome": "answered",
                "path": "none",
                "reason": "none",
                "retry_count": 0,
            }
            token = _turn.set(metadata)
            try:
                return function(*args, **kwargs)
            except Exception as error:
                metadata["outcome"] = {
                    "AiConversationUnavailableError": "provider_failure",
                    "TrainingChatUnavailableError": "provider_failure",
                    "OnboardingNotEditableError": "conflict",
                    "ConcurrentTrainingUpdateError": "conflict",
                    "TrainingChatDraftUpdateError": "draft_blocked",
                    "TrainingChatNotFoundError": "unavailable",
                }.get(type(error).__name__, "unexpected_error")
                raise
            finally:
                metadata["duration_ms"] = round((perf_counter() - started) * 1000, 2)
                logger.info(json.dumps(metadata, separators=(",", ":")))
                _turn.reset(token)

        return observed

    return decorate


def observe_provider_call(function):
    @wraps(function)
    def observed(provider, context, instructions, schema, response_type):
        started = perf_counter()
        metadata = {
            "event": "ai_provider_call",
            "operation": {
                "AiOnboardingExtractionResponse": "onboarding",
                "AiInterviewTurnResponse": "onboarding",
                "AiTrainingChatResponse": "training_chat",
                "AiTrainingGenerationResponse": "training_generation",
                "AiTrainingRequestFocus": "training_generation",
                "AiTrainingPlanAssessment": "training_generation",
                "AiTrainingAdaptationResponse": "training_adaptation",
            }.get(response_type.__name__, "unknown"),
            "provider": {
                "OllamaOnboardingProvider": "ollama",
                "OpenAiResponsesOnboardingProvider": "openai",
            }.get(type(provider).__name__, "unknown"),
            "outcome": "success",
            "reason": "none",
        }
        try:
            return function(provider, context, instructions, schema, response_type)
        except Exception as error:
            metadata["outcome"] = "failure"
            metadata["reason"] = _allowed(
                getattr(error, "category", None), _REASONS, "unclassified"
            )
            raise
        finally:
            metadata["duration_ms"] = round((perf_counter() - started) * 1000, 2)
            logger.info(json.dumps(metadata, separators=(",", ":")))

    return observed
