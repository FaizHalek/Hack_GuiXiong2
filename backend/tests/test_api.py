from fastapi.testclient import TestClient

from app.deps import CurrentUser, get_current_user
from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_bearer_token():
    assert client.get("/me").status_code == 401
    assert client.post("/chat", json={"question": "x"}).status_code == 401


def test_admin_routes_reject_non_admin():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u", email="u@example.com", role="user", token="t", label_ids=["l1"]
    )
    try:
        assert client.get("/admin/users").status_code == 403
        assert client.post("/admin/documents", json={"title": "t", "filename": "f.pdf"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_chat_rejects_libraries_outside_grants():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u", email="u@example.com", role="user", token="t", label_ids=["l1"]
    )
    try:
        r = client.post("/chat", json={"question": "x", "label_ids": ["someone-elses-library"]})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
