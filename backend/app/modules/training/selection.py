"""Validate AI exercise selection before saving a draft; never pick a row arbitrarily."""

import re
import unicodedata
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.integrations.ai_diagnostics import record_retry
from app.modules.training.completeness import (
    IncompleteTrainingPlanError,
    split_training_day,
    validate_assessment,
    validate_requested_sessions,
    validate_session_variation,
)
from app.modules.training.schema import TrainingPlanVersionInput

Response = TypeVar("Response", bound=BaseModel)


class RedundantTrainingExerciseError(ValueError):
    """The writer did not resolve competing prescriptions for the same exercise."""


def _normalized(value: str) -> str:
    return " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(char)
        ).split()
    )


def validate_exercise_selection(plan: TrainingPlanVersionInput) -> None:
    seen: dict[str, list[str]] = {}
    for item in plan.items:
        name = _normalized(item.exercise_name)
        day, name = split_training_day(name)
        name = re.sub(r"[^\w\s]", " ", name)
        name = " ".join(name.split())
        for previous_day in seen.get(name, []):
            if not day or not previous_day or day == previous_day:
                raise RedundantTrainingExerciseError("redundant_exercise_prescription")
        seen.setdefault(name, []).append(day)


def request_selected_training(
    operation: Callable[[dict[str, object]], Response],
    context: dict[str, object],
    *,
    plan_field: str,
    assess: Callable | None = None,
) -> Response:
    """Ask the writer to resolve duplicates once using the same request and evidence."""
    response = operation(context)
    for attempt in range(2):
        raw_plan = getattr(response, plan_field)
        if raw_plan is None:
            if attempt:
                raise RedundantTrainingExerciseError("missing_corrected_plan")
            return response
        plan = TrainingPlanVersionInput.model_validate(raw_plan)
        try:
            validate_exercise_selection(plan)
            validate_requested_sessions(plan, context)
            validate_session_variation(plan, context)
            if assess is not None:
                validate_assessment(
                    assess({**context, "proposed_plan": plan.model_dump(mode="json")}), context
                )
            return response
        except (RedundantTrainingExerciseError, IncompleteTrainingPlanError) as error:
            record_retry(
                "incomplete_training_plan"
                if isinstance(error, IncompleteTrainingPlanError)
                else "redundant_exercise_prescription",
                will_retry=not attempt,
            )
            if attempt:
                raise
            issues = error.issues if isinstance(error, IncompleteTrainingPlanError) else []
        response = operation(
            {
                **context,
                "selection_correction": {
                    "rejected_plan": plan.model_dump(mode="json"),
                    "completeness_issues": issues,
                    "instruction": (
                        "A ficha tem lacunas de abrangência/dias ou repete exercícios. Corrija "
                        "completeness_issues em TODAS as fichas de training_schedule; cada ficha "
                        "de corpo inteiro deve ser completa. Não transforme três dias em três "
                        "exercícios. Reavalie as alternativas usando o "
                        "pedido original e as evidências fornecidas; selecione a prescrição mais "
                        "adequada, sem escolher automaticamente a primeira linha. Não renomeie "
                        "duplicatas nem invente dias para contornar a validação. Só mantenha "
                        "prescrições diferentes do mesmo exercício se o planejamento já prevê "
                        "dias distintos, identificados em exercise_name como (Dia A), (Dia B). "
                        "Retorne a ficha completa corrigida e as citações que a sustentam."
                    ),
                },
            }
        )
    raise RedundantTrainingExerciseError("redundant_exercise_prescription")
