"""End-to-end checks of the local (SQLite + filesystem) storage through the API.

These replace the old database RLS tests: access control now lives in the API,
so every rule is exercised here as a request from an admin or a regular user.
"""

import pytest
from fastapi.testclient import TestClient

from app import vectors as vector_store
from app.agents import pipeline
from app.agents.retrieve import retrieve
from app.agents.schemas import QueryPlan
from app.db import connect
from app.main import app
from tests.conftest import make_pdf

client = TestClient(app)


def login(email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(local_store):
    return login(local_store.demo_admin_email, local_store.demo_admin_password)


@pytest.fixture
def officer(local_store):
    return login(local_store.demo_user_email, local_store.demo_user_password)


def labels_by_name(headers) -> dict[str, str]:
    return {label["name"]: label["id"] for label in client.get("/admin/labels", headers=headers).json()}


def upload(headers, pdf: bytes, title: str, label_ids: list[str], **fields) -> dict:
    r = client.post(
        "/admin/documents",
        headers=headers,
        files={"file": ("circular.pdf", pdf, "application/pdf")},
        data={"title": title, "label_ids": label_ids, **fields},
    )
    assert r.status_code == 201, r.text
    return r.json()


def ingest_all(headers, document_id: str) -> None:
    start = 0
    while True:
        r = client.post(f"/admin/documents/{document_id}/ingest?start={start}", headers=headers)
        assert r.status_code == 200, r.text
        if r.json()["done"]:
            return
        start = r.json()["next_start"]


HEALTH = "Department of Health and Wellbeing"
DIGITAL = "Department of Digital Services"
FINANCE = "Department of Finance and Treasury"
WORKS = "Ministry of Public Works"

LEAVE_PDF = make_pdf(
    [
        ["Circular on annual leave", "Officers are entitled to 25 days of annual leave per year."],
        ["Carry forward", "Unused leave of up to 10 days may be carried forward to the next year."],
    ],
    header="HUMAN RESOURCES DIVISION",
)
PROCUREMENT_PDF = make_pdf(
    [["Procurement thresholds", "Purchases above RM50,000 require a quotation committee."]],
    header="FINANCE DIVISION",
)


def test_login_rejects_wrong_password(local_store):
    assert client.post("/auth/login", json={"email": local_store.demo_admin_email, "password": "nope"}).status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_seeded_accounts_and_collections(admin, officer):
    me = client.get("/me", headers=admin).json()
    assert me["role"] == "admin" and len(me["labels"]) == 6
    me = client.get("/me", headers=officer).json()
    assert me["role"] == "user"
    assert sorted(label["name"] for label in me["labels"]) == [DIGITAL, HEALTH]


def test_upload_ingest_and_access_control(admin, officer):
    labels = labels_by_name(admin)
    leave = upload(admin, LEAVE_PDF, "Leave Circular", [labels[HEALTH]], doc_type="circular", issued_on="2024-03-01")
    proc = upload(admin, PROCUREMENT_PDF, "Procurement SOP", [labels[FINANCE]], doc_type="sop")
    assert leave["doc_type"] == "circular" and leave["issued_on"] == "2024-03-01"
    assert leave["label_ids"] == [labels[HEALTH]]

    # not ready yet: hidden from users
    assert client.get("/documents", headers=officer).json() == []
    ingest_all(admin, leave["id"])
    ingest_all(admin, proc["id"])

    visible = client.get("/documents", headers=officer).json()
    assert [d["title"] for d in visible] == ["Leave Circular"]
    assert {d["title"] for d in client.get("/documents", headers=admin).json()} == {"Leave Circular", "Procurement SOP"}

    # pages and PDFs outside the officer's collections are not found
    assert client.get(f"/documents/{proc['id']}/pages/1", headers=officer).status_code == 404
    assert client.get(f"/documents/{proc['id']}/signed-url", headers=officer).status_code == 404
    page = client.get(f"/documents/{leave['id']}/pages/1", headers=officer).json()
    assert "25 days of annual leave" in page["text"]

    # the signed link serves the PDF without a bearer token, and only for its own document
    url = client.get(f"/documents/{leave['id']}/signed-url", headers=officer).json()["url"]
    pdf = client.get(url)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    token = url.split("token=")[1]
    assert client.get(f"/documents/{proc['id']}/file?token={token}").status_code == 403
    assert client.get(f"/documents/{leave['id']}/file?token=forged").status_code == 401


def test_hybrid_search_respects_labels(admin):
    labels = labels_by_name(admin)
    leave = upload(admin, LEAVE_PDF, "Leave Circular", [labels[HEALTH]])
    proc = upload(admin, PROCUREMENT_PDF, "Procurement SOP", [labels[FINANCE]])
    ingest_all(admin, leave["id"])
    ingest_all(admin, proc["id"])

    plan = QueryPlan(
        needs_retrieval=True, standalone_question="How much leave can be carried forward?", sub_queries=["carry forward leave"]
    )
    sources = retrieve(plan, [labels[HEALTH]])
    assert sources and sources[0].document_title == "Leave Circular" and sources[0].page_index == 2
    assert all(s.document_id == leave["id"] for s in sources)

    # the procurement document only appears when its collection is searched
    plan = QueryPlan(needs_retrieval=True, standalone_question="quotation committee", sub_queries=["quotation committee"])
    assert retrieve(plan, [labels[HEALTH]])[0].document_id != proc["id"]
    assert retrieve(plan, [labels[FINANCE]])[0].document_id == proc["id"]


def test_reingest_and_delete_keep_search_index_consistent(admin):
    labels = labels_by_name(admin)
    doc = upload(admin, LEAVE_PDF, "Leave Circular", [labels[HEALTH]])
    ingest_all(admin, doc["id"])
    ingest_all(admin, doc["id"])  # start=0 again replaces pages and chunks

    with connect() as conn:
        chunks = conn.execute("select count(*) from chunks").fetchone()[0]
        fts = conn.execute("select count(*) from chunks_fts where chunks_fts match '\"leave\"'").fetchone()[0]
    assert chunks == 2 and fts == 2
    assert vector_store.count() == 2  # the first run's vectors were replaced, not added to

    # re-running a batch from the middle replaces that page's vectors too
    client.post(f"/admin/documents/{doc['id']}/ingest?start=1", headers=admin)
    with connect() as conn:
        ids = {r[0] for r in conn.execute("select id from chunks")}
    assert vector_store.count() == 2
    assert set(vector_store.nearest([1.0] + [0.0] * 383, [doc["id"]], 10)) == ids

    assert client.delete(f"/admin/documents/{doc['id']}", headers=admin).status_code == 204
    with connect() as conn:
        assert conn.execute("select count(*) from pages").fetchone()[0] == 0
        assert conn.execute("select count(*) from chunks_fts where chunks_fts match '\"leave\"'").fetchone()[0] == 0
    assert vector_store.count() == 0


def test_rejects_non_pdf_upload(admin):
    files = {"file": ("x.pdf", b"hello", "application/pdf")}
    r = client.post("/admin/documents", headers=admin, files=files, data={"title": "x"})
    assert r.status_code == 400


def test_user_management(admin):
    labels = labels_by_name(admin)
    r = client.post(
        "/admin/users",
        headers=admin,
        json={"email": "New.Officer@agency.example", "password": "a-long-password", "label_ids": [labels[WORKS]]},
    )
    assert r.status_code == 201
    duplicate = {"email": "new.officer@agency.example", "password": "x" * 8}
    assert client.post("/admin/users", headers=admin, json=duplicate).status_code == 409

    new = login("new.officer@agency.example", "a-long-password")
    assert [label["name"] for label in client.get("/me", headers=new).json()["labels"]] == ["Ministry of Public Works"]
    assert client.get("/admin/users", headers=new).status_code == 403

    user_id = r.json()["id"]
    assert client.put(f"/admin/users/{user_id}/password", headers=admin, json={"password": "another-password"}).status_code == 204
    login("new.officer@agency.example", "another-password")
    assert client.delete(f"/admin/users/{user_id}", headers=admin).status_code == 204
    assert client.get("/me", headers=new).status_code == 401


def test_conversations_are_private_and_logged(admin, officer, monkeypatch):
    def fake_run(question, labels, history):
        yield {"type": "delta", "text": "Officers get 25 days [S1]."}
        yield {
            "type": "final",
            "answer": "Officers get 25 days [S1].",
            "citations": [],
            "eval": {"verdict": "grounded", "grounded_score": 1.0, "summary": "", "claims": []},
            "regenerated": False,
            "plan": {"sub_queries": [question]},
            "retrieved_chunk_ids": [],
            "latency_ms": 5,
            "usage": {"input_tokens": 1, "output_tokens": 2},
            "trace": {"retrieved": [], "first_draft": None},
        }

    monkeypatch.setattr(pipeline, "run", fake_run)
    r = client.post("/chat", headers=officer, json={"question": "How much annual leave do I get?"})
    assert r.status_code == 200 and '"type": "final"' in r.text

    convos = client.get("/conversations", headers=officer).json()
    assert len(convos) == 1
    convo = client.get(f"/conversations/{convos[0]['id']}", headers=officer).json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    assert client.get(f"/conversations/{convos[0]['id']}", headers=admin).status_code == 404  # owner only

    message_id = convo["messages"][1]["id"]
    assert client.post(f"/messages/{message_id}/feedback", headers=admin, json={"value": 1}).status_code == 404
    assert client.post(f"/messages/{message_id}/feedback", headers=officer, json={"value": 1}).status_code == 204

    logs = client.get("/admin/query-logs", headers=admin).json()
    assert logs[0]["question"] == "How much annual leave do I get?"
    assert logs[0]["messages"]["feedback"] == 1 and logs[0]["profiles"]["email"] == "officer@agency.example"
    stats = client.get("/admin/stats", headers=admin).json()
    assert stats["queries"] == 1 and stats["thumbs_up"] == 1 and stats["users"] == 2
