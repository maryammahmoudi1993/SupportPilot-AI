import pytest

from knowledge.errors import ChunkingError
from knowledge.ingestion.chunking import chunk_text


def test_empty_input_returns_no_chunks():
    assert chunk_text("   ", chunk_size=20, overlap=2, minimum_chars=2) == []


def test_small_input_is_one_exact_chunk():
    chunks = chunk_text("hello world", chunk_size=20, overlap=2, minimum_chars=2)
    assert [(item.ordinal, item.text, item.start_offset, item.end_offset) for item in chunks] == [
        (0, "hello world", 0, 11)
    ]


def test_long_input_is_bounded_overlapping_and_deterministic():
    text = "paragraph one has words\n\nparagraph two has more words and content"
    first = chunk_text(text, chunk_size=30, overlap=8, minimum_chars=2)
    second = chunk_text(text, chunk_size=30, overlap=8, minimum_chars=2)
    assert first == second
    assert all(0 < len(item.text) <= 30 for item in first)
    assert [item.ordinal for item in first] == list(range(len(first)))
    assert first[1].start_offset < first[0].end_offset


def test_pathological_no_whitespace_is_split():
    chunks = chunk_text("x" * 55, chunk_size=20, overlap=5, minimum_chars=2)
    assert len(chunks) >= 3
    assert all(item.text for item in chunks)


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, -1), (10, 10), (10, 11)])
def test_invalid_configuration_fails(size, overlap):
    with pytest.raises(ChunkingError):
        chunk_text("content", chunk_size=size, overlap=overlap, minimum_chars=1)
