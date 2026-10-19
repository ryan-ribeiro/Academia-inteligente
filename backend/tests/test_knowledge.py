"""Retrieval safeguards, citation provenance and idempotent catalogue initialization."""

import copy
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from test_training_generation import session as session
from test_training_lifecycle import client_id

from app.integrations.embeddings import EMBEDDING_DIMENSIONS, EmbeddingProviderError
from app.modules.knowledge.bootstrap import CATALOG_PATH, seed_catalog
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.modules.knowledge.service import KnowledgeCitationError, KnowledgeContext, KnowledgeService


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.extend(texts)
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]


def catalog_source(identifier="reviewed", **overrides):
    value = {
        "id": identifier,
        "title": "Reviewed exercise guidance",
        "url": "https://example.test/source",
        "authors": ["Reviewed author"],
        "language": "pt-BR",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "commercial_use_allowed": True,
        "review_status": "approved",
        "reviewed_by": "content-license-review",
        "reviewed_at": date.today().isoformat(),
        "review_due_at": (date.today() + timedelta(days=365)).isoformat(),
        "limitations": ["Resultados populacionais não garantem benefício individual."],
        "chunks": [
            {
                "id": identifier + "-1",
                "section": "Carga",
                "content": "Exercício força carga gradual.",
            }
        ],
    }
    value.update(overrides)
    return value


def test_seed_is_idempotent_refreshes_changed_chunks_and_removes_revoked_content(session):
    provider = FakeEmbeddings()
    data = {"version": 1, "sources": [catalog_source(), catalog_source("another")]}
    assert seed_catalog(session, provider, data) == 2
    session.commit()
    assert seed_catalog(session, provider, data) == 2
    assert len(provider.calls) == 2
    changed = copy.deepcopy(data)
    changed["sources"][0]["chunks"][0]["content"] = "Exercício força progressão revista."
    seed_catalog(session, provider, changed)
    session.commit()
    assert len(provider.calls) == 3
    changed["sources"][0]["chunks"][0]["section"] = "Progressão revista"
    seed_catalog(session, provider, changed)
    session.commit()
    assert len(provider.calls) == 4
    changed["sources"][0].update(review_status="excluded", commercial_use_allowed=False)
    assert seed_catalog(session, provider, changed) == 1
    assert session.get(KnowledgeChunk, "reviewed-1") is None
    assert session.get(KnowledgeSource, "reviewed").review_status == "excluded"


@pytest.mark.parametrize("license", ["CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "pending", "unauthorized"])
def test_approval_cannot_bypass_restricted_licence(session, license):
    with pytest.raises(ValueError, match="unlicensed_or_unreviewed"):
        seed_catalog(
            session, FakeEmbeddings(), {"version": 1, "sources": [catalog_source(license=license)]}
        )


def test_initial_catalogue_contains_all_candidates_but_embeds_only_reviewed_allowed_content(
    session,
):
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    provider = FakeEmbeddings()
    count = seed_catalog(session, provider, data)
    assert len(session.scalars(select(KnowledgeSource)).all()) == 14
    assert count == len(provider.calls) > 0
    rows = session.execute(select(KnowledgeChunk, KnowledgeSource).join(KnowledgeSource)).all()
    assert all(
        source.review_status == "approved" and "NC" not in source.license for _, source in rows
    )


def test_retrieval_limits_matches_and_never_leaks_private_client_sources(session):
    first = client_id(session)
    from test_training_chat import create_client

    second = create_client(session, "other-client", "other@example.test").id
    sources = [catalog_source(f"public-{index}") for index in range(8)]
    seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": sources})
    source = session.get(KnowledgeSource, "public-0")
    source.client_id = second
    session.flush()
    context = KnowledgeService().retrieve(session, first, "força")
    assert context.knowledge_status == "supported"
    assert len(context.chunks) == 6
    assert all(chunk["source_id"] != "public-0" for chunk in context.chunks)


def test_stale_and_no_evidence_have_clear_clinical_limits(session):
    identifier = client_id(session)
    source = catalog_source(review_due_at=date.today().isoformat())
    seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": [source]})
    service = KnowledgeService()
    outdated = service.retrieve(session, identifier, "força")
    assert outdated.knowledge_status == "outdated" and not outdated.chunks
    assert "revisão vencida" in outdated.knowledge_limitations
    missing = service.retrieve(session, identifier, "astronomia")
    assert missing.knowledge_status == "insufficient_evidence" and not missing.chunks
    assert "diagnósticos" in missing.knowledge_limitations


def test_server_only_resolves_exact_retrieved_chunk_ids_and_keeps_provenance(session):
    identifier = client_id(session)
    seed_catalog(session, FakeEmbeddings(), {"version": 1, "sources": [catalog_source()]})
    context = KnowledgeService().retrieve(session, identifier, "força")
    result = context.resolve_citations(["reviewed-1", "reviewed-1"], "supported")
    assert len(result.citations) == 1
    assert result.citations[0]["authors"] == ["Reviewed author"]
    assert "content" not in result.citations[0]
    for citations in (["invented"], [{"chunk_id": "reviewed-1", "url": "https://invented.test"}]):
        with pytest.raises(KnowledgeCitationError):
            context.resolve_citations(citations)
    assert context.resolve_citations([]).knowledge_status == "insufficient_evidence"
    assert (
        context.resolve_citations(["reviewed-1"], "insufficient_evidence").knowledge_status
        == "insufficient_evidence"
    )
    assert (
        KnowledgeContext.empty("outdated").resolve_citations([], "supported").knowledge_status
        == "outdated"
    )


def test_bad_seed_embedding_is_rejected_without_persisting_claimed_ready_catalogue(session):
    class InvalidEmbeddings:
        def embed(self, texts):
            return [[float("nan")] * EMBEDDING_DIMENSIONS for _ in texts]

    with pytest.raises(EmbeddingProviderError):
        seed_catalog(session, InvalidEmbeddings(), {"version": 1, "sources": [catalog_source()]})
    session.rollback()
    assert not session.scalars(select(KnowledgeSource)).all()


def test_catalogue_removal_preserves_previously_assigned_private_source(session):
    from test_training_chat import create_client

    client = create_client(session, "private-catalogue", "private-catalogue@example.test")
    provider = FakeEmbeddings()
    seed_catalog(
        session, provider, {"version": 1, "sources": [catalog_source("private"), catalog_source()]}
    )
    private = session.get(KnowledgeSource, "private")
    private.client_id = client.id
    session.commit()
    seed_catalog(session, provider, {"version": 1, "sources": [catalog_source()]})
    assert private.review_status == "approved"
    assert session.get(KnowledgeChunk, "private-1") is not None
