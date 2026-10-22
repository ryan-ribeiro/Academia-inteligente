"""Validate AI exercise selection before saving a draft; never pick a row arbitrarily."""

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.integrations.ai_diagnostics import record_retry
from app.modules.training.completeness import (
    IncompleteTrainingPlanError,
    exercise_identity,
    normalize_training_resources,
    training_review_context,
    validate_assessment,
    validate_exercise_names,
    validate_requested_sessions,
    validate_session_variation,
)
from app.modules.training.schema import TrainingPlanVersionInput

Response = TypeVar("Response", bound=BaseModel)


class RedundantTrainingExerciseError(ValueError):
    """The writer did not resolve competing prescriptions for the same exercise."""


def validate_exercise_selection(plan: TrainingPlanVersionInput) -> None:
    seen: dict[str, list[str]] = {}
    for item in plan.items:
        day, name = exercise_identity(item.exercise_name)
        for previous_day in seen.get(name, []):
            if not day or not previous_day or day == previous_day:
                raise RedundantTrainingExerciseError("redundant_exercise_prescription")
        seen.setdefault(name, []).append(day)


def request_selected_training(
    operation: Callable[[dict[str, object]], Response],
    context: dict[str, object],
    *,
    assess: Callable,
    plan_field: str = "plan",
    plan_builder: Callable | None = None,
) -> Response:
    """Require exercise review and one bounded correction before any AI plan is saved."""

    def write(selected_context):
        result = operation(selected_context)
        if plan_builder is None:
            raw_plan = getattr(result, plan_field)
            if raw_plan is not None:
                normalized = normalize_training_resources(
                    TrainingPlanVersionInput.model_validate(raw_plan)
                )
                result = result.model_copy(update={plan_field: normalized.model_dump(mode="json")})
        return result

    response = write(context)
    for attempt in range(2):
        raw_plan = plan_builder(response) if plan_builder else getattr(response, plan_field)
        if raw_plan is None:
            if attempt:
                raise RedundantTrainingExerciseError("missing_corrected_plan")
            return response
        plan = TrainingPlanVersionInput.model_validate(raw_plan)
        try:
            validate_exercise_names(plan)
            validate_exercise_selection(plan)
            validate_requested_sessions(plan, context)
            review_context = training_review_context(plan, context)
            assessment = assess(review_context)
            validate_session_variation(
                plan,
                context,
                assessment=assessment,
                citations=getattr(response, "citations", []),
            )
            validate_assessment(assessment, review_context)
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
        response = write(
            {
                **context,
                "selection_correction": exercise_selection_correction(plan, issues),
            }
        )
    raise RedundantTrainingExerciseError("redundant_exercise_prescription")


def exercise_selection_correction(plan: TrainingPlanVersionInput, issues: list[dict]) -> dict:
    """The same precise feedback repairs legacy content and a newly rejected candidate."""
    return {
        "rejected_plan": plan.model_dump(mode="json"),
        "completeness_issues": issues,
        "instruction": (
            "Corrija rejected_plan conforme completeness_issues e o pedido original. "
            "repeated_session: a ficha copia matches_label; substitua ao menos um "
            "exercício por uma alternativa real de função complementar aplicável. "
            "Compare com TODOS os previous_sessions. Não devolva a mesma seleção "
            "mudando só ordem, grafia, séries, repetições, carga ou descanso. "
            "Só repita a ficha inteira com recomendação explícita e aplicável nos "
            "trechos citados, confirmada na revisão; frequência semanal não basta. "
            "Consolide duplicatas no mesmo dia; não oculte repetições só trocando nomes "
            "nem invente dias. "
            "ambiguous_exercise: corrija cada position/exercise_name informado com um movimento "
            "reconhecido e preciso. Pressão de joelho e flexão de perna são ambíguos; "
            "substitua esses itens por exercícios identificáveis, não por sinônimos vagos. "
            "Acrescentar com peso corporal, com halteres ou leve não resolve o nome ambíguo. "
            "Exemplos de nomes identificáveis: flexão de braços, agachamento, ponte de quadril "
            "e remada. São exemplos de identificação, não substituições automáticas; escolha "
            "apenas movimentos compatíveis com as fontes e restrições do cliente. "
            "Peso corporal é carga, "
            "não exercício nem prefixo do nome; mantenha recursos apenas em load_guidance. "
            "Preserve restrições e a abrangência pedida: treino localizado não exige "
            "corpo inteiro. Preserve os dias de training_schedule. "
            "Retorne a ficha completa e suas citações."
        ),
    }
