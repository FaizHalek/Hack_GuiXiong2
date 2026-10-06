"""Hybrid retrieval over the caller's authorised libraries.

Runs `match_chunks` (vector + full-text, RRF-fused, RLS-enforced) once per
sub-query. Chunks are small (the embedding model reads 512 tokens), so results
are rolled up to pages: a page scores its best chunk per sub-query, summed
across sub-queries, and the Answer Agent receives the whole page text. A
per-report cap keeps one report from crowding out the rest.
"""

from collections import defaultdict

from supabase import Client

from app.agents.schemas import QueryPlan, Source
from app.config import get_settings
from app.llm import embeddings


def fts_text(keywords: list[str], fallback: str) -> str:
    """websearch_to_tsquery syntax: OR the keywords, quoting multi-word phrases."""
    terms = [f'"{k}"' if " " in k else k for k in (kw.replace('"', "") for kw in keywords) if k]
    return " or ".join(terms) if terms else fallback


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


def retrieve(db: Client, plan: QueryPlan, label_ids: list[str]) -> list[Source]:
    s = get_settings()
    queries = plan.sub_queries
    vectors = embeddings.embed(queries)
    keyword_query = fts_text(plan.keywords, "")

    results = [
        db.rpc(
            "match_chunks",
            {
                "query_embedding": vector,
                "query_text": keyword_query or query,
                "label_ids": label_ids,
                "match_count": s.match_count,
            },
        )
        .execute()
        .data
        or []
        for query, vector in zip(queries, vectors, strict=True)
    ]
    picked = cap_per_document(rank_pages(results), s.context_pages, s.max_pages_per_document)

    return [
        Source(
            id=f"S{i}",
            chunk_id=page["chunk_id"],
            document_id=page["document_id"],
            document_title=page["document_title"],
            page_index=page["page_index"],
            printed_label=page.get("printed_label"),
            content=page.get("page_text") or page["content"],
            score=page["score"],
            matched=page["content"],
        )
        for i, page in enumerate(picked, start=1)
    ]
