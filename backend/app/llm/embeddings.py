"""Local text embeddings.

`fastembed` runs a small ONNX sentence-embedding model on the CPU (default
BAAI/bge-small-en-v1.5, 384-dim). The model is downloaded once on first use and
cached by fastembed. Such models read at most 512 tokens, so callers should keep
inputs to roughly 1,800 characters (see Settings.max_chunk_chars). Queries and
documents are embedded the same way.

`hash` is a dependency-free fallback: hashed bag of words and word pairs. It
captures lexical overlap only, which is enough for offline demos and tests.

Vectors are L2-normalised, so a dot product is the cosine similarity.
"""

import hashlib
import math
import re
from functools import lru_cache

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


@lru_cache
def _fastembed_model(name: str):
    try:
        from fastembed import TextEmbedding
    except ImportError as e:
        raise EmbeddingError("fastembed is not installed; pip install fastembed, or set EMBEDDING_PROVIDER=hash") from e
    try:
        return TextEmbedding(model_name=name)
    except Exception as e:
        raise EmbeddingError(f"could not load embedding model {name}: {e}") from e


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def _hash_embed(text: str, dim: int) -> list[float]:
    words = re.findall(r"\w+", text.lower())
    features = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]
    vector = [0.0] * dim
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        vector[bucket] += 1.0 if digest[4] & 1 else -1.0
    return _normalise(vector)


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    if s.embedding_provider == "hash":
        return [_hash_embed(t, s.embedding_dim) for t in texts]
    if s.embedding_provider != "fastembed":
        raise EmbeddingError(f"unknown EMBEDDING_PROVIDER {s.embedding_provider!r}; use fastembed or hash")

    model = _fastembed_model(s.embedding_model)
    vectors = [_normalise([float(x) for x in v]) for v in model.embed(texts, batch_size=s.embed_batch_size)]
    if len(vectors) != len(texts) or any(len(v) != s.embedding_dim for v in vectors):
        raise EmbeddingError(
            f"{s.embedding_model} returned vectors of size {len(vectors[0]) if vectors else 0}; "
            f"set EMBEDDING_DIM to match the model"
        )
    return vectors
