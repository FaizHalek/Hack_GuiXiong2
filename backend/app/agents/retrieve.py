"""Hybrid retrieval over the caller's authorised collections.

Each sub-query runs a vector search (cosine similarity in the local ChromaDB
collection, app/vectors.py) and a keyword search (SQLite FTS5, BM25), fused with
Reciprocal Rank Fusion. Only documents that are ready and carry one of `label_ids` are
searched; the caller must pass labels already checked by `authorised_labels`.

Chunks are small (the embedding model reads ~256 word pieces), so results are rolled
up to pages: a page scores its best chunk per sub-query, summed across
sub-queries, and the Answer Agent receives the whole page text. A per-document
cap keeps one document from crowding out the rest.
"""

import re
import sqlite3
from collections import defaultdict

from app import vectors as vector_store
from app.agents.schemas import QueryPlan, Source
from app.config import get_settings
from app.db import connect, fetch_all, placeholders
from app.llm import embeddings

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i in is it its me my of on or our should the their "
    "there this to was we what when where which who why will with you your".split()
)


def fts_text(keywords: list[str], fallback: str) -> str:
    """FTS5 MATCH syntax: OR the keywords as quoted phrases; without keywords, OR the fallback's content words."""
    terms = [k.strip() for k in keywords if k.strip()]
    if not terms:
        terms = [w for w in re.findall(r"\w+", fallback.lower()) if len(w) > 1 and w not in STOPWORDS]
    quoted = dict.fromkeys('"' + t.replace('"', '""') + '"' for t in terms)
    return " OR ".join(quoted)


PageKey = tuple[str, int]


def rank_pages(results_per_query: list[list[dict]]) -> list[dict]:
    """Roll chunk hits up to pages; returns page rows sorted by score."""
    pages: dict[PageKey, dict] = {}
    for rows in results_per_query:
        best_this_query: dict[PageKey, float] = {}
        for row in rows:
            key = (row["document_id"], row["page_index"])
            page = pages.setdefault(key, {**row, "score": 0.0, "best_chunk_score": -1.0})
            if row["score"] > page["best_chunk_score"]:
                page.update(chunk_id=row["chunk_id"], content=row["content"], best_chunk_score=row["score"])
            best_this_query[key] = max(best_this_query.get(key, 0.0), row["score"])
        for key, score in best_this_query.items():
            pages[key]["score"] += score  # pages relevant to several sub-queries rank higher
    return sorted(pages.values(), key=lambda p: p["score"], reverse=True)


def cap_per_document(pages: list[dict], limit: int, per_doc: int) -> list[dict]:
    doc_counts: dict[str, int] = defaultdict(int)
    picked = []
    for page in pages:
        if doc_counts[page["document_id"]] >= per_doc:
            continue
        doc_counts[page["document_id"]] += 1
        picked.append(page)
        if len(picked) >= limit:
            break
    return picked


def rrf(rankings: list[list[str]], k: int) -> dict[str, float]:
    """Reciprocal Rank Fusion of several ranked id lists."""
    scores: dict[str, float] = defaultdict(float)
    for ranked in rankings:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return scores


def _keyword_search(conn: sqlite3.Connection, query: str, doc_ids: list[str], n: int) -> list[str]:
    if not query:
        return []
    try:
        rows = conn.execute(
            "select c.id from chunks_fts f join chunks c on c.rowid = f.rowid"
            f" where chunks_fts match ? and c.document_id in ({placeholders(doc_ids)})"
            " order by bm25(chunks_fts) limit ?",
            [query, *doc_ids, n],
        ).fetchall()
    except sqlite3.OperationalError:  # malformed MATCH expression; the vector search still runs
        return []
    return [r["id"] for r in rows]


def _chunk_rows(conn: sqlite3.Connection, scores: dict[str, float], n: int) -> list[dict]:
    top = sorted(scores, key=scores.get, reverse=True)[:n]
    rows = fetch_all(
        conn,
        "select c.id as chunk_id, c.document_id, d.title as document_title, d.doc_type, d.reference_no, d.issued_on,"
        " c.page_index, p.printed_label, c.content, p.text as page_text"
        " from chunks c join documents d on d.id = c.document_id left join pages p on p.id = c.page_id"
        f" where c.id in ({placeholders(top)})",
        top,
    )
    for row in rows:
        row["score"] = scores[row["chunk_id"]]
    return sorted(rows, key=lambda r: r["score"], reverse=True)


def search(conn: sqlite3.Connection, queries: list[str], vectors: list[list[float]], keyword_query: str, label_ids: list[str]):
    """Chunk hits per sub-query, each list shaped like rank_pages expects."""
    s = get_settings()
    doc_ids = [
        r["id"]
        for r in fetch_all(
            conn,
            "select d.id from documents d where d.status = 'ready' and exists (select 1 from document_labels dl"
            f" where dl.document_id = d.id and dl.label_id in ({placeholders(label_ids)}))",
            label_ids,
        )
    ]
    if not doc_ids:
        return [[] for _ in queries]
    depth = s.match_count * 4
    results = []
    for query, vector in zip(queries, vectors, strict=True):
        scores = rrf(
            [
                vector_store.nearest(vector, doc_ids, depth),
                _keyword_search(conn, keyword_query or fts_text([], query), doc_ids, depth),
            ],
            s.rrf_k,
        )
        results.append(_chunk_rows(conn, scores, s.match_count))
    return results


def retrieve(plan: QueryPlan, label_ids: list[str]) -> list[Source]:
    s = get_settings()
    queries = plan.sub_queries or [plan.standalone_question]
    if not label_ids:
        return []
    vectors = embeddings.embed(queries)
    keyword_query = fts_text(plan.keywords, "")

    with connect() as conn:
        results = search(conn, queries, vectors, keyword_query, label_ids)
    picked = cap_per_document(rank_pages(results), s.context_pages, s.max_pages_per_document)

    return [
        Source(
            id=f"S{i}",
            chunk_id=page["chunk_id"],
            document_id=page["document_id"],
            document_title=page["document_title"],
            doc_type=page.get("doc_type"),
            reference_no=page.get("reference_no"),
            issued_on=page.get("issued_on"),
            page_index=page["page_index"],
            printed_label=page.get("printed_label"),
            content=page.get("page_text") or page["content"],
            score=page["score"],
            matched=page["content"],
        )
        for i, page in enumerate(picked, start=1)
    ]
