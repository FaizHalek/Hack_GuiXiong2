"""Load the fake government documents (data/fake/<type>/*.txt) into the local store.

Each .txt file written by scripts/generate_fake_docs.py is:
  1. parsed for its header (agency, title, reference number, date),
  2. rendered to a PDF, so citations, the PDF viewer and evidence highlighting
     work exactly as for uploaded documents,
  3. registered in SQLite with its document type, reference number, issue date
     and its agency's collection, and
  4. indexed through the normal ingestion pipeline (SQLite + FTS5 + Chroma).

Documents are matched on reference number, so running it again skips what is
already loaded. Usage (from backend/):

  .venv/Scripts/python -m app.demo_seed               # load data/fake
  .venv/Scripts/python -m app.demo_seed --reset       # delete the previously loaded fake documents first
  .venv/Scripts/python -m app.demo_seed --limit 10    # a quick subset (per type)
"""

import argparse
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from app import vectors as vector_store
from app.config import BACKEND_DIR, get_settings
from app.db import (
    SEED_COLLECTIONS,
    collection_description,
    connect,
    fetch_all,
    fetch_one,
    file_path,
    new_id,
    now,
    placeholders,
)
from app.ingestion.pipeline import ingest_batch

DEFAULT_DATA = BACKEND_DIR.parent / "data" / "fake"

# Folder name -> documents.doc_type
FOLDER_TYPES = {
    "policies": "policy",
    "sops": "sop",
    "circulars": "circular",
    "guidelines": "guideline",
    "reports": "report",
    "meeting_minutes": "minutes",
}
EXTRA_COLOURS = ["#475569", "#0d9488", "#9333ea", "#ca8a04"]


@dataclass
class FakeDoc:
    path: Path
    doc_type: str
    agency_name: str
    kind: str  # the document's own heading, e.g. "STANDARD OPERATING PROCEDURE"
    title: str
    reference_no: str
    issued_on: str | None
    header: list[tuple[str, str]] = field(default_factory=list)  # every "Key: value" line, in order
    body: str = ""

    @property
    def agency_code(self) -> str:
        return self.reference_no.split("/")[0].upper() if "/" in self.reference_no else ""


def _iso_date(value: str) -> str | None:
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse(path: Path) -> FakeDoc:
    """Split a generated document into its header fields and body text."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^=+\s*$", text, maxsplit=2, flags=re.MULTILINE)
    agency, header_text, body = (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", "", text)

    header: list[tuple[str, str]] = []
    kind = ""
    for line in header_text.splitlines():
        key, sep, value = line.partition(":")
        if sep and value.strip():
            header.append((key.strip(), value.strip()))
        elif line.strip():
            kind = line.strip()
    fields = dict(header)
    return FakeDoc(
        path=path,
        doc_type=FOLDER_TYPES.get(path.parent.name, "other"),
        agency_name=agency.strip().title(),
        kind=kind,
        title=fields.get("Title", path.stem.replace("_", " ")),
        reference_no=fields.get("Reference No.", ""),
        issued_on=_iso_date(fields.get("Date", "")),
        header=header,
        body=body.strip(),
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=14)
    return {
        "agency": ParagraphStyle("agency", parent=body, fontName="Helvetica-Bold", fontSize=13, alignment=1, spaceAfter=2),
        "kind": ParagraphStyle("kind", parent=body, fontName="Helvetica-Bold", fontSize=11, alignment=1, spaceAfter=6),
        "field": ParagraphStyle("field", parent=body, leading=13),
        "heading": ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", spaceBefore=6),
        "body": body,
        "indent": ParagraphStyle("indent", parent=body, leftIndent=12),
    }


def render_pdf(doc: FakeDoc, out: Path) -> None:
    st = _styles()
    story = [Paragraph(escape(doc.agency_name.upper()), st["agency"])]
    if doc.kind:
        story.append(Paragraph(escape(doc.kind), st["kind"]))
    story.append(HRFlowable(width="100%", thickness=0.8, spaceAfter=6))
    for key, value in doc.header:
        story.append(Paragraph(f"<b>{escape(key)}:</b> {escape(value)}", st["field"]))
    story += [Spacer(1, 4), HRFlowable(width="100%", thickness=0.8, spaceAfter=8)]

    for line in doc.body.splitlines():
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 6))
        elif stripped.isupper() or re.fullmatch(r"\d+\.\s+[A-Z][A-Z \-&/()]+", stripped):
            story.append(Paragraph(escape(stripped), st["heading"]))
        elif line.startswith((" ", "\t")):
            story.append(Paragraph(escape(stripped), st["indent"]))
        else:
            story.append(Paragraph(escape(stripped), st["body"]))

    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(out),
        pagesize=A4,
        title=doc.title,
        author=doc.agency_name,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    ).build(story)


def _collection_ids(conn: sqlite3.Connection, docs: list[FakeDoc]) -> dict[str, str]:
    """Agency code -> label id, creating a collection for any agency not seeded yet."""
    names = {code: name for code, name, _ in SEED_COLLECTIONS}
    colours = {code: colour for code, _, colour in SEED_COLLECTIONS}
    for d in docs:
        names.setdefault(d.agency_code, d.agency_name or d.agency_code)
    ids = {}
    for i, code in enumerate(sorted({d.agency_code for d in docs if d.agency_code})):
        name = names[code]
        row = fetch_one(conn, "select id from labels where name = ?", (name,))
        if row is None:
            row = {"id": new_id()}
            conn.execute(
                "insert into labels (id, name, description, color, created_at) values (?, ?, ?, ?, ?)",
                (row["id"], name, collection_description(code, name), colours.get(code, EXTRA_COLOURS[i % 4]), now()),
            )
        ids[code] = row["id"]
    return ids


def load(data_dir: Path, limit: int | None = None) -> list[FakeDoc]:
    docs = []
    for folder in FOLDER_TYPES:
        files = sorted((data_dir / folder).glob("*.txt"))
        docs += [parse(p) for p in files[:limit]]
    return docs


def reset(docs: list[FakeDoc]) -> int:
    refs = [d.reference_no for d in docs if d.reference_no]
    with connect() as conn:
        rows = fetch_all(conn, f"select id, storage_path from documents where reference_no in ({placeholders(refs)})", refs)
        conn.executemany("delete from documents where id = ?", [(r["id"],) for r in rows])
    for r in rows:
        vector_store.delete_document(r["id"])
        path = file_path(r["storage_path"])
        path.unlink(missing_ok=True)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    return len(rows)


def seed(data_dir: Path = DEFAULT_DATA, limit: int | None = None, log=print) -> dict[str, int]:
    docs = load(data_dir, limit)
    if not docs:
        raise SystemExit(f"No .txt files under {data_dir}/<type>/. Run scripts/generate_fake_docs.py first.")

    with connect() as conn:
        label_ids = _collection_ids(conn, docs)
        existing = {r["reference_no"] for r in fetch_all(conn, "select reference_no from documents where reference_no != ''")}
        admin = fetch_one(conn, "select id from users where role = 'admin' order by created_at limit 1")

    added = skipped = failed = 0
    for n, d in enumerate(docs, start=1):
        if d.reference_no in existing:
            skipped += 1
            continue
        document_id = str(uuid.uuid4())
        storage_path = f"{document_id}/{d.path.stem}.pdf"
        render_pdf(d, file_path(storage_path))
        stamp = now()
        with connect() as conn:
            conn.execute(
                "insert into documents (id, title, filename, storage_path, doc_type, reference_no, issued_on, uploaded_by,"
                " created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    d.title,
                    f"{d.path.stem}.pdf",
                    storage_path,
                    d.doc_type,
                    d.reference_no or None,
                    d.issued_on,
                    admin["id"] if admin else None,
                    stamp,
                    stamp,
                ),
            )
            if d.agency_code in label_ids:
                conn.execute(
                    "insert into document_labels (document_id, label_id) values (?, ?)", (document_id, label_ids[d.agency_code])
                )
        try:
            start = 0
            while not (batch := ingest_batch(document_id, start)).done:
                start = batch.next_start
            added += 1
            existing.add(d.reference_no)
        except Exception as e:  # keep going; the document stays "failed" and can be resumed from the admin page
            failed += 1
            log(f"  ! {d.path.name}: {e}")
        log(f"  [{n}/{len(docs)}] {d.reference_no or d.path.name}  {d.title}")
    return {"added": added, "skipped": skipped, "failed": failed, "collections": len(label_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="folder of <type>/*.txt (default: repo data/fake)")
    parser.add_argument("--reset", action="store_true", help="delete previously loaded fake documents first")
    parser.add_argument("--limit", type=int, default=None, help="load at most N documents per type")
    args = parser.parse_args()

    s = get_settings()
    print(f"Local store: {s.data_dir}  (embeddings: {s.embedding_provider}, collection {vector_store.collection_name()})")
    if args.reset:
        print(f"Removed {reset(load(args.data.resolve()))} previously loaded documents.")
    result = seed(args.data.resolve(), args.limit)
    print(
        f"Done: {result['added']} added, {result['skipped']} already loaded, {result['failed']} failed,"
        f" across {result['collections']} agency collections. Chroma now holds {vector_store.count()} chunk vectors."
    )
    sys.exit(1 if result["failed"] else 0)


if __name__ == "__main__":
    main()
