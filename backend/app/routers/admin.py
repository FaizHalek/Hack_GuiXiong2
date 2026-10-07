import re
import sqlite3
import uuid
from dataclasses import asdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator

from app.auth import hash_password
from app.config import get_settings
from app.db import DOC_TYPES, connect, fetch_all, fetch_one, file_path, new_id, now, placeholders
from app.deps import CurrentUser, require_admin
from app.ingestion.pipeline import ingest_batch
from app.routers.documents import DOC_COLUMNS, attach_labels

router = APIRouter(prefix="/admin", tags=["admin"])

DocType = Literal["policy", "sop", "circular", "guideline", "report", "minutes", "other"]
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    doc_type: DocType = "other"
    reference_no: str | None = Field(default=None, max_length=100)
    issued_on: date | None = None


class LabelAssignment(BaseModel):
    label_ids: list[str]


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "document"
    return stem if stem.lower().endswith(".pdf") else f"{stem}.pdf"


def _known_labels(conn: sqlite3.Connection, label_ids: list[str]) -> list[str]:
    ids = sorted(set(label_ids))
    rows = fetch_all(conn, f"select id from labels where id in ({placeholders(ids)})", ids)
    return [r["id"] for r in rows]


def _set_document_labels(conn: sqlite3.Connection, document_id: str, label_ids: list[str]) -> None:
    conn.execute("delete from document_labels where document_id = ?", (document_id,))
    conn.executemany(
        "insert into document_labels (document_id, label_id) values (?, ?)",
        [(document_id, lid) for lid in _known_labels(conn, label_ids)],
    )


def _require_document(conn: sqlite3.Connection, document_id: str) -> dict:
    doc = fetch_one(conn, "select id, storage_path from documents where id = ?", (document_id,))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _remove_file(storage_path: str) -> None:
    """Delete a stored PDF and its per-document folder."""
    path = file_path(storage_path)
    path.unlink(missing_ok=True)
    if path.parent != get_settings().files_dir.resolve() and path.parent.exists() and not any(path.parent.iterdir()):
        path.parent.rmdir()


def _optional_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "issued_on must be a date (YYYY-MM-DD)") from e


@router.post("/documents", status_code=201)
def create_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=300),
    doc_type: DocType = Form("other"),
    reference_no: str | None = Form(None, max_length=100),
    issued_on: str | None = Form(None),
    label_ids: list[str] = Form([]),
    admin: CurrentUser = Depends(require_admin),
):
    """Save an uploaded PDF to local storage and register it. Indexing is driven by /ingest."""
    head = file.file.read(5)
    if head != b"%PDF-":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files can be uploaded")

    document_id = str(uuid.uuid4())
    storage_path = f"{document_id}/{_safe_filename(file.filename or title)}"
    path = file_path(storage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    size = len(head)
    try:
        with path.open("wb") as out:
            out.write(head)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDFs are limited to 200 MB")
                out.write(chunk)

        stamp = now()
        with connect() as conn:
            conn.execute(
                "insert into documents (id, title, filename, storage_path, doc_type, reference_no, issued_on, uploaded_by,"
                " created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    title.strip(),
                    file.filename or path.name,
                    storage_path,
                    doc_type,
                    (reference_no or "").strip() or None,
                    _optional_date(issued_on),
                    admin.id,
                    stamp,
                    stamp,
                ),
            )
            _set_document_labels(conn, document_id, label_ids)
            doc = fetch_one(conn, f"select {DOC_COLUMNS} from documents d where d.id = ?", (document_id,))
            return attach_labels(conn, [doc])[0]
    except BaseException:
        _remove_file(storage_path)
        raise


@router.post("/documents/{document_id}/ingest")
def ingest(document_id: str, start: int = 0, admin: CurrentUser = Depends(require_admin)):
    if start < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "start must be >= 0")
    with connect() as conn:
        _require_document(conn, document_id)
    try:
        return asdict(ingest_batch(document_id, start))
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Ingestion failed: {e}") from e


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: DocumentUpdate, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        _require_document(conn, document_id)
        conn.execute(
            "update documents set title = ?, doc_type = ?, reference_no = ?, issued_on = ?, updated_at = ? where id = ?",
            (
                body.title.strip(),
                body.doc_type,
                (body.reference_no or "").strip() or None,
                body.issued_on.isoformat() if body.issued_on else None,
                now(),
                document_id,
            ),
        )
        doc = fetch_one(conn, f"select {DOC_COLUMNS} from documents d where d.id = ?", (document_id,))
        return attach_labels(conn, [doc])[0]


@router.put("/documents/{document_id}/labels", status_code=204)
def set_document_labels(document_id: str, body: LabelAssignment, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        _require_document(conn, document_id)
        _set_document_labels(conn, document_id, body.label_ids)


class BulkLabel(BaseModel):
    label_id: str
    document_ids: list[str] = Field(min_length=1)


@router.post("/documents/labels/bulk", status_code=204)
def bulk_add_label(body: BulkLabel, admin: CurrentUser = Depends(require_admin)):
    """Add one label to many documents."""
    with connect() as conn:
        conn.executemany(
            "insert or ignore into document_labels (document_id, label_id)"
            " select d.id, l.id from documents d, labels l where d.id = ? and l.id = ?",
            [(d, body.label_id) for d in body.document_ids],
        )


@router.get("/documents/{document_id}/empty-pages")
def empty_pages(document_id: str, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        rows = fetch_all(
            conn,
            "select page_index from pages where document_id = ? and char_count = 0 order by page_index",
            (document_id,),
        )
    return [r["page_index"] for r in rows]


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        doc = _require_document(conn, document_id)
        conn.execute("delete from documents where id = ?", (document_id,))
    _remove_file(doc["storage_path"])


@router.get("/documents")
def list_all_documents(admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        docs = attach_labels(
            conn,
            fetch_all(
                conn,
                f"select {DOC_COLUMNS}, (select count(*) from pages p where p.document_id = d.id and p.char_count = 0)"
                " as empty_pages from documents d order by d.created_at desc",
            ),
        )
    return docs


@router.get("/doc-types")
def doc_types(admin: CurrentUser = Depends(require_admin)):
    return list(DOC_TYPES)


# ---------------------------------------------------------------------------
# Labels (collections)
# ---------------------------------------------------------------------------


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")


def _unique_name_error(e: sqlite3.IntegrityError) -> HTTPException:
    if "UNIQUE" in str(e):
        return HTTPException(status.HTTP_409_CONFLICT, "A collection with this name already exists")
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/labels")
def list_labels(admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        return fetch_all(
            conn,
            "select l.*,"
            " (select count(*) from document_labels dl where dl.label_id = l.id) as document_count,"
            " (select count(*) from user_label_grants g where g.label_id = l.id) as user_count"
            " from labels l order by l.name",
        )


@router.post("/labels", status_code=201)
def create_label(body: LabelIn, admin: CurrentUser = Depends(require_admin)):
    label_id = new_id()
    try:
        with connect() as conn:
            conn.execute(
                "insert into labels (id, name, description, color, created_at) values (?, ?, ?, ?, ?)",
                (label_id, body.name.strip(), body.description, body.color, now()),
            )
            return fetch_one(conn, "select * from labels where id = ?", (label_id,))
    except sqlite3.IntegrityError as e:
        raise _unique_name_error(e) from e


@router.patch("/labels/{label_id}")
def update_label(label_id: str, body: LabelIn, admin: CurrentUser = Depends(require_admin)):
    try:
        with connect() as conn:
            conn.execute(
                "update labels set name = ?, description = ?, color = ? where id = ?",
                (body.name.strip(), body.description, body.color, label_id),
            )
            label = fetch_one(conn, "select * from labels where id = ?", (label_id,))
    except sqlite3.IntegrityError as e:
        raise _unique_name_error(e) from e
    if label is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found")
    return label


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(label_id: str, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        conn.execute("delete from labels where id = ?", (label_id,))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["admin", "user"] = "user"
    label_ids: list[str] = []

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class RoleIn(BaseModel):
    role: Literal["admin", "user"]


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=200)


def _set_user_labels(conn: sqlite3.Connection, user_id: str, label_ids: list[str]) -> None:
    conn.execute("delete from user_label_grants where user_id = ?", (user_id,))
    conn.executemany(
        "insert into user_label_grants (user_id, label_id) values (?, ?)",
        [(user_id, lid) for lid in _known_labels(conn, label_ids)],
    )


def _require_user(conn: sqlite3.Connection, user_id: str) -> dict:
    user = fetch_one(conn, "select id, role from users where id = ?", (user_id,))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/users")
def list_users(admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        users = fetch_all(conn, "select id, email, role, created_at from users order by email")
        grants: dict[str, list[str]] = {}
        for g in fetch_all(conn, "select user_id, label_id from user_label_grants"):
            grants.setdefault(g["user_id"], []).append(g["label_id"])
    for u in users:
        u["label_ids"] = sorted(grants.get(u["id"], []))
    return users


@router.post("/users", status_code=201)
def create_user(body: UserCreate, admin: CurrentUser = Depends(require_admin)):
    user_id = new_id()
    try:
        with connect() as conn:
            conn.execute(
                "insert into users (id, email, password_hash, role, created_at) values (?, ?, ?, ?, ?)",
                (user_id, body.email, hash_password(body.password), body.role, now()),
            )
            _set_user_labels(conn, user_id, body.label_ids)
    except sqlite3.IntegrityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists") from e
    return {"id": user_id, "email": body.email, "role": body.role, "label_ids": sorted(set(body.label_ids))}


@router.patch("/users/{user_id}")
def set_role(user_id: str, body: RoleIn, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id and body.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove your own admin role")
    with connect() as conn:
        _require_user(conn, user_id)
        conn.execute("update users set role = ? where id = ?", (body.role, user_id))
    return {"id": user_id, "role": body.role}


@router.put("/users/{user_id}/labels", status_code=204)
def set_user_labels(user_id: str, body: LabelAssignment, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        _require_user(conn, user_id)
        _set_user_labels(conn, user_id, body.label_ids)


@router.put("/users/{user_id}/password", status_code=204)
def reset_password(user_id: str, body: PasswordIn, admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        _require_user(conn, user_id)
        conn.execute("update users set password_hash = ? where id = ?", (hash_password(body.password), user_id))


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't delete your own account")
    with connect() as conn:
        _require_user(conn, user_id)
        conn.execute("delete from users where id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


@router.get("/query-logs")
def query_logs(limit: int = 100, verdict: str | None = None, admin: CurrentUser = Depends(require_admin)):
    sql = (
        "select q.id, q.question, q.verdict, q.grounded_score, q.regenerated, q.latency_ms, q.input_tokens,"
        " q.output_tokens, q.created_at, q.label_ids, q.plan, q.retrieved_chunk_ids, q.retrieved, q.first_draft,"
        " u.email as user_email, m.id as message_id, m.content as message_content, m.feedback, m.feedback_note,"
        " m.citations, m.eval"
        " from query_logs q left join users u on u.id = q.user_id left join messages m on m.id = q.message_id"
    )
    params: list = []
    if verdict:
        sql += " where q.verdict = ?"
        params.append(verdict)
    sql += " order by q.created_at desc limit ?"
    params.append(max(1, min(limit, 500)))
    with connect() as conn:
        rows = fetch_all(conn, sql, params)

    logs = []
    for r in rows:
        message_id, email = r.pop("message_id"), r.pop("user_email")
        message = {
            "content": r.pop("message_content"),
            "feedback": r.pop("feedback"),
            "feedback_note": r.pop("feedback_note"),
            "citations": r.pop("citations"),
            "eval": r.pop("eval"),
        }
        logs.append({**r, "profiles": {"email": email} if email else None, "messages": message if message_id else None})
    return logs


@router.get("/stats")
def stats(admin: CurrentUser = Depends(require_admin)):
    with connect() as conn:
        return fetch_one(
            conn,
            "select"
            " (select count(*) from documents) as documents,"
            " (select count(*) from documents where status = 'ready') as documents_ready,"
            " (select count(*) from pages) as pages,"
            " (select count(*) from pages where char_count = 0) as empty_pages,"
            " (select count(*) from users) as users,"
            " (select count(*) from query_logs) as queries,"
            " (select avg(grounded_score) from query_logs) as avg_grounded,"
            " (select count(*) from messages where feedback = 1) as thumbs_up,"
            " (select count(*) from messages where feedback = -1) as thumbs_down,"
            " (select count(*) from query_logs where regenerated = 1) as regenerated,"
            " (select count(*) from query_logs where verdict = 'no_sources') as unanswered",
        )
