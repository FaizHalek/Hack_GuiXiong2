from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import get_settings
from app.db import service_client
from app.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])

DOC_FIELDS = "id,title,filename,page_count,pages_processed,status,error,created_at,document_labels(label_id)"


def flatten_labels(doc: dict) -> dict:
    doc["label_ids"] = [dl["label_id"] for dl in doc.pop("document_labels", []) or []]
    return doc


@router.get("")
def list_documents(
    label_id: str | None = None,
    status_: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
):
    q = user.db.table("documents").select(DOC_FIELDS).order("created_at", desc=True)
    if status_:
        q = q.eq("status", status_)
    elif not user.is_admin:
        q = q.eq("status", "ready")
    docs = [flatten_labels(d) for d in q.execute().data]
    if label_id:
        docs = [d for d in docs if label_id in d["label_ids"]]
    return docs


def _get_accessible(user: CurrentUser, document_id: str) -> dict:
    # RLS decides visibility; a document outside the user's grants simply isn't found.
    res = (
        user.db.table("documents")
        .select("id,title,storage_path,page_count,status")
        .eq("id", document_id)
        .maybe_single()
        .execute()
    )
    if res is None or not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return res.data


@router.get("/{document_id}/signed-url")
def signed_url(document_id: str, user: CurrentUser = Depends(get_current_user)):
    doc = _get_accessible(user, document_id)
    signed = service_client().storage.from_(get_settings().storage_bucket).create_signed_url(doc["storage_path"], 3600)
    url = signed.get("signedURL") or signed.get("signedUrl")
    return {"url": url, "title": doc["title"], "page_count": doc["page_count"]}


@router.get("/{document_id}/pages/{page_index}")
def get_page(document_id: str, page_index: int, user: CurrentUser = Depends(get_current_user)):
    res = (
        user.db.table("pages")
        .select("page_index,printed_label,text,char_count")
        .eq("document_id", document_id)
        .eq("page_index", page_index)
        .maybe_single()
        .execute()
    )
    if res is None or not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    return res.data
