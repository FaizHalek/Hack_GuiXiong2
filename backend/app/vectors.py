"""Vector index: a persistent ChromaDB collection under DATA_DIR/chroma.

SQLite stays the source of truth for documents, pages, chunk text, keyword
search and access control. Chroma only holds one vector per chunk, keyed by the
SQLite chunk id, with the document id and page in its metadata so searches can
be limited to the documents a user may see and deleted per document.

Each embedding provider/model gets its own collection, so switching models never
mixes vector sizes; documents need a re-index to appear in the new collection.
"""

import re
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings


@lru_cache
def _client(path: Path) -> chromadb.ClientAPI:
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False))


def collection_name() -> str:
    provider = get_settings().embedding_provider
    model = "all-minilm-l6-v2" if provider == "chroma" else provider
    return re.sub(r"[^a-z0-9]+", "-", f"chunks-{model}".lower()).strip("-")[:63]


def _collection() -> chromadb.Collection:
    s = get_settings()
    # Vectors are computed by app.llm.embeddings and passed in, so no embedding function here.
    return _client(s.chroma_dir).get_or_create_collection(
        collection_name(), embedding_function=None, metadata={"hnsw:space": "cosine"}
    )


def upsert(rows: list[dict], vectors: list[list[float]]) -> None:
    """rows carry id, document_id, page_index and chunk_index (the SQLite chunk row)."""
    if not rows:
        return
    _collection().upsert(
        ids=[r["id"] for r in rows],
        embeddings=vectors,
        metadatas=[{key: r[key] for key in ("document_id", "page_index", "chunk_index")} for r in rows],
    )


def delete_ids(ids: list[str]) -> None:
    if ids:
        _collection().delete(ids=ids)


def delete_document(document_id: str) -> None:
    _collection().delete(where={"document_id": document_id})


def nearest(vector: list[float], document_ids: list[str], n: int) -> list[str]:
    """Chunk ids closest to `vector`, restricted to `document_ids`, best first."""
    if not document_ids:
        return []
    collection = _collection()
    if collection.count() == 0:
        return []
    where = {"document_id": document_ids[0]} if len(document_ids) == 1 else {"document_id": {"$in": document_ids}}
    result = collection.query(query_embeddings=[vector], n_results=n, where=where, include=["distances"])
    return result["ids"][0] if result["ids"] else []


def count() -> int:
    return _collection().count()
