"""Text embeddings via the `embed` Supabase Edge Function (built-in gte-small).

gte-small reads at most 512 tokens per text, so callers should keep inputs to
roughly 1,800 characters (see Settings.max_chunk_chars). The model is
symmetric: queries and documents are embedded the same way.

Edge Functions have a 2 s CPU budget per request, so texts are sent in small
batches; a batch that fails is split in half and retried, down to one text.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx

from app.config import get_settings


class EmbeddingError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@lru_cache
def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))


def _call(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    url = f"{s.supabase_url.rstrip('/')}/functions/v1/{s.embed_function}"
    headers = {"x-embed-secret": s.embed_secret, "apikey": s.supabase_anon_key}
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = _client().post(url, json={"texts": texts}, headers=headers)
            if response.status_code == 200:
                vectors = response.json()["embeddings"]
                if len(vectors) != len(texts) or any(len(v) != s.embedding_dim for v in vectors):
                    raise EmbeddingError(f"embed function returned unexpected shape for {len(texts)} texts", retryable=False)
                return vectors
            if response.status_code in (400, 401, 403, 404):
                raise EmbeddingError(f"embed function returned {response.status_code}: {response.text[:300]}", retryable=False)
            last_error = EmbeddingError(f"embed function returned {response.status_code}: {response.text[:300]}")
        except httpx.HTTPError as e:
            last_error = e
    raise EmbeddingError(f"embed function failed: {last_error}")


def _embed_batch(texts: list[str]) -> list[list[float]]:
    try:
        return _call(texts)
    except EmbeddingError as e:
        # Likely the CPU budget: retry each half separately. Auth/config errors fail fast.
        if len(texts) == 1 or not e.retryable:
            raise
        mid = len(texts) // 2
        return _embed_batch(texts[:mid]) + _embed_batch(texts[mid:])


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    batches = [texts[i : i + s.embed_batch_size] for i in range(0, len(texts), s.embed_batch_size)]
    with ThreadPoolExecutor(max_workers=s.embed_concurrency) as pool:
        results = list(pool.map(_embed_batch, batches))
    return [vector for batch in results for vector in batch]
