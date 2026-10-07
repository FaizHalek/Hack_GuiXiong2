import pytest

from app.agents import pipeline
from app.agents.citations import cited_ids, format_sources, resolve
from app.agents.evaluator import passes, verdict
from app.agents.retrieve import cap_per_document, fts_text, rank_pages
from app.agents.schemas import ClaimCheck, Evaluation, QueryPlan, Source
from app.deps import CurrentUser, authorised_labels


def src(i: int, doc: str = "d1", page: int = 1) -> Source:
    return Source(
        id=f"S{i}", chunk_id=f"c{i}", document_id=doc, document_title=f"Doc {doc}", page_index=page, content=f"content {i}"
    )


def claim(verdict_="supported", correct=True, ids=("S1",), quote="q") -> ClaimCheck:
    return ClaimCheck(claim="x", source_ids=list(ids), verdict=verdict_, citation_correct=correct, evidence_quote=quote, note="")


# --- citations ---------------------------------------------------------------


def test_cited_ids_in_order_and_deduplicated():
    assert cited_ids("A [S2]. B [S1][S2]. C [S3, S4].") == ["S2", "S1", "S3", "S4"]


def test_resolve_separates_invented_ids():
    known, invented = resolve("x [S1] y [S9]", [src(1), src(2)])
    assert [s.id for s in known] == ["S1"]
    assert invented == ["S9"]


def test_format_sources_includes_page_and_printed_label():
    s = src(1, page=12)
    s.printed_label = "x"
    out = format_sources([s])
    assert 'id="S1"' in out and 'page="12 (printed x)"' in out


# --- retrieval helpers -------------------------------------------------------


def test_fts_text_ors_quoted_keywords():
    assert fts_text(["PK 3/2024", "annual leave"], "fallback") == '"PK 3/2024" OR "annual leave"'
    assert fts_text(['say "hi"'], "") == '"say ""hi"""'  # quotes are escaped, not parsed as FTS syntax


def test_fts_text_falls_back_to_content_words():
    assert fts_text([], "What is the leave policy for the officers?") == '"leave" OR "policy" OR "officers"'
    assert fts_text([], "") == ""


def hit(doc, page, chunk, score):
    return {
        "document_id": doc,
        "page_index": page,
        "chunk_id": chunk,
        "content": chunk,
        "score": score,
        "page_text": f"{doc}-{page}",
    }


def test_rank_pages_rolls_chunks_up_to_pages():
    q1 = [hit("a", 1, "a1x", 0.5), hit("a", 1, "a1y", 0.9), hit("a", 2, "a2", 0.7)]
    q2 = [hit("a", 2, "a2", 0.6), hit("b", 1, "b1", 0.2)]
    pages = rank_pages([q1, q2])

    # one row per page; a page found by both sub-queries outranks a single strong hit
    assert [(p["document_id"], p["page_index"]) for p in pages] == [("a", 2), ("a", 1), ("b", 1)]
    assert pages[0]["score"] == pytest.approx(1.3)
    # a page's score uses its best chunk per query, not the sum of all its chunks
    assert pages[1]["score"] == pytest.approx(0.9)
    assert pages[1]["chunk_id"] == "a1y"


def test_cap_per_document():
    pages = [{"document_id": "a"}] * 5 + [{"document_id": "b"}]
    picked = cap_per_document(pages, limit=10, per_doc=3)
    assert sum(p["document_id"] == "a" for p in picked) == 3
    assert sum(p["document_id"] == "b" for p in picked) == 1


# --- access ------------------------------------------------------------------


def test_authorised_labels_intersects_with_grants():
    user = CurrentUser(id="u", email="e", role="user", token="t", label_ids=["l1", "l2"])
    assert authorised_labels(["l2", "l3"], user) == ["l2"]
    assert authorised_labels([], user) == ["l1", "l2"]
    assert authorised_labels(["l3"], user) == []


# --- evaluator gate ----------------------------------------------------------


def test_gate_and_verdicts():
    assert verdict(Evaluation(claims=[claim()], grounded_score=1.0, summary="")) == "grounded"
    assert verdict(Evaluation(claims=[claim(correct=False)], grounded_score=0.9, summary="")) == "partial"
    bad = Evaluation(claims=[claim(), claim("unsupported")], grounded_score=0.8, summary="")
    assert not passes(bad) and verdict(bad) == "low_confidence"
    assert not passes(Evaluation(claims=[claim("partial")], grounded_score=0.5, summary=""))
    assert verdict(Evaluation(claims=[], grounded_score=0, summary="")) == "not_applicable"


# --- pipeline orchestration --------------------------------------------------


@pytest.fixture
def plan():
    return QueryPlan(needs_retrieval=True, standalone_question="Q?", sub_queries=["Q"], keywords=[], direct_reply="")


def _patch(monkeypatch, plan, sources, answers, evaluations):
    answers, evaluations = list(answers), list(evaluations)
    feedback_seen = []
    monkeypatch.setattr(pipeline.query_agent, "plan_query", lambda q, h, u=None: plan)
    monkeypatch.setattr(pipeline.retrieve, "retrieve", lambda p, labels: sources)

    def fake_stream(question, sources, feedback=None, usage=None):
        feedback_seen.append(feedback)
        yield from answers.pop(0)

    monkeypatch.setattr(pipeline.answer_agent, "stream_answer", fake_stream)
    monkeypatch.setattr(pipeline.evaluator, "evaluate", lambda q, a, s, u=None: evaluations.pop(0))
    return feedback_seen


def test_pipeline_happy_path(monkeypatch, plan):
    good = Evaluation(claims=[claim(quote="exact words")], grounded_score=1.0, summary="ok")
    _patch(monkeypatch, plan, [src(1), src(2)], [["Revenue grew ", "[S1]."]], [good])

    events = list(pipeline.run("q", ["l1"], []))
    types = [e["type"] for e in events]
    assert types == ["plan", "sources", "delta", "delta", "evaluating", "final"]

    final = events[-1]
    assert final["answer"] == "Revenue grew [S1]."
    assert [c["id"] for c in final["citations"]] == ["S1"]
    assert final["citations"][0]["snippet"] == "exact words"  # evaluator quote used for highlighting
    assert final["eval"]["verdict"] == "grounded"
    assert final["regenerated"] is False

    trace = final["trace"]
    assert [(r["id"], r["cited"]) for r in trace["retrieved"]] == [("S1", True), ("S2", False)]
    assert trace["first_draft"] is None


def test_pipeline_regenerates_once_with_feedback(monkeypatch, plan):
    bad = Evaluation(claims=[claim("unsupported", ids=("S2",))], grounded_score=0.2, summary="S2 doesn't say that")
    good = Evaluation(claims=[claim()], grounded_score=1.0, summary="ok")
    feedback_seen = _patch(monkeypatch, plan, [src(1), src(2)], [["Wrong [S2]."], ["Right [S1]."]], [bad, good])

    events = list(pipeline.run("q", ["l1"], []))
    types = [e["type"] for e in events]
    assert "regenerate" in types
    assert feedback_seen == [None, bad]
    assert events[-1]["answer"] == "Right [S1]."
    assert events[-1]["regenerated"] is True

    draft = events[-1]["trace"]["first_draft"]
    assert draft["answer"] == "Wrong [S2]."
    assert draft["eval"]["verdict"] == "low_confidence"
    assert draft["eval"]["summary"] == "S2 doesn't say that"


def test_pipeline_flags_low_confidence_after_second_failure(monkeypatch, plan):
    bad = Evaluation(claims=[claim("unsupported")], grounded_score=0.1, summary="no")
    _patch(monkeypatch, plan, [src(1)], [["A [S1]."], ["B [S1]."]], [bad, bad])
    final = list(pipeline.run("q", ["l1"], []))[-1]
    assert final["eval"]["verdict"] == "low_confidence"
    assert [e for e in final["citations"]][0]["snippet"] == "content 1"  # no trusted quote -> chunk text


def test_pipeline_no_sources(monkeypatch, plan):
    _patch(monkeypatch, plan, [], [], [])
    final = list(pipeline.run("q", ["l1"], []))[-1]
    assert final["eval"]["verdict"] == "no_sources"
    assert final["citations"] == []


def test_pipeline_direct_reply_skips_retrieval(monkeypatch):
    p = QueryPlan(needs_retrieval=False, standalone_question="hi", sub_queries=[], keywords=[], direct_reply="Hello!")
    monkeypatch.setattr(pipeline.query_agent, "plan_query", lambda q, h, u=None: p)
    monkeypatch.setattr(pipeline.retrieve, "retrieve", lambda *a: pytest.fail("should not retrieve"))
    events = list(pipeline.run("hi", ["l1"], []))
    assert [e["type"] for e in events] == ["plan", "delta", "final"]
