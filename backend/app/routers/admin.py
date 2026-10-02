import re
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import service_client
from app.deps import CurrentUser, require_admin
from app.ingestion.pipeline import ingest_batch
from app.routers.documents import DOC_FIELDS, flatten_labels

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    filename: str = Field(min_length=1, max_length=300)
    label_ids: list[str] = []


class DocumentUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class LabelAssignment(BaseModel):
    label_ids: list[str]


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "document"
    return stem if stem.lower().endswith(".pdf") else f"{stem}.pdf"


def _set_document_labels(admin: CurrentUser, document_id: str, label_ids: list[str]) -> None:
    admin.db.table("document_labels").delete().eq("document_id", document_id).execute()
    if label_ids:
        admin.db.table("document_labels").insert(
            [{"document_id": document_id, "label_id": lid} for lid in sorted(set(label_ids))]
        ).execute()


@router.post("/documents", status_code=201)
def create_document(body: DocumentCreate, admin: CurrentUser = Depends(require_admin)):
    """Register a document and return a signed URL the browser uploads the PDF to."""
    document_id = str(uuid.uuid4())
    storage_path = f"{document_id}/{_safe_filename(body.filename)}"
    doc = (
        admin.db.table("documents")
        .insert(
            {
                "id": document_id,
                "title": body.title,
                "filename": body.filename,
                "storage_path": storage_path,
                "uploaded_by": admin.id,
            }
        )
        .execute()
        .data[0]
    )
    _set_document_labels(admin, document_id, body.label_ids)
    upload = service_client().storage.from_(get_settings().storage_bucket).create_signed_upload_url(storage_path)
    return {"document": doc, "upload": {"path": upload["path"], "token": upload["token"], "signed_url": upload["signed_url"]}}


@router.post("/documents/{document_id}/ingest")
def ingest(document_id: str, start: int = 0, admin: CurrentUser = Depends(require_admin)):
    if start < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "start must be >= 0")
    try:
        return asdict(ingest_batch(document_id, start))
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Ingestion failed: {e}") from e


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: DocumentUpdate, admin: CurrentUser = Depends(require_admin)):
    return admin.db.table("documents").update({"title": body.title}).eq("id", document_id).execute().data


@router.put("/documents/{document_id}/labels", status_code=204)
def set_document_labels(document_id: str, body: LabelAssignment, admin: CurrentUser = Depends(require_admin)):
    _set_document_labels(admin, document_id, body.label_ids)


class BulkLabel(BaseModel):
    label_id: str
    document_ids: list[str] = Field(min_length=1)


@router.post("/documents/labels/bulk", status_code=204)
def bulk_add_label(body: BulkLabel, admin: CurrentUser = Depends(require_admin)):
    """Add one label to many documents."""
    admin.db.table("document_labels").upsert(
        [{"document_id": d, "label_id": body.label_id} for d in body.document_ids], on_conflict="document_id,label_id"
    ).execute()


@router.get("/documents/{document_id}/empty-pages")
def empty_pages(document_id: str, admin: CurrentUser = Depends(require_admin)):
    rows = (
        admin.db.table("pages")
        .select("page_index")
        .eq("document_id", document_id)
        .eq("char_count", 0)
        .order("page_index")
        .execute()
        .data
    )
    return [r["page_index"] for r in rows]


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, admin: CurrentUser = Depends(require_admin)):
    res = admin.db.table("documents").select("storage_path").eq("id", document_id).maybe_single().execute()
    if res is None or not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    service_client().storage.from_(get_settings().storage_bucket).remove([res.data["storage_path"]])
    admin.db.table("documents").delete().eq("id", document_id).execute()


@router.get("/documents")
def list_all_documents(admin: CurrentUser = Depends(require_admin)):
    docs = admin.db.table("documents").select(DOC_FIELDS).order("created_at", desc=True).execute().data
    empty = admin.db.table("pages").select("document_id").eq("char_count", 0).execute().data
    empty_counts: dict[str, int] = {}
    for row in empty:
        empty_counts[row["document_id"]] = empty_counts.get(row["document_id"], 0) + 1
    return [{**flatten_labels(d), "empty_pages": empty_counts.get(d["id"], 0)} for d in docs]


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")


@router.get("/labels")
def list_labels(admin: CurrentUser = Depends(require_admin)):
    labels = admin.db.table("labels").select("*, document_labels(count), user_label_grants(count)").order("name").execute().data
    for label in labels:
        label["document_count"] = (label.pop("document_labels") or [{"count": 0}])[0]["count"]
        label["user_count"] = (label.pop("user_label_grants") or [{"count": 0}])[0]["count"]
    return labels


@router.post("/labels", status_code=201)
def create_label(body: LabelIn, admin: CurrentUser = Depends(require_admin)):
    return admin.db.table("labels").insert(body.model_dump()).execute().data[0]


@router.patch("/labels/{label_id}")
def update_label(label_id: str, body: LabelIn, admin: CurrentUser = Depends(require_admin)):
    return admin.db.table("labels").update(body.model_dump()).eq("id", label_id).execute().data


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(label_id: str, admin: CurrentUser = Depends(require_admin)):
    admin.db.table("labels").delete().eq("id", label_id).execute()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class InviteIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["admin", "user"] = "user"
    label_ids: list[str] = []


class RoleIn(BaseModel):
    role: Literal["admin", "user"]


def _set_user_labels(admin: CurrentUser, user_id: str, label_ids: list[str]) -> None:
    admin.db.table("user_label_grants").delete().eq("user_id", user_id).execute()
    if label_ids:
        admin.db.table("user_label_grants").insert(
            [{"user_id": user_id, "label_id": lid} for lid in sorted(set(label_ids))]
        ).execute()


@router.get("/users")
def list_users(admin: CurrentUser = Depends(require_admin)):
    users = (
        admin.db.table("profiles").select("id,email,role,created_at,user_label_grants(label_id)").order("email").execute().data
    )
    for u in users:
        u["label_ids"] = [g["label_id"] for g in u.pop("user_label_grants", []) or []]
    return users


@router.post("/users/invite", status_code=201)
def invite_user(body: InviteIn, admin: CurrentUser = Depends(require_admin)):
    try:
        res = service_client().auth.admin.invite_user_by_email(body.email, {"redirect_to": get_settings().frontend_origin})
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invite failed: {e}") from e
    user_id = res.user.id
    # The profile row is created by the on_auth_user_created trigger.
    admin.db.table("profiles").update({"role": body.role}).eq("id", user_id).execute()
    _set_user_labels(admin, user_id, body.label_ids)
    return {"id": user_id, "email": body.email, "role": body.role, "label_ids": body.label_ids}


@router.patch("/users/{user_id}")
def set_role(user_id: str, body: RoleIn, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id and body.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't remove your own admin role")
    return admin.db.table("profiles").update({"role": body.role}).eq("id", user_id).execute().data


@router.put("/users/{user_id}/labels", status_code=204)
def set_user_labels(user_id: str, body: LabelAssignment, admin: CurrentUser = Depends(require_admin)):
    _set_user_labels(admin, user_id, body.label_ids)


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


@router.get("/query-logs")
def query_logs(limit: int = 100, verdict: str | None = None, admin: CurrentUser = Depends(require_admin)):
    q = (
        admin.db.table("query_logs")
        .select(
            "id,question,verdict,grounded_score,regenerated,latency_ms,input_tokens,output_tokens,created_at,"
            "profiles(email),messages(content,feedback,feedback_note,citations)"
        )
        .order("created_at", desc=True)
        .limit(min(limit, 500))
    )
    if verdict:
        q = q.eq("verdict", verdict)
    return q.execute().data


@router.get("/stats")
def stats(admin: CurrentUser = Depends(require_admin)):
    return admin.db.rpc("admin_stats", {}).execute().data
