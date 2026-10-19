"""Deterministic client preview of validated, persisted training content."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.training.completeness import split_training_day
from app.modules.training.models import TrainingPlanItem, TrainingPlanVersion
from app.modules.training.schema import TrainingPlanVersionInput


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", r"\|")


def proposal_preview(session: Session, version: TrainingPlanVersion) -> str:
    items = session.scalars(
        select(TrainingPlanItem)
        .where(TrainingPlanItem.version_id == version.id)
        .order_by(TrainingPlanItem.position)
    )
    return training_preview(version.name, version.objective, items)


def adaptation_preview(data: TrainingPlanVersionInput) -> str:
    return training_preview(data.name, data.objective, data.items)


def training_preview(name: str, objective: str, items) -> str:
    groups: dict[str, list] = {}
    for item in items:
        label, exercise_name = split_training_day(item.exercise_name)
        groups.setdefault(label, []).append((exercise_name, item))
    name = " ".join(name.split())
    if any(groups):
        division = re.sub(r"^Treino [A-Z]\s*[—–-]\s*", "", name)
        return "\n\n".join(
            _session_preview(f"Treino {label} — {division}" if label else name, objective, rows)
            for label, rows in sorted(groups.items())
        )
    return _session_preview(name, objective, groups.get("", []))


def _session_preview(name: str, objective: str, rows: list) -> str:
    name = " ".join(name.split())
    title = name if re.match(r"^Treino [A-Z]\s*[—–-]", name) else f"Treino A — {name}"
    lines = [
        title,
        f"Objetivo: {' '.join(objective.split())}",
        "Status: Aguardando revisão do instrutor",
        "",
        "| Ordem | Exercício | Séries | Repetições ou duração | Carga | Descanso |",
        "|---|---|---:|---|---|---:|",
    ]
    for position, (exercise_name, item) in enumerate(rows, 1):
        values = (
            position,
            exercise_name,
            item.sets,
            item.repetitions,
            item.load_guidance,
            f"{item.rest_seconds} s",
        )
        lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
    return "\n".join(lines)
