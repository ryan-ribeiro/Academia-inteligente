"""Ground the AI-selected retrieval scope in the client's actual request."""

import re
import unicodedata
from collections.abc import Callable

from app.integrations.ai import AiTrainingRequestFocus
from app.integrations.ai_diagnostics import record_retry


class InvalidTrainingFocusError(ValueError):
    """The writer added a muscle/region that the client did not request."""


def _normalized(value: str) -> str:
    return " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        ).split()
    )


def analyze_training_focus(
    operation: Callable[[dict[str, object]], AiTrainingRequestFocus], request: str
) -> dict[str, object]:
    context: dict[str, object] = {"training_request": request}
    text = _normalized(request)
    body_term = r"(?:corpo inteiro|todo o corpo|full[ -]?body)"
    full_body_requested = bool(
        re.search(r"\b" + body_term + r"\b", text)
        and not re.search(r"\bnao(?:\s+\w+){0,3}\s+" + body_term + r"\b", text)
    )
    for attempt in range(2):
        focus = operation(context)
        scope_matches = (focus.scope == "full_body") == full_body_requested
        if (
            scope_matches
            and (focus.scope != "targeted" or focus.muscle_groups)
            and all(
                re.search(r"(?<!\w)" + re.escape(_normalized(group)) + r"(?!\w)", text)
                for group in focus.muscle_groups
            )
        ):
            return focus.model_dump()
        record_retry("invalid_training_focus", will_retry=not attempt)
        if attempt:
            raise InvalidTrainingFocusError("ungrounded_training_focus")
        context = {
            "training_request": request,
            "focus_correction": {
                "rejected_focus": focus.model_dump(),
                "instruction": (
                    "Se o pedido é de corpo inteiro ou todo o corpo, mantenha scope=full_body "
                    "e retorne muscle_groups=[]; não abrevie a expressão nem a trate como "
                    "um grupo muscular localizado. "
                    "O foco incluiu grupos ausentes do pedido ou omitiu os grupos do foco "
                    "localizado. Copie em muscle_groups somente os termos musculares ou "
                    "regiões literalmente presentes no pedido original, sem traduzir ou "
                    "trocar por sinônimos. Por exemplo, se o aluno pediu bíceps, não inclua "
                    "tríceps nem ombros. Preserve todos os grupos explicitamente pedidos."
                ),
            },
        }
    raise InvalidTrainingFocusError("ungrounded_training_focus")
