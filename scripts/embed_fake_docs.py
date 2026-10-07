"""Embed the fake government documents into a local ChromaDB collection.

Reads every .txt file written by generate_fake_docs.py, splits each document into
overlapping chunks (reusing the backend's chunker), and upserts them into a
persistent Chroma store. Embeddings come from Chroma's default model
(all-MiniLM-L6-v2, run locally with ONNX; downloaded on first use).

Setup (once, from the repo root):
  python -m venv scripts/.venv
  scripts/.venv/Scripts/pip install -r scripts/requirements.txt    # Windows; bin/pip elsewhere

Usage:
  scripts/.venv/Scripts/python scripts/embed_fake_docs.py                 # embed data/fake -> data/chroma
  scripts/.venv/Scripts/python scripts/embed_fake_docs.py --reset         # rebuild the collection
  scripts/.venv/Scripts/python scripts/embed_fake_docs.py --query "How long does procurement approval take?"
  scripts/.venv/Scripts/python scripts/embed_fake_docs.py --query "leave carry-forward" --type policies --agency DDS
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ingestion.chunk import split_page  # noqa: E402

# all-MiniLM-L6-v2 reads at most 256 word pieces (~1,000 characters of English).
MAX_CHUNK_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150
HEADER_FIELDS = {"Title": "title", "Reference No.": "reference", "Date": "date"}


def parse(path: Path, data_dir: Path) -> tuple[dict, str]:
    """Split a generated document into header metadata and body text."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^=+$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) == 3:
        agency_name, header, body = parts[0].strip(), parts[1], parts[2]
    else:  # not in the generator's format: index the whole file
        agency_name, header, body = "", "", text

    meta = {"doc_type": path.parent.name, "source": path.relative_to(data_dir).as_posix(), "agency_name": agency_name.title()}
    for line in header.splitlines():
        key, _, value = line.partition(":")
        if key.strip() in HEADER_FIELDS:
            meta[HEADER_FIELDS[key.strip()]] = value.strip()
    meta.setdefault("title", path.stem)
    meta["agency"] = meta.get("reference", "").split("/")[0]
    return meta, body.strip()


def embed(data_dir: Path, collection: chromadb.Collection) -> None:
    files = sorted(data_dir.glob("*/*.txt"))
    if not files:
        sys.exit(f"No .txt files under {data_dir}/<type>/. Run scripts/generate_fake_docs.py first.")

    ids, docs, metas = [], [], []
    for path in files:
        meta, body = parse(path, data_dir)
        doc_id = hashlib.sha1(meta["source"].encode()).hexdigest()[:16]
        for i, chunk in enumerate(split_page(body, MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS)):
            ids.append(f"{doc_id}-{i}")
            # Prefix the title so each chunk's embedding carries its source, as the backend does.
            docs.append(f"{meta['title']} ({meta['doc_type']})\n{chunk}")
            metas.append({**meta, "chunk_index": i})

    batch = 100
    for start in range(0, len(ids), batch):
        end = start + batch
        collection.upsert(ids=ids[start:end], documents=docs[start:end], metadatas=metas[start:end])
        print(f"  embedded {min(end, len(ids))}/{len(ids)} chunks", end="\r")
    print(f"\nIndexed {len(files)} documents as {len(ids)} chunks. Collection now holds {collection.count()} chunks.")


def query(collection: chromadb.Collection, text: str, n: int, doc_type: str | None, agency: str | None) -> None:
    filters = [{"doc_type": doc_type}] if doc_type else []
    filters += [{"agency": agency.upper()}] if agency else []
    where = None if not filters else filters[0] if len(filters) == 1 else {"$and": filters}

    res = collection.query(query_texts=[text], n_results=n, where=where)
    for rank, (doc, meta, dist) in enumerate(zip(res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True), 1):
        snippet = " ".join(doc.split("\n", 1)[-1].split())[:220]
        print(f"\n{rank}. [{dist:.3f}] {meta['title']}  ({meta['doc_type']}, {meta.get('reference', '')}, {meta.get('date', '')})")
        print(f"   {meta['source']} #chunk {meta['chunk_index']}")
        print(f"   {snippet}...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "fake", help="folder of <type>/*.txt (default data/fake)")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "chroma", help="Chroma persistence folder (default data/chroma)")
    parser.add_argument("--collection", default="gov_docs")
    parser.add_argument("--reset", action="store_true", help="drop the collection before embedding")
    parser.add_argument("--query", help="search the collection instead of embedding")
    parser.add_argument("-n", type=int, default=5, help="results to show for --query")
    parser.add_argument("--type", help="filter --query by document type folder, e.g. policies")
    parser.add_argument("--agency", help="filter --query by agency code, e.g. DDS")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=str(args.db))
    if args.reset and not args.query:
        try:
            client.delete_collection(args.collection)
        except Exception:
            pass  # nothing to reset
    # Cosine distance suits sentence-transformer embeddings (Chroma defaults to L2).
    collection = client.get_or_create_collection(args.collection, metadata={"hnsw:space": "cosine"})

    if args.query:
        query(collection, args.query, args.n, args.type, args.agency)
    else:
        embed(args.data.resolve(), collection)


if __name__ == "__main__":
    main()
