"""Keep prescription retrieval focused on the client's request and own restrictions."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.knowledge.service import MAX_CHUNKS, KnowledgeContext, KnowledgeService


def training_knowledge_query(
    request: str,
    onboarding: dict[str, object],
    focus: dict[str, object] | None = None,
) -> str:
    focus = focus or {}
    parts = [
        " ".join(focus.get("muscle_groups", [])),
        str(focus.get("goal") or ""),
        request.strip()[:2000],
    ]
    fields = (
        ("training_experience",) if focus.get("goal") else ("training_goal", "training_experience")
    )
    for field in fields:
        value = onboarding.get(field)
        if value:
            parts.append(str(value)[:400])
    # General prescription evidence must be searched alongside any safety restrictions.
    parts.append("Treinamento resistido, adaptações musculares, progressão de força e recuperação.")
    return "\n".join(filter(None, parts))


def retrieve_training_knowledge(
    service: KnowledgeService,
    session: Session,
    client_id: UUID,
    request: str,
    onboarding: dict[str, object],
    *,
    focus: dict[str, object] | None = None,
) -> KnowledgeContext:
    general = service.retrieve(
        session, client_id, training_knowledge_query(request, onboarding, focus)
    )
    restrictions = "\n".join(
        str(onboarding[field])[:800]
        for field in ("limitations_or_complaints", "health_conditions")
        if onboarding.get(field)
    )
    if not restrictions or general.knowledge_status == "unavailable":
        return general
    safety = service.retrieve(session, client_id, restrictions)
    if safety.knowledge_status == "unavailable":
        return safety
    # Reserve space for general prescription and for the client's restrictions.
    # Both searches enforce scope, licenses and freshness before ranking.
    candidates = [*general.chunks[:3], *safety.chunks[:3], *general.chunks[3:], *safety.chunks[3:]]
    selected = {}
    for chunk in candidates:
        selected.setdefault(chunk["chunk_id"], chunk)
        if len(selected) == MAX_CHUNKS:
            break
    if not selected:
        status = (
            "outdated"
            if "outdated" in (general.knowledge_status, safety.knowledge_status)
            else "insufficient_evidence"
        )
        return KnowledgeContext.empty(status)
    status = (
        "supported"
        if general.knowledge_status == safety.knowledge_status == "supported"
        else "insufficient_evidence"
    )
    limitations = " ".join(
        dict.fromkeys(filter(None, (general.knowledge_limitations, safety.knowledge_limitations)))
    )
    return KnowledgeContext(tuple(selected.values()), status, limitations)
