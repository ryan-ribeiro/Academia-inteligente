"""Operational diagnostics must not turn sensitive AI context into technical logs."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from urllib.error import URLError

import pytest
from test_onboarding_conversations import database_session as database_session
from test_onboarding_direct_answers import interview, send
from test_openai_onboarding_adapter import ollama_response

from app.integrations import ai
from app.integrations.ai import AiProviderError, OllamaConfig, OllamaOnboardingProvider
from app.integrations.ai_diagnostics import observe_turn, record_retry, record_turn
from app.modules.onboarding.conversation_service import AiConversationUnavailableError


def events(caplog):
    return [
        json.loads(record.message) for record in caplog.records if record.name == "uvicorn.error.ai"
    ]


def test_onboarding_logs_fast_path_rejection_fallback_and_cached_replay(database_session, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    service, _, scope, _ = interview(database_session)
    from uuid import uuid4

    request_id = uuid4()
    send(database_session, service, scope, "80 ou 82 kg", request_id)
    send(database_session, service, scope, "80 ou 82 kg", request_id)
    send(database_session, service, scope, "Não lembro")
    send(database_session, service, scope, "eu tenho 82 kilos")
    items = events(caplog)
    assert [item["outcome"] for item in items] == [
        "clarification",
        "cached",
        "clarification",
        "ready",
    ]
    assert items[0]["reason"] == "multiple_measurements"
    assert items[2]["fallback"] is True
    assert items[-1]["path"] == "direct" and items[-1]["accepted_count"] == 1
    assert all(item["duration_ms"] >= 0 for item in items)
    assert "eu tenho" not in caplog.text and str(scope.client_id) not in caplog.text
    assert "ada@example.test" not in caplog.text and str(request_id) not in caplog.text


def test_provider_payload_tokens_and_errors_are_not_logged(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    secret = "DO_NOT_LOG_medical_answer_email_token"
    provider = OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "qwen3:8b", 120))
    monkeypatch.setattr(
        ai,
        "urlopen",
        lambda request, timeout: BytesIO(ollama_response({"assistant_message": secret})),
    )
    provider.training_chat({"current_user_message": secret, "Authorization": secret})

    def fail(request, timeout):
        raise URLError(secret)

    monkeypatch.setattr(ai, "urlopen", fail)
    with pytest.raises(AiProviderError):
        provider.training_chat({"current_user_message": secret})
    items = events(caplog)
    assert items[0]["event"] == "ai_provider_call" and items[0]["operation"] == "training_chat"
    assert items[0]["provider"] == "ollama" and items[0]["outcome"] == "success"
    assert items[1]["outcome"] == "failure" and items[1]["reason"] == "timeout_or_network"
    assert secret not in caplog.text
    assert all(
        set(item) == {"event", "operation", "provider", "outcome", "reason", "duration_ms"}
        for item in items
    )


def test_training_focus_is_classified_without_logging_the_request(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    provider = OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "local-writer", 120))
    monkeypatch.setattr(
        ai,
        "urlopen",
        lambda request, timeout: BytesIO(
            ollama_response({"scope": "targeted", "muscle_groups": ["bíceps"], "goal": None})
        ),
    )
    provider.analyze_training_request({"training_request": "private-client-request"})
    assert events(caplog)[0]["operation"] == "training_generation"
    assert "private-client-request" not in caplog.text and "bíceps" not in caplog.text


def test_failed_turn_exposes_category_and_retry_count_not_exception_text(database_session, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    service, _, scope, provider = interview(database_session)

    def fail(context):
        raise AiProviderError("timeout_or_network", retryable=True)

    provider.extract_onboarding = fail
    with pytest.raises(AiConversationUnavailableError):
        send(database_session, service, scope, "Preciso explicar uma informação privada")
    item = events(caplog)[-1]
    assert item["outcome"] == "provider_failure" and item["retry_count"] == 1
    assert item["reason"] == "timeout_or_network" and item["path"] == "model"
    assert "informação privada" not in caplog.text


def test_diagnostic_contexts_are_isolated_and_unknown_metadata_is_discarded(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    barrier = Barrier(2)

    @observe_turn("training_chat")
    def turn(index):
        record_turn(path="direct" if index else "model", reason="SENSITIVE" if index else "none")
        if index:
            record_retry("timeout_or_network", True)
        barrier.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(turn, range(2)))
    by_path = {item["path"]: item for item in events(caplog)}
    assert by_path["direct"]["retry_count"] == 1
    assert by_path["model"]["retry_count"] == 0 and by_path["model"]["reason"] == "none"
    assert "SENSITIVE" not in caplog.text
    record_turn(reason="unsupported_answer")  # Outside a turn is harmless and produces no event.
    assert len(events(caplog)) == 2
