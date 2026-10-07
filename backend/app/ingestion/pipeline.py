"""Batched ingestion: each call processes one slice of pages, so the admin UI can
show progress and resume a failed document. The UI calls it in a loop until
`done` is true. Re-running a batch is safe (rows are upserted).
"""

from dataclasses import dataclass

from app import vectors as vector_store
from app.config import get_settings
from app.db import connect, fetch_one, file_path, new_id, now
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


def _set_status(document_id: str, **fields) -> None:
    columns = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"update documents set {columns}, updated_at = ? where id = ?", [*fields.values(), now(), document_id])


def ingest_batch(document_id: str, start: int) -> BatchResult:
    s = get_settings()
    with connect() as conn:
        doc = fetch_one(conn, "select id, title, storage_path from documents where id = ?", (document_id,))
    if doc is None:
        raise LookupError(f"document {document_id} not found")

    try:
        reader = open_pdf(file_path(doc["storage_path"]).read_bytes())
        page_count = len(reader.pages)

        if start == 0:
            # Fresh (re-)ingestion: drop previous pages; chunks cascade.
            with connect() as conn:
                conn.execute("delete from pages where document_id = ?", (document_id,))
            vector_store.delete_document(document_id)
            _set_status(document_id, status="processing", page_count=page_count, pages_processed=0, error=None)

        end = min(start + s.ingest_batch_pages, page_count)
        pages = extract_pages(reader, start, end, detect_boilerplate(reader))

        chunk_rows = [
            {"page_index": p.page_index, "chunk_index": ci, "content": content}
            for p in pages
            for ci, content in enumerate(split_page(p.text, s.max_chunk_chars, s.chunk_overlap_chars))
        ]
        # Embed before writing anything, so a model failure leaves the batch untouched.
        vectors = embeddings.embed([embedding_text(doc["title"], r["page_index"], r["content"]) for r in chunk_rows])

        with connect() as conn:
            page_ids = {}
            stale_chunk_ids: list[str] = []
            for p in pages:
                conn.execute(
                    "insert into pages (id, document_id, page_index, printed_label, text, char_count)"
                    " values (?, ?, ?, ?, ?, ?)"
                    " on conflict (document_id, page_index) do update set"
                    " printed_label = excluded.printed_label, text = excluded.text, char_count = excluded.char_count",
                    (new_id(), document_id, p.page_index, p.printed_label, p.text, len(p.text)),
                )
                page_ids[p.page_index] = conn.execute(
                    "select id from pages where document_id = ? and page_index = ?", (document_id, p.page_index)
                ).fetchone()[0]
                # A re-run batch may produce fewer chunks than before; drop the old ones for this page.
                stale_chunk_ids += [
                    r[0] for r in conn.execute("select id from chunks where page_id = ?", (page_ids[p.page_index],))
                ]
                conn.execute("delete from chunks where page_id = ?", (page_ids[p.page_index],))

            for r in chunk_rows:
                r.update(id=new_id(), document_id=document_id, page_id=page_ids[r["page_index"]])
            conn.executemany(
                "insert into chunks (id, document_id, page_id, page_index, chunk_index, content)"
                " values (:id, :document_id, :page_id, :page_index, :chunk_index, :content)",
                chunk_rows,
            )
            # Inside the transaction: if the vector store fails, the SQLite rows roll back too.
            vector_store.delete_ids(stale_chunk_ids)
            vector_store.upsert(chunk_rows, vectors)

        done = end >= page_count
        _set_status(document_id, pages_processed=end, status="ready" if done else "processing")

        return BatchResult(
            document_id=document_id,
            start=start,
            next_start=end,
            page_count=page_count,
            done=done,
            empty_pages=[p.page_index for p in pages if not p.text],
        )
    except Exception as e:
        _set_status(document_id, status="failed", error=str(e)[:1000])
        raise
