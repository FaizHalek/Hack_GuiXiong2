import sqlite3

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.auth import FILE_TOKEN_TTL_S, create_file_token, decode_file_token
from app.db import connect, fetch_all, fetch_one, file_path, placeholders
from app.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])

DOC_COLUMNS = (
    "d.id, d.title, d.filename, d.doc_type, d.reference_no, d.issued_on, d.page_count, d.pages_processed,"
    " d.status, d.error, d.created_at"
)


def attach_labels(conn: sqlite3.Connection, docs: list[dict]) -> list[dict]:
    ids = [d["id"] for d in docs]
    labels: dict[str, list[str]] = {i: [] for i in ids}
    for row in fetch_all(
        conn, f"select document_id, label_id from document_labels where document_id in ({placeholders(ids)})", ids
    ):
        labels[row["document_id"]].append(row["label_id"])
    for d in docs:
        d["label_ids"] = sorted(labels[d["id"]])
    return docs


def access_clause(user: CurrentUser) -> tuple[str, list]:
    """SQL condition (on alias `d`) limiting documents to those carrying one of the user's labels."""
    if user.is_admin:
        return "1 = 1", []
    return (
        "exists (select 1 from document_labels dl where dl.document_id = d.id"
        f" and dl.label_id in ({placeholders(user.label_ids)}))",
        list(user.label_ids),
    )


def get_accessible(conn: sqlite3.Connection, user: CurrentUser, document_id: str) -> dict:
    # A document outside the user's collections simply isn't found.
    where, params = access_clause(user)
    doc = fetch_one(
        conn,
        f"select d.id, d.title, d.storage_path, d.page_count, d.status from documents d where d.id = ? and {where}",
        [document_id, *params],
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("")
def list_documents(
    label_id: str | None = None,
    status_: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
):
    where, params = access_clause(user)
    if status_:
        where += " and d.status = ?"
        params.append(status_)
    elif not user.is_admin:
        where += " and d.status = 'ready'"
    with connect() as conn:
        docs = attach_labels(
            conn, fetch_all(conn, f"select {DOC_COLUMNS} from documents d where {where} order by d.created_at desc", params)
        )
    if label_id:
        docs = [d for d in docs if label_id in d["label_ids"]]
    return docs


@router.get("/{document_id}/signed-url")
def signed_url(document_id: str, request: Request, user: CurrentUser = Depends(get_current_user)):
    """A short-lived link to the PDF that works without an Authorization header (PDF viewer, new tab)."""
    with connect() as conn:
        doc = get_accessible(conn, user, document_id)
    url = request.url_for("document_file", document_id=document_id).include_query_params(token=create_file_token(document_id))
    return {"url": str(url), "title": doc["title"], "page_count": doc["page_count"], "expires_in": FILE_TOKEN_TTL_S}


@router.get("/{document_id}/file", name="document_file")
def document_file(document_id: str, token: str):
    try:
        claims = decode_file_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid or expired link: {e}") from e
    if claims.get("doc") != document_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This link is for another document")
    with connect() as conn:
        doc = fetch_one(conn, "select filename, storage_path from documents where id = ?", (document_id,))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = file_path(doc["storage_path"])
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The PDF file is missing from local storage")
    return FileResponse(path, media_type="application/pdf", filename=doc["filename"], content_disposition_type="inline")


@router.get("/{document_id}/pages/{page_index}")
def get_page(document_id: str, page_index: int, user: CurrentUser = Depends(get_current_user)):
    with connect() as conn:
        get_accessible(conn, user, document_id)
        page = fetch_one(
            conn,
            "select page_index, printed_label, text, char_count from pages where document_id = ? and page_index = ?",
            (document_id, page_index),
        )
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    return page
