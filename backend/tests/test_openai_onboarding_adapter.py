import json
from io import BytesIO

import pytest

from app.integrations import ai
from app.integrations.ai import (
    AiProviderError,
    OllamaConfig,
    OllamaOnboardingProvider,
    OpenAiConfig,
    OpenAiResponsesOnboardingProvider,
    onboarding_ai_provider_from_environment,
    training_adaptation_provider_from_environment,
    training_chat_provider_from_environment,
)


def openai_response(payload: dict[str, object]) -> bytes:
    return json.dumps(
        {"output": [{"content": [{"type": "output_text", "text": json.dumps(payload)}]}]}
    ).encode()


def ollama_response(payload: dict[str, object]) -> bytes:
    return json.dumps({"message": {"content": json.dumps(payload)}}).encode()


def test_openai_interview_uses_configured_model_and_small_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setattr(
        ai,
        "urlopen",
        lambda request, timeout: (
            captured.append((request, timeout))
            or BytesIO(
                openai_response(
                    {"assistant_message": "Qual é seu objetivo?", "interview_status": "in_progress"}
                )
            )
        ),
    )
    provider = OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "gpt-5.6-luna", 10))
    result = provider.interview_turn({"current_user_message": "Olá"})
    assert result.interview_status == "in_progress"
    assert json.loads(captured[0][0].data)["model"] == "gpt-5.6-luna"


def test_openai_final_extraction_uses_shared_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "training_goal": "Força",
        "training_experience": "beginner",
        "height_cm": 170,
        "weight_kg": 70,
        "has_limitations_or_complaints": False,
        "limitations_or_complaints": None,
        "uses_medications": False,
        "medications": None,
        "has_health_conditions": False,
        "health_conditions": None,
    }
    monkeypatch.setattr(
        ai, "urlopen", lambda request, timeout: BytesIO(openai_response({"onboarding": data}))
    )
    result = OpenAiResponsesOnboardingProvider(OpenAiConfig("key", "model", 10)).extract_onboarding(
        {"conversation": []}
    )
    assert result.onboarding["training_goal"] == "Força"


def test_openai_training_generation_uses_structured_plan_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {
        "name": "Plano inicial",
        "objective": "Força",
        "items": [
            {
                "exercise_name": "Agachamento",
                "sets": 3,
                "repetitions": "8",
                "load_guidance": "Carga confortável",
                "rest_seconds": 90,
            }
        ],
    }
    monkeypatch.setattr(
        ai, "urlopen", lambda request, timeout: BytesIO(openai_response({"plan": plan}))
    )
    result = OpenAiResponsesOnboardingProvider(OpenAiConfig("key", "model", 10)).generate_training(
        {"completed_onboarding": {"training_goal": "Força"}}
    )
    assert result.plan == plan


def test_ollama_training_generation_maps_the_same_structured_plan_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {
        "name": "Plano inicial",
        "objective": "Condicionamento",
        "items": [
            {
                "exercise_name": "Bicicleta ergométrica",
                "sets": 1,
                "repetitions": "10 minutos",
                "load_guidance": "Ritmo confortável",
                "rest_seconds": 0,
            }
        ],
    }
    monkeypatch.setattr(
        ai, "urlopen", lambda request, timeout: BytesIO(ollama_response({"plan": plan}))
    )
    result = OllamaOnboardingProvider(
        OllamaConfig("http://ollama:11434", "qwen3:4b", 30)
    ).generate_training({"completed_onboarding": {"training_goal": "Condicionamento"}})
    assert result.plan == plan


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_provider_selection(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    monkeypatch.setenv("AI_PROVIDER", provider)
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "key")
    expected = (
        "OpenAiResponsesOnboardingProvider" if provider == "openai" else "OllamaOnboardingProvider"
    )
    assert onboarding_ai_provider_from_environment().__class__.__name__ == expected


def test_ollama_uses_configured_url_model_and_shared_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setattr(
        ai,
        "urlopen",
        lambda request, timeout: (
            captured.append((request, timeout))
            or BytesIO(
                ollama_response(
                    {"assistant_message": "Qual é sua altura?", "interview_status": "in_progress"}
                )
            )
        ),
    )
    result = OllamaOnboardingProvider(
        OllamaConfig("http://ollama:11434", "qwen3:4b", 30)
    ).interview_turn({"current_user_message": "Olá"})
    assert result.assistant_message == "Qual é sua altura?"
    request_body = json.loads(captured[0][0].data)
    assert request_body["model"] == "qwen3:4b"
    assert request_body["think"] is False


@pytest.mark.parametrize(
    "instructions,context,reasoning",
    [
        (ai._TRAINING_GENERATION, {}, True),
        (ai._TRAINING_FULL_BODY_GENERATION, {}, True),
        (ai._TRAINING_COMPLETENESS, {"proposed_plan": {}}, True),
        (ai._TRAINING_ADAPTATION, {}, True),
        (ai._TRAINING_CHAT, {"rules": {"may_update_ai_draft": True}}, True),
        (ai._TRAINING_CHAT, {"rules": {"may_update_ai_draft": False}}, False),
        (ai._INTERVIEW, {}, False),
        (ai._EXTRACTION, {}, False),
        (ai._TRAINING_REQUEST_FOCUS, {}, False),
    ],
)
def test_local_reasoning_is_enabled_for_structured_training_only(instructions, context, reasoning):
    provider = OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 360))
    body = json.loads(provider._request(context, instructions, {}).data)
    assert body["think"] is reasoning
    assert body["model"] == "existing-writer"


def test_private_reasoning_is_not_returned_or_logged(monkeypatch, caplog):
    import logging

    secret = "PRIVATE_REASONING_WITH_CLIENT_CONTEXT"
    caplog.set_level(logging.INFO, logger="uvicorn.error.ai")
    payload = {
        "message": {
            "thinking": secret,
            "content": json.dumps({"sessions": [{"label": "", "complete": True, "issues": []}]}),
        }
    }
    monkeypatch.setattr(ai, "urlopen", lambda *a, **kw: BytesIO(json.dumps(payload).encode()))
    provider = OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "existing-writer", 360))
    result = provider.assess_training({"proposed_plan": {}})
    assert result.sessions[0].complete
    assert secret not in result.model_dump_json()
    assert secret not in caplog.text


def test_adapter_failures_are_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ai, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError())
    )
    with pytest.raises(AiProviderError):
        OllamaOnboardingProvider(
            OllamaConfig("http://ollama:11434", "qwen3:4b", 30)
        ).interview_turn({"current_user_message": "Olá"})


def test_unsupported_provider_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "unsupported")
    with pytest.raises(AiProviderError):
        onboarding_ai_provider_from_environment()


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_training_chat_uses_the_same_provider_neutral_contract(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("AI_PROVIDER", provider)
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "key")
    selected = training_chat_provider_from_environment()
    assert hasattr(selected, "training_chat")


def test_ollama_training_chat_maps_plain_shared_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ai,
        "urlopen",
        lambda request, timeout: BytesIO(ollama_response({"assistant_message": "Faça com calma."})),
    )
    result = OllamaOnboardingProvider(
        OllamaConfig("http://ollama:11434", "qwen3:4b", 30)
    ).training_chat({"current_user_message": "Como faço?"})
    assert result.assistant_message == "Faça com calma."


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_adaptation_uses_the_same_provider_neutral_contract(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("AI_PROVIDER", provider)
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "key")
    selected = training_adaptation_provider_from_environment()
    assert hasattr(selected, "generate_adaptation")


def test_ollama_adaptation_maps_the_shared_structured_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "explanation": "Vamos revisar esta alteração com um instrutor.",
        "operations": [
            {
                "operation_type": "adjust",
                "target_position": 1,
                "item": {
                    "exercise_name": "Agachamento",
                    "sets": 2,
                    "repetitions": "8",
                    "load_guidance": "Carga leve",
                    "rest_seconds": 90,
                    "equipment_requirement": None,
                    "is_existing_exercise": True,
                },
            }
        ],
    }
    monkeypatch.setattr(ai, "urlopen", lambda request, timeout: BytesIO(ollama_response(payload)))
    result = OllamaOnboardingProvider(
        OllamaConfig("http://ollama:11434", "qwen3:4b", 30)
    ).generate_adaptation({"base_plan": {}})
    assert result.operations[0]["operation_type"] == "adjust"


@pytest.mark.parametrize("kind", ["openai", "ollama"])
def test_extraction_schema_keeps_unknown_answers_nullable_and_requires_sources(kind, monkeypatch):
    payload = {"onboarding": {"uses_medications": None}, "evidence": {"uses_medications": None}}
    captured = []

    def respond(request, timeout):
        captured.append(json.loads(request.data))
        return BytesIO(openai_response(payload) if kind == "openai" else ollama_response(payload))

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OpenAiResponsesOnboardingProvider(OpenAiConfig("synthetic", "model", 10))
        if kind == "openai"
        else OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "model", 30))
    )
    result = provider.extract_onboarding({"conversation": []})
    assert result.onboarding["uses_medications"] is None
    body = captured[0]
    schema = body["text"]["format"]["schema"] if kind == "openai" else body["format"]
    assert "evidence" in schema["required"]
    fields = schema["properties"]["onboarding"]["properties"]
    assert all("null" in field["type"] for field in fields.values())
    assert None in fields["training_experience"]["enum"]
