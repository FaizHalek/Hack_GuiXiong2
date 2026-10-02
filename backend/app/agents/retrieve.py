"""Hybrid retrieval over the caller's authorised libraries.

Runs `match_chunks` (vector + full-text, RRF-fused, RLS-enforced) once per
sub-query, merges the results, and applies diversity caps so one report or
page can't crowd out the rest.
"""

from collections import defaultdict

from supabase import Client

from app.agents.schemas import QueryPlan, Source
from app.config import get_settings
from app.llm import voyage


def fts_text(keywords: list[str], fallback: str) -> str:
    """websearch_to_tsquery syntax: OR the keywords, quoting multi-word phrases."""
    terms = [f'"{k}"' if " " in k else k for k in (kw.replace('"', "") for kw in keywords) if k]
    return " or ".join(terms) if terms else fallback


def diversify(ranked: list[dict], limit: int, per_page: int, per_doc: int) -> list[dict]:
    page_counts: dict[tuple, int] = defaultdict(int)
    doc_counts: dict[str, int] = defaultdict(int)
    picked = []
    for row in ranked:
        page_key = (row["document_id"], row["page_index"])
        if page_counts[page_key] >= per_page or doc_counts[row["document_id"]] >= per_doc:
            continue
        page_counts[page_key] += 1
        doc_counts[row["document_id"]] += 1
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def retrieve(db: Client, plan: QueryPlan, label_ids: list[str]) -> list[Source]:
    s = get_settings()
    queries = plan.sub_queries
    vectors = voyage.embed(queries, input_type="query")
    keyword_query = fts_text(plan.keywords, "")

    merged: dict[str, dict] = {}
    for query, vector in zip(queries, vectors, strict=True):
        rows = (
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
        )
        for row in rows:
            existing = merged.get(row["chunk_id"])
            if existing:
                existing["score"] += row["score"]  # evidence for several sub-queries ranks higher
            else:
                merged[row["chunk_id"]] = dict(row)

    ranked = sorted(merged.values(), key=lambda r: r["score"], reverse=True)
    picked = diversify(ranked, s.context_chunks, s.max_chunks_per_page, s.max_chunks_per_document)

    return [
        Source(
            id=f"S{i}",
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            page_index=row["page_index"],
            printed_label=row.get("printed_label"),
            content=row["content"],
            score=row["score"],
        )
        for i, row in enumerate(picked, start=1)
    ]
