"""Offline deterministic embedding provider and strict output validation."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from django.conf import settings

from knowledge.errors import InvalidEmbeddingError

TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class DeterministicHashEmbeddingProvider:
    provider_name = "supportpilot-deterministic"
    model_name = "hashed-token-projection-v1"

    def __init__(self, *, dimension: int | None = None) -> None:
        self._dimension = dimension or settings.KNOWLEDGE_EMBEDDING_DIMENSION

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = TOKEN_RE.findall(text.casefold())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Two stable projections reduce collisions while retaining lexical similarity.
            for position in (0, 4):
                index = int.from_bytes(digest[position : position + 4], "big") % self.dimension
                sign = 1.0 if digest[position + 8] & 1 else -1.0
                vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def validate_embeddings(
    vectors: Sequence[Sequence[float]], *, expected_count: int, dimension: int
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise InvalidEmbeddingError()
    validated: list[list[float]] = []
    for vector in vectors:
        if len(vector) != dimension:
            raise InvalidEmbeddingError()
        converted: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidEmbeddingError()
            number = float(value)
            if not math.isfinite(number):
                raise InvalidEmbeddingError()
            converted.append(number)
        validated.append(converted)
    return validated


def get_embedding_provider() -> EmbeddingProvider:
    return DeterministicHashEmbeddingProvider()
