"""Check requested sessions and bounded AI coverage review before persistence."""

import re
import json
import unicodedata

from app.integrations.ai import AiTrainingPlanAssessment
from app.modules.training.schema import TrainingPlanVersionInput

_DAY = re.compile(r"\s*\(dia\s+([a-z]|[1-7])\)\s*$", re.IGNORECASE)
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


def validate_session_variation(plan: TrainingPlanVersionInput, context: dict) -> None:
    def signature(data):
        rows = []
        for item in data.items:
            row = item.model_dump(mode="json")
            _, name = split_training_day(item.exercise_name)
            name = "".join(c for c in unicodedata.normalize("NFKD", name.casefold()) if not unicodedata.combining(c))
            row["exercise_name"] = " ".join(re.sub(r"[^\w\s]", " ", name).split())
            row = {key: " ".join(value.casefold().split()) if isinstance(value, str) else value for key, value in row.items()}
            rows.append(json.dumps(row, sort_keys=True))
        return sorted(rows)
    current = signature(plan)
    for previous in context.get("previous_sessions", []):
        if current == signature(TrainingPlanVersionInput.model_validate(previous["plan"])):
            raise IncompleteTrainingPlanError([{
                "label": context["training_session"]["label"], "issues": ["repeated_session"],
            }])
