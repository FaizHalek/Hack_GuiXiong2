"""Local text embeddings.

`chroma` uses ChromaDB's built-in embedding function, all-MiniLM-L6-v2 (384-dim),
run on the CPU with ONNX. The model is downloaded once on first use and cached by
Chroma (~/.cache/chroma). It reads at most 256 word pieces, so callers should keep
inputs to roughly 1,000 characters (see Settings.max_chunk_chars). Queries and
documents are embedded the same way.

`hash` is a dependency-free fallback: hashed bag of words and word pairs. It
captures lexical overlap only, which is enough for offline demos and tests.

Vectors are L2-normalised, so cosine distance in the vector store is 1 - dot product.
"""

import hashlib
import math
import re
from functools import lru_cache

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


@lru_cache
def _chroma_function():
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    except ImportError as e:
        raise EmbeddingError("chromadb is not installed; pip install chromadb, or set EMBEDDING_PROVIDER=hash") from e
    return DefaultEmbeddingFunction()


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
    if s.embedding_provider != "chroma":
        raise EmbeddingError(f"unknown EMBEDDING_PROVIDER {s.embedding_provider!r}; use chroma or hash")

    function = _chroma_function()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), s.embed_batch_size):
        try:
            batch = function(texts[start : start + s.embed_batch_size])
        except Exception as e:
            raise EmbeddingError(f"Chroma embedding failed: {e}") from e
        vectors += [_normalise([float(x) for x in v]) for v in batch]
    if len(vectors) != len(texts) or any(len(v) != s.embedding_dim for v in vectors):
        raise EmbeddingError(
            f"the embedding function returned vectors of size {len(vectors[0]) if vectors else 0}; "
            "set EMBEDDING_DIM to match the model"
        )
    return vectors
