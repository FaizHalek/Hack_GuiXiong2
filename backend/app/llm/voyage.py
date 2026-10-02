"""Voyage AI embeddings."""

from functools import lru_cache
from typing import Literal

import voyageai

from app.config import get_settings


@lru_cache
def client() -> voyageai.Client:
    return voyageai.Client(api_key=get_settings().voyage_api_key or None, max_retries=3)


def embed(texts: list[str], input_type: Literal["document", "query"]) -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), s.embed_batch_size):
        batch = texts[i : i + s.embed_batch_size]
        result = client().embed(
            batch,
            model=s.embedding_model,
            input_type=input_type,
            output_dimension=s.embedding_dim,
        )
        out.extend(result.embeddings)
    return out
