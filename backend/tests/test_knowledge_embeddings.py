"""Embedding adapter validates the BGE-M3 contract without a live model dependency."""

import json
from io import BytesIO
from urllib.error import URLError

import pytest

from app.integrations import embeddings


def test_ollama_bge_m3_uses_embedding_endpoint_and_strict_dimensions(monkeypatch):
    vectors = [[1.0] + [0.0] * 1023]
    requests = []

    def respond(request, timeout):
        requests.append((request, timeout))
        return BytesIO(json.dumps({"embeddings": vectors}).encode())

    monkeypatch.setattr(embeddings, "urlopen", respond)
    assert (
        embeddings.OllamaBgeM3EmbeddingProvider("http://local:11434", 3).embed(["força"]) == vectors
    )
    request, timeout = requests[0]
    assert request.full_url == "http://local:11434/api/embed" and timeout == 3
    assert json.loads(request.data) == {"model": "bge-m3", "input": ["força"], "truncate": False}


@pytest.mark.parametrize("vector", [[0.0] * 1024, [1.0] * 10, [True] * 1024, [float("inf")] * 1024])
def test_invalid_or_degenerate_vectors_are_rejected(vector):
    with pytest.raises(embeddings.EmbeddingProviderError):
        embeddings.validate_embedding(vector)


def test_embedding_failure_is_controlled_and_does_not_include_input(monkeypatch):
    def fail(request, timeout):
        raise URLError("unreachable")

    monkeypatch.setattr(embeddings, "urlopen", fail)
    with pytest.raises(embeddings.EmbeddingProviderError, match="embedding_unavailable") as error:
        embeddings.OllamaBgeM3EmbeddingProvider().embed(["private client context"])
    assert "private" not in str(error.value)
