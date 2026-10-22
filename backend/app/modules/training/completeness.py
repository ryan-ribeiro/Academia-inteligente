"""Check requested sessions and bounded AI coverage review before persistence."""

import re
import unicodedata

from app.integrations.ai import AiTrainingPlanAssessment
from app.modules.training.schema import TrainingPlanItemInput, TrainingPlanVersionInput

_DAY = re.compile(r"\s*\(dia\s+([a-z]|[1-7])\)\s*$", re.IGNORECASE)
_RESOURCE_PREFIX = re.compile(
    r"^\s*(?P<resource>peso corporal|peso do corpo|body\s?weight|halteres?|barras?|"
    r"m[aá]quinas?|equipamentos?|el[aá]sticos?)\s*[:—–-]\s*",
    re.IGNORECASE,
)
_NUMBERS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "três": 3,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
}


class IncompleteTrainingPlanError(ValueError):
    def __init__(self, issues: list[dict]):
        super().__init__("incomplete_training_plan")
        self.issues = issues


def split_training_day(name: str) -> tuple[str, str]:
    match = _DAY.search(name)
    if not match:
        return "", name
    label = match.group(1).upper()
    if label.isdigit():
        label = "ABCDEFG"[int(label) - 1]
    return label, name[: match.start()].strip()


def exercise_identity(name: str) -> tuple[str, str]:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", name.casefold())
        if not unicodedata.combining(char)
    )
    day, exercise = split_training_day(" ".join(normalized.split()))
    return day, " ".join(re.sub(r"[^\w\s]", " ", exercise).split())


def training_review_context(plan: TrainingPlanVersionInput, context: dict) -> dict:
    """Review every actual session even when the request has no explicit schedule."""
    labels = context.get("training_schedule", {}).get("session_labels", [])
    if not labels:
        labels = list(
            dict.fromkeys(split_training_day(item.exercise_name)[0] for item in plan.items)
        )
    return {
        **context,
        "training_schedule": {"session_labels": labels},
        "proposed_plan": plan.model_dump(mode="json"),
    }


def normalize_exercise_resource(item: TrainingPlanItemInput) -> TrainingPlanItemInput:
    """Separate an explicit resource prefix without inventing or substituting a movement."""
    day, name = split_training_day(item.exercise_name)
    prefix = _RESOURCE_PREFIX.match(name)
    if prefix is None or not name[prefix.end() :].strip():
        return item
    movement = name[prefix.end() :].strip()
    resource = " ".join(prefix.group("resource").split())
    guidance = item.load_guidance
    if resource.casefold() not in guidance.casefold():
        guidance = f"{resource}; {guidance}"
    return type(item).model_validate(
        {
            **item.model_dump(),
            "exercise_name": movement + (f" (Dia {day})" if day else ""),
            "load_guidance": guidance,
        }
    )


def normalize_training_resources(plan: TrainingPlanVersionInput) -> TrainingPlanVersionInput:
    return plan.model_copy(
        update={"items": [normalize_exercise_resource(item) for item in plan.items]}
    )


def validate_exercise_names(plan: TrainingPlanVersionInput) -> None:
    """Reject obvious resource-only labels; semantic validity still needs AI review."""
    resources = {
        "peso corporal",
        "peso do corpo",
        "bodyweight",
        "body weight",
        "halter",
        "halteres",
        "barra",
        "barras",
        "maquina",
        "maquinas",
        "equipamento",
        "equipamentos",
        "elastico",
        "elasticos",
    }
    issues = []
    for position, item in enumerate(plan.items, 1):
        day, name = exercise_identity(item.exercise_name)
        _, raw_name = split_training_day(item.exercise_name)
        resource_prefix = _RESOURCE_PREFIX.match(raw_name)
        ambiguous = re.match(
            r"^(?:flexao (?:de|da|das) pernas?|pressao (?:de|do|dos) joelhos?)\b", name
        )
        if not name or name in resources or resource_prefix or ambiguous:
            issues.append(
                {
                    "label": day,
                    "issues": ["ambiguous_exercise"],
                    "position": position,
                    "exercise_name": item.exercise_name,
                    "reason": "resource_prefix" if resource_prefix else "unidentified_movement",
                }
            )
    if issues:
        raise IncompleteTrainingPlanError(issues)


def validate_session_variation(
    plan: TrainingPlanVersionInput,
    context: dict,
    *,
    assessment: AiTrainingPlanAssessment | None = None,
    citations: list[str] | None = None,
) -> None:
    """Allow a copied sheet only with an assessed, cited recommendation to repeat it."""
    current = sorted(exercise_identity(item.exercise_name)[1] for item in plan.items)
    for previous in context.get("previous_sessions", []):
        previous_plan = TrainingPlanVersionInput.model_validate(previous["plan"])
        selection = sorted(exercise_identity(item.exercise_name)[1] for item in previous_plan.items)
        if current == selection:
            if _has_repetition_recommendation(context, assessment, citations):
                continue
            raise IncompleteTrainingPlanError(
                [
                    {
                        "label": context["training_session"]["label"],
                        "issues": ["repeated_session"],
                        "matches_label": previous["label"],
                    }
                ]
            )


def _has_repetition_recommendation(
    context: dict,
    assessment: AiTrainingPlanAssessment | None,
    citations: list[str] | None,
) -> bool:
    knowledge = context.get("knowledge", {})
    if assessment is None or knowledge.get("knowledge_status") != "supported":
        return False
    label = context["training_session"]["label"]
    review = next((item for item in assessment.sessions if item.label == label), None)
    if review is None or not review.complete or review.issues:
        return False
    recommendation = review.repetition_recommendation
    if recommendation is None or recommendation.chunk_id not in (citations or []):
        return False
    chunk = next(
        (
            item
            for item in knowledge.get("chunks", [])[:6]
            if item["chunk_id"] == recommendation.chunk_id
        ),
        None,
    )
    # Quote matching grounds the review in retrieved text; semantic applicability
    # is assessed by the existing reviewer, never inferred from citation presence.
    return chunk is not None and " ".join(recommendation.quote.split()) in " ".join(
        chunk["content"].split()
    )


def requested_training_schedule(request: str, focus: dict | None) -> dict:
    if not focus or focus["scope"] != "full_body":
        return {"session_labels": []}
    match = re.search(
        r"\b([1-7]|um|uma|dois|duas|três|tres|quatro|cinco|seis|sete)\s+(?:dias?|vezes)\b",
        request.casefold(),
    )
    count = (
        (int(match.group(1)) if match.group(1).isdigit() else _NUMBERS[match.group(1)])
        if match
        else 0
    )
    return {"session_labels": list("ABCDEFG"[:count])}


def validate_requested_sessions(plan: TrainingPlanVersionInput, context: dict) -> None:
    expected = context.get("training_schedule", {}).get("session_labels", [])
    if not expected:
        return
    actual = {split_training_day(item.exercise_name)[0] for item in plan.items}
    if actual != set(expected):
        raise IncompleteTrainingPlanError(
            [
                {"label": label, "issues": ["missing_session"]}
                for label in expected
                if label not in actual
            ]
            or [{"label": "", "issues": ["missing_session"]}]
        )


def validate_assessment(assessment: AiTrainingPlanAssessment, context: dict) -> None:
    expected = context.get("training_schedule", {}).get("session_labels", []) or [""]
    labels = [item.label for item in assessment.sessions]
    if sorted(labels) != sorted(expected):
        raise IncompleteTrainingPlanError(
            [{"label": label, "issues": ["missing_session"]} for label in expected]
        )
    issues = [item.model_dump() for item in assessment.sessions if not item.complete or item.issues]
    if issues:
        raise IncompleteTrainingPlanError(issues)
