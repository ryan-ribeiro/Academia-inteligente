"""Local BGE-M3 embeddings; independent of the writing-LLM provider."""

from __future__ import annotations

import json
import math
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIMENSIONS = 1024


class EmbeddingProviderError(Exception):
    """Controlled embedding failure without source text or client data in its message."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_embedding(value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIMENSIONS:
        raise EmbeddingProviderError("invalid_embedding_dimensions")
    if any(
        isinstance(number, bool)
        or not isinstance(number, (int, float))
        or not math.isfinite(number)
        for number in value
    ):
        raise EmbeddingProviderError("invalid_embedding_values")
    result = [float(number) for number in value]
    if not any(result):
        raise EmbeddingProviderError("invalid_zero_embedding")
    return result


class OllamaBgeM3EmbeddingProvider:
    model = EMBEDDING_MODEL

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (
            base_url or os.getenv("KNOWLEDGE_OLLAMA_BASE_URL", "http://knowledge-ollama:11434")
        ).rstrip("/")
        self.timeout = timeout or float(os.getenv("KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS", "120"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > 32 or any(not text.strip() or len(text) > 12000 for text in texts):
            raise EmbeddingProviderError("invalid_embedding_input")
        request = Request(
            self.base_url + "/api/embed",
            data=json.dumps({"model": self.model, "input": texts, "truncate": False}).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read(2_000_001))
            vectors = data.get("embeddings")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise EmbeddingProviderError("invalid_embedding_response")
            return [validate_embedding(vector) for vector in vectors]
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise EmbeddingProviderError("embedding_unavailable") from error
        except (ValueError, TypeError, AttributeError) as error:
            raise EmbeddingProviderError("invalid_embedding_response") from error
