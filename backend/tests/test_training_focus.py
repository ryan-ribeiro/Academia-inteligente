"""Focus decoding must respect the same scope rules as domain validation."""

import json
from io import BytesIO

import pytest

from app.integrations import ai
from app.integrations.ai import (
    AiTrainingRequestFocus,
    OllamaConfig,
    OllamaOnboardingProvider,
    OpenAiConfig,
    OpenAiResponsesOnboardingProvider,
)
from app.modules.training.focus import InvalidTrainingFocusError, analyze_training_focus


@pytest.mark.parametrize("kind", ["openai", "ollama"])
@pytest.mark.parametrize(
    "training_request,scope,groups,allowed",
    [
        (
            "Refaça todo a minha ficha de treino do zero, para ganho de massa",
            "unspecified",
            [],
            ["targeted", "unspecified"],
        ),
        ("Refaça minha ficha para bíceps", "targeted", ["bíceps"], ["targeted", "unspecified"]),
        ("Gere um treino de corpo inteiro", "full_body", [], ["full_body"]),
    ],
)
def test_scope_constraints_reach_both_provider_schemas(
    monkeypatch, kind, training_request, scope, groups, allowed
):
    calls = []
    focus = {"scope": scope, "muscle_groups": groups, "goal": None}

    def respond(request, timeout):
        calls.append(json.loads(request.data))
        payload = (
            {"output": [{"content": [{"type": "output_text", "text": json.dumps(focus)}]}]}
            if kind == "openai"
            else {"message": {"content": json.dumps(focus)}}
        )
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ai, "urlopen", respond)
    provider = (
        OpenAiResponsesOnboardingProvider(OpenAiConfig("test-key", "writer", 10))
        if kind == "openai"
        else OllamaOnboardingProvider(OllamaConfig("http://ollama:11434", "writer", 120))
    )
    assert analyze_training_focus(provider.analyze_training_request, training_request) == focus
    schema = calls[0]["text"]["format"]["schema"] if kind == "openai" else calls[0]["format"]
    assert schema["properties"]["scope"]["enum"] == allowed
    assert schema["properties"]["muscle_groups"]["maxItems"] == (0 if scope == "full_body" else 20)


def test_rebuild_correction_explains_unspecified_scope_and_retains_constraints():
    contexts = []
    results = iter(
        [
            AiTrainingRequestFocus(scope="full_body", muscle_groups=[], goal="ganho de massa"),
            AiTrainingRequestFocus(scope="unspecified", muscle_groups=[], goal="ganho de massa"),
        ]
    )

    def operation(context):
        contexts.append(context)
        return next(results)

    result = analyze_training_focus(operation, "Refaça minha ficha do zero para ganho de massa")
    assert result["scope"] == "unspecified"
    assert contexts[0]["focus_constraints"] == contexts[1]["focus_constraints"]
    assert "scope=unspecified" in contexts[1]["focus_correction"]["instruction"]


@pytest.mark.parametrize("scope,groups", [("full_body", []), ("targeted", ["bíceps"])])
def test_persistent_unrequested_scope_or_muscles_are_still_rejected(scope, groups):
    with pytest.raises(InvalidTrainingFocusError):
        analyze_training_focus(
            lambda context: AiTrainingRequestFocus(scope=scope, muscle_groups=groups, goal=None),
            "Refaça minha ficha do zero para ganho de massa",
        )
