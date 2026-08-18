import math

import pytest

from knowledge.errors import InvalidEmbeddingError
from knowledge.ingestion.embeddings import (
    DeterministicHashEmbeddingProvider,
    validate_embeddings,
)


def _cosine(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True))


class TestDeterministicEmbeddingProvider:
    def test_same_input_is_stable_across_instances(self):
        first = DeterministicHashEmbeddingProvider(dimension=64).embed_query("refund payment")
        second = DeterministicHashEmbeddingProvider(dimension=64).embed_query("refund payment")
        assert first == second

    def test_dimension_and_finite_values(self):
        vector = DeterministicHashEmbeddingProvider(dimension=32).embed_query("hello world")
        assert len(vector) == 32
        assert all(math.isfinite(value) for value in vector)

    def test_lexical_similarity_is_meaningful(self):
        provider = DeterministicHashEmbeddingProvider(dimension=256)
        query = provider.embed_query("refund duplicate payment policy")
        relevant = provider.embed_query("duplicate payment refund policy and verification")
        unrelated = provider.embed_query("appointment booking calendar reschedule")
        assert _cosine(query, relevant) > _cosine(query, unrelated)

    def test_batch_preserves_order_and_empty_is_zero(self):
        provider = DeterministicHashEmbeddingProvider(dimension=16)
        result = provider.embed_documents(["first", "second", ""])
        assert result[0] == provider.embed_query("first")
        assert result[1] == provider.embed_query("second")
        assert result[2] == [0.0] * 16


@pytest.mark.parametrize(
    "vectors,count,dimension",
    [([], 1, 2), ([[1.0]], 1, 2), ([[1.0, float("nan")]], 1, 2), ([[True, 0.0]], 1, 2)],
)
def test_malformed_embedding_is_rejected(vectors, count, dimension):
    with pytest.raises(InvalidEmbeddingError):
        validate_embeddings(vectors, expected_count=count, dimension=dimension)


def test_valid_embeddings_are_converted_to_float():
    assert validate_embeddings([[1, 0]], expected_count=1, dimension=2) == [[1.0, 0.0]]
