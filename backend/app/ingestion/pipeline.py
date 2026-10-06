"""Batched ingestion: each call processes one slice of pages so a single request
stays inside Vercel's function time limit. The admin UI calls it in a loop
until `done` is true. Re-running a batch is safe (rows are upserted).
"""

from dataclasses import dataclass

from app.config import get_settings
from app.db import service_client
from app.ingestion.chunk import embedding_text, split_page
from app.ingestion.extract import detect_boilerplate, extract_pages, open_pdf
from app.llm import embeddings


@dataclass
class BatchResult:
    document_id: str
    start: int
    next_start: int
    page_count: int
    done: bool
    empty_pages: list[int]


def ingest_batch(document_id: str, start: int) -> BatchResult:
    s = get_settings()
    db = service_client()
    doc = db.table("documents").select("*").eq("id", document_id).single().execute().data

    try:
        data = db.storage.from_(s.storage_bucket).download(doc["storage_path"])
        reader = open_pdf(data)
        page_count = len(reader.pages)

        if start == 0:
            # Fresh (re-)ingestion: drop previous pages; chunks cascade.
            db.table("pages").delete().eq("document_id", document_id).execute()
            db.table("documents").update(
                {"status": "processing", "page_count": page_count, "pages_processed": 0, "error": None}
            ).eq("id", document_id).execute()

        end = min(start + s.ingest_batch_pages, page_count)
        pages = extract_pages(reader, start, end, detect_boilerplate(reader))

        page_rows = (
            (
                db.table("pages")
                .upsert(
                    [
                        {
                            "document_id": document_id,
                            "page_index": p.page_index,
                            "printed_label": p.printed_label,
                            "text": p.text,
                            "char_count": len(p.text),
                        }
                        for p in pages
                    ],
                    on_conflict="document_id,page_index",
                )
                .execute()
                .data
            )
            if pages
            else []
        )
        page_ids = {row["page_index"]: row["id"] for row in page_rows}

        chunk_rows = []
        for p in pages:
            for ci, content in enumerate(split_page(p.text, s.max_chunk_chars, s.chunk_overlap_chars)):
                chunk_rows.append(
                    {
                        "document_id": document_id,
                        "page_id": page_ids[p.page_index],
                        "page_index": p.page_index,
                        "chunk_index": ci,
                        "content": content,
                    }
                )

        vectors = embeddings.embed([embedding_text(doc["title"], r["page_index"], r["content"]) for r in chunk_rows])
        for row, vec in zip(chunk_rows, vectors, strict=True):
            row["embedding"] = vec
        if chunk_rows:
            db.table("chunks").upsert(chunk_rows, on_conflict="document_id,page_index,chunk_index").execute()

        done = end >= page_count
        db.table("documents").update({"pages_processed": end, "status": "ready" if done else "processing"}).eq(
            "id", document_id
        ).execute()

        return BatchResult(
            document_id=document_id,
            start=start,
            next_start=end,
            page_count=page_count,
            done=done,
            empty_pages=[p.page_index for p in pages if not p.text],
        )
    except Exception as e:
        db.table("documents").update({"status": "failed", "error": str(e)[:1000]}).eq("id", document_id).execute()
        raise
