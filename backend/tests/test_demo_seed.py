from fastapi.testclient import TestClient

from app import demo_seed
from app import vectors as vector_store
from app.agents.retrieve import retrieve
from app.agents.schemas import QueryPlan
from app.db import connect, fetch_all
from app.main import app

client = TestClient(app)

SAMPLE = """DEPARTMENT OF HEALTH AND WELLBEING
============================================================
CIRCULAR
Title: Circular No. 3 of 2023: Updates to Annual Leave
Reference No.: DHW/CIR/2023/003
Date: 16 October 2023
To: All Heads of Department and Staff
============================================================

1. PURPOSE
This circular informs all staff of changes to requirements on annual leave.

3. CHANGES
3.1 Effective 30 October 2023, the processing period is reduced from 7 to 5 working days.
"""


def test_parse_reads_the_generator_header(tmp_path):
    path = tmp_path / "circulars" / "DHW-CIR-2023-003_annual_leave.txt"
    path.parent.mkdir()
    path.write_text(SAMPLE, encoding="utf-8")
    doc = demo_seed.parse(path)
    assert doc.doc_type == "circular"
    assert doc.agency_name == "Department Of Health And Wellbeing"
    assert doc.agency_code == "DHW"
    assert doc.kind == "CIRCULAR"
    assert doc.title == "Circular No. 3 of 2023: Updates to Annual Leave"
    assert doc.reference_no == "DHW/CIR/2023/003"
    assert doc.issued_on == "2023-10-16"
    assert ("To", "All Heads of Department and Staff") in doc.header
    assert doc.body.startswith("1. PURPOSE")


def test_seed_loads_fake_documents_into_every_store(local_store):
    result = demo_seed.seed(demo_seed.DEFAULT_DATA, limit=2, log=lambda *_: None)
    assert result == {"added": 12, "skipped": 0, "failed": 0, "collections": result["collections"]}

    with connect() as conn:
        docs = fetch_all(
            conn,
            "select d.doc_type, d.reference_no, d.issued_on, d.status, l.name as collection from documents d"
            " join document_labels dl on dl.document_id = d.id join labels l on l.id = dl.label_id",
        )
        pages = conn.execute("select count(*) from pages where char_count > 0").fetchone()[0]
        chunks = conn.execute("select count(*) from chunks").fetchone()[0]
    assert len(docs) == 12 and all(d["status"] == "ready" for d in docs)
    assert {d["doc_type"] for d in docs} == {"policy", "sop", "circular", "guideline", "report", "minutes"}
    assert all(d["reference_no"] and d["issued_on"] for d in docs)
    # each document lands in its agency's collection (the agency code leads the reference number)
    agencies = {code: name for code, name, _ in demo_seed.SEED_COLLECTIONS}
    assert all(d["collection"] == agencies[d["reference_no"].split("/")[0]] for d in docs)
    assert pages >= 12 and vector_store.count() == chunks

    # running it again skips what is already there
    assert demo_seed.seed(demo_seed.DEFAULT_DATA, limit=2, log=lambda *_: None)["skipped"] == 12


def test_seeded_documents_are_searchable_and_access_controlled(local_store):
    demo_seed.seed(demo_seed.DEFAULT_DATA, limit=3, log=lambda *_: None)
    token = client.post(
        "/auth/login", json={"email": local_store.demo_user_email, "password": local_store.demo_user_password}
    ).json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    visible = client.get("/documents", headers={"Authorization": f"Bearer {token}"}).json()

    allowed_prefixes = {f"{code}/" for code in ("DHW", "DDS")}  # the demo officer's agencies
    assert visible and all(d["reference_no"][:4] in allowed_prefixes for d in visible)

    target = visible[0]
    plan = QueryPlan(needs_retrieval=True, standalone_question=target["title"], sub_queries=[target["title"]])
    sources = retrieve(plan, [label["id"] for label in me["labels"]])
    assert sources and {s.document_id for s in sources} <= {d["id"] for d in visible}
    assert any(s.document_id == target["id"] for s in sources)
    assert sources[0].reference_no and sources[0].doc_type


def test_reset_removes_seeded_documents(local_store):
    demo_seed.seed(demo_seed.DEFAULT_DATA, limit=1, log=lambda *_: None)
    removed = demo_seed.reset(demo_seed.load(demo_seed.DEFAULT_DATA, limit=1))
    assert removed == 6
    with connect() as conn:
        assert conn.execute("select count(*) from documents").fetchone()[0] == 0
    assert vector_store.count() == 0
    assert not any(local_store.files_dir.iterdir())


def test_canary_is_found_by_admins_and_hidden_from_officers(local_store, tmp_path):
    """The "brown M&M's" canary: a fact only one restricted document holds (see scripts/generate_fake_docs.py)."""
    data = tmp_path / "fake"
    (data / "circulars").mkdir(parents=True)
    canary = demo_seed.DEFAULT_DATA / "circulars" / "LAD-CIR-2025-099_meeting_room_confectionery.txt"
    (data / "circulars" / canary.name).write_bytes(canary.read_bytes())
    demo_seed.seed(data, log=lambda *_: None)

    question = "Which form confirms that brown sweets were removed before a contractor briefing?"
    plan = QueryPlan(needs_retrieval=True, standalone_question=question, sub_queries=[question], keywords=["brown", "sweets"])
    with connect() as conn:
        lad = fetch_all(conn, "select id from labels where name = 'Land Administration Department'")[0]["id"]

    sources = retrieve(plan, [lad])
    assert sources[0].reference_no == "LAD/CIR/2025/099" and "Form LAD-0451" in sources[0].content

    def login(email, password):
        token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    officer = login(local_store.demo_user_email, local_store.demo_user_password)
    officer_labels = [label["id"] for label in client.get("/me", headers=officer).json()["labels"]]
    assert lad not in officer_labels
    assert retrieve(plan, officer_labels) == []
    assert client.get("/documents", headers=officer).json() == []
    assert client.post("/chat", headers=officer, json={"question": question, "label_ids": [lad]}).status_code == 403

    admin = login(local_store.demo_admin_email, local_store.demo_admin_password)
    assert [d["reference_no"] for d in client.get("/documents", headers=admin).json()] == ["LAD/CIR/2025/099"]
