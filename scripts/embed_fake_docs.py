"""Embed the fake government documents into the backend's local store, or query it.

This is a thin wrapper around the backend: documents are loaded by `app.demo_seed`
(rendered to PDF, registered in SQLite with type, reference no., date and agency
collection, then chunked and embedded into the ChromaDB collection under
backend/data/chroma with Chroma's default all-MiniLM-L6-v2 model). `--query` runs a
vector search on that same collection, which is what the app's hybrid search uses.

Setup: use the backend's virtualenv (backend/requirements.txt includes chromadb).

Usage (from the repo root):
  backend/.venv/Scripts/python scripts/embed_fake_docs.py                 # embed data/fake
  backend/.venv/Scripts/python scripts/embed_fake_docs.py --reset         # reload the fake documents
  backend/.venv/Scripts/python scripts/embed_fake_docs.py --query "How long does procurement approval take?"
  backend/.venv/Scripts/python scripts/embed_fake_docs.py --query "leave carry-forward" --type policies --agency DDS
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import demo_seed  # noqa: E402
from app import vectors as vector_store  # noqa: E402
from app.db import connect, fetch_all, placeholders  # noqa: E402
from app.llm import embeddings  # noqa: E402


def query(text: str, n: int, folder: str | None, agency: str | None) -> None:
    where, params = ["d.status = 'ready'"], []
    if folder:
        where.append("d.doc_type = ?")
        params.append(demo_seed.FOLDER_TYPES.get(folder, folder))
    if agency:
        where.append("d.reference_no like ?")
        params.append(f"{agency.upper()}/%")
    with connect() as conn:
        docs = {r["id"]: r for r in fetch_all(conn, f"select * from documents d where {' and '.join(where)}", params)}
    if not docs:
        sys.exit("No matching documents. Load them first: scripts/embed_fake_docs.py")

    ids = vector_store.nearest(embeddings.embed([text])[0], list(docs), n)
    with connect() as conn:
        chunks = {r["id"]: r for r in fetch_all(conn, f"select * from chunks where id in ({placeholders(ids)})", ids)}
    for rank, chunk_id in enumerate(ids, 1):
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        doc = docs[chunk["document_id"]]
        snippet = " ".join(chunk["content"].split())[:220]
        print(f"\n{rank}. {doc['title']}  ({doc['doc_type']}, {doc['reference_no']}, {doc['issued_on']})")
        print(f"   page {chunk['page_index']} #chunk {chunk['chunk_index']}")
        print(f"   {snippet}...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=demo_seed.DEFAULT_DATA, help="folder of <type>/*.txt (default data/fake)")
    parser.add_argument("--reset", action="store_true", help="delete previously loaded fake documents before embedding")
    parser.add_argument("--limit", type=int, default=None, help="load at most N documents per type")
    parser.add_argument("--query", help="search the collection instead of embedding")
    parser.add_argument("-n", type=int, default=5, help="results to show for --query")
    parser.add_argument("--type", help="filter --query by document type folder, e.g. policies")
    parser.add_argument("--agency", help="filter --query by agency code, e.g. DDS")
    args = parser.parse_args()

    if args.query:
        query(args.query, args.n, args.type, args.agency)
        return
    if args.reset:
        print(f"Removed {demo_seed.reset(demo_seed.load(args.data.resolve()))} previously loaded documents.")
    result = demo_seed.seed(args.data.resolve(), args.limit)
    print(f"Done: {result['added']} added, {result['skipped']} already loaded, {result['failed']} failed.")
    print(f"Chroma collection {vector_store.collection_name()} now holds {vector_store.count()} chunk vectors.")


if __name__ == "__main__":
    main()
