import math

import pytest

from app.config import get_settings
from app.llm import embeddings


@pytest.fixture
def hashed(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "hash")


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_hash_vectors_are_normalised_and_sized(hashed):
    vectors = embeddings.embed(["annual leave entitlement", "procurement threshold"])
    assert len(vectors) == 2
    for v in vectors:
        assert len(v) == get_settings().embedding_dim
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


def test_hash_vectors_reflect_word_overlap(hashed):
    query, related, unrelated = embeddings.embed(
        ["annual leave entitlement for officers", "officers' annual leave entitlement is 25 days", "server patching window"]
    )
    assert cosine(query, related) > cosine(query, unrelated)


def test_empty_input_makes_no_calls(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "nonsense")
    assert embeddings.embed([]) == []


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "nonsense")
    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed(["x"])


def test_chroma_dimension_mismatch_is_reported(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_provider", "chroma")
    monkeypatch.setattr(embeddings, "_chroma_function", lambda: lambda texts: [[1.0, 0.0] for _ in texts])
    with pytest.raises(embeddings.EmbeddingError, match="EMBEDDING_DIM"):
        embeddings.embed(["x"])


def test_chroma_vectors_are_batched_and_normalised(monkeypatch):
    calls = []

    def fake(texts):
        calls.append(len(texts))
        return [[3.0, 4.0] + [0.0] * 382 for _ in texts]

    monkeypatch.setattr(get_settings(), "embedding_provider", "chroma")
    monkeypatch.setattr(get_settings(), "embed_batch_size", 2)
    monkeypatch.setattr(embeddings, "_chroma_function", lambda: fake)
    vectors = embeddings.embed(["a", "b", "c"])
    assert calls == [2, 1]
    assert vectors[0][:2] == pytest.approx([0.6, 0.8])
