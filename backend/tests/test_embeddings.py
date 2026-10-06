import json

import httpx
import pytest

from app.config import get_settings
from app.llm import embeddings


@pytest.fixture
def edge_function(monkeypatch):
    """Install a fake Edge Function; `handler(texts) -> httpx.Response`."""
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "embed_secret", "s3cret")
    monkeypatch.setattr(settings, "embed_batch_size", 4)
    requests = []

    def install(handler):
        def transport(request: httpx.Request) -> httpx.Response:
            texts = json.loads(request.content)["texts"]
            requests.append((request, texts))
            return handler(texts)

        client = httpx.Client(transport=httpx.MockTransport(transport))
        monkeypatch.setattr(embeddings, "_client", lambda: client)
        return requests

    return install


def ok(texts):
    dim = get_settings().embedding_dim
    return httpx.Response(200, json={"embeddings": [[float(len(t))] * dim for t in texts]})


def test_batches_preserve_order_and_send_secret(edge_function):
    requests = edge_function(ok)
    texts = [f"text-{'x' * i}" for i in range(10)]
    vectors = embeddings.embed(texts)

    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]
    assert sorted(len(batch) for _, batch in requests) == [2, 4, 4]
    request = requests[0][0]
    assert str(request.url) == "https://proj.supabase.co/functions/v1/embed"
    assert request.headers["x-embed-secret"] == "s3cret"


def test_failed_batch_is_split_and_retried(edge_function):
    # Simulate the CPU budget: batches larger than 1 fail with the runtime's 546 status.
    requests = edge_function(lambda texts: ok(texts) if len(texts) == 1 else httpx.Response(546, text="CPU time exceeded"))
    vectors = embeddings.embed(["a", "bb", "ccc"])
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]
    assert any(len(batch) == 1 for _, batch in requests)


def test_auth_error_fails_fast(edge_function):
    requests = edge_function(lambda texts: httpx.Response(401, json={"error": "unauthorised"}))
    with pytest.raises(embeddings.EmbeddingError, match="401"):
        embeddings.embed(["a", "b", "c", "d"])
    assert len(requests) == 1  # no retries, no splitting


def test_wrong_dimension_is_rejected(edge_function):
    edge_function(lambda texts: httpx.Response(200, json={"embeddings": [[0.0] * 1024 for _ in texts]}))
    with pytest.raises(embeddings.EmbeddingError, match="unexpected shape"):
        embeddings.embed(["a"])


def test_empty_input_makes_no_calls(edge_function):
    requests = edge_function(ok)
    assert embeddings.embed([]) == []
    assert requests == []
