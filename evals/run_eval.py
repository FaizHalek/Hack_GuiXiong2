# ruff: noqa: E501
"""Offline evaluation of the question-answering pipeline against a golden set.

Runs every golden question through the same pipeline the API uses, then scores:

  retrieval      page-level Recall@k and MRR (expected pages vs retrieved chunks)
  groundedness   the in-pipeline Evaluator Agent's verdict and score
  judge          an independent DeepSeek V4 Pro judge: correctness and relevance vs the
                 reference answer (1-5), faithfulness and citation accuracy (0-1)
  refusals       unanswerable questions must be declined, not answered
  ops            latency and token usage

Usage (from the backend directory, with backend/.env filled in):

  .venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl
  .venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl --limit 5 --no-judge

Each golden line is JSON:
  {"id": "q1", "question": "...", "type": "single_fact|synthesis|comparative|unanswerable",
   "labels": ["Acme Corp"],                      # library names or ids to search
   "expected": [{"document": "Acme 2023 Annual Outlook", "page": 12}],  # title or id
   "reference_answer": "..."}
"""

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.agents import pipeline  # noqa: E402
from app.agents.citations import format_sources  # noqa: E402
from app.agents.schemas import Source  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import service_client  # noqa: E402
from app.llm import deepseek as llm  # noqa: E402

JUDGE_SYSTEM = """You grade answers produced by a research assistant that answers questions from a company's research reports.

You receive the question, a reference answer written by a domain expert, the assistant's answer with citations like [S1], and the text of each cited source.

Score:
- correctness (1-5): does the answer agree with the reference answer on the facts that matter? 5 = fully correct and complete, 3 = mostly correct with gaps, 1 = wrong.
- relevance (1-5): does it address what was asked, without padding?
- faithfulness (0-1): share of the answer's factual claims that are supported by the cited sources (ignore whether they match the reference).
- citation_accuracy (0-1): share of citations that point to a source that actually contains the cited claim.
- refused: true if the answer declines to answer or says the information isn't available.

When the reference answer says the question is unanswerable from the library, a correct answer is a refusal (correctness 5 if refused, 1 if it invents an answer)."""


class Judgement(BaseModel):
    correctness: int = Field(description="1-5")
    relevance: int = Field(description="1-5")
    faithfulness: float = Field(description="0-1")
    citation_accuracy: float = Field(description="0-1")
    refused: bool
    rationale: str = Field(description="Two sentences at most.")


def load_golden(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if line and not line.startswith("//"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{n}: invalid JSON: {e}") from e
    return rows


def resolve_labels(db, names_or_ids: list[str]) -> list[str]:
    labels = db.table("labels").select("id,name").execute().data
    by_name = {row["name"].lower(): row["id"] for row in labels}
    ids = {row["id"] for row in labels}
    if not names_or_ids:
        return sorted(ids)
    out = []
    for value in names_or_ids:
        if value in ids:
            out.append(value)
        elif value.lower() in by_name:
            out.append(by_name[value.lower()])
        else:
            raise SystemExit(f"Unknown library label: {value}")
    return out


def document_lookup(db) -> dict[str, str]:
    """Map lower-cased titles and ids to document ids."""
    docs = db.table("documents").select("id,title").execute().data
    lookup = {d["id"]: d["id"] for d in docs}
    lookup.update({d["title"].lower(): d["id"] for d in docs})
    return lookup


def retrieval_metrics(expected: list[dict], retrieved: list[tuple[str, int]], docs: dict[str, str], k: int) -> dict:
    if not expected:
        return {"recall_at_k": None, "mrr": None}
    want = set()
    for e in expected:
        doc_id = docs.get(str(e["document"]).lower()) or docs.get(str(e["document"]))
        if doc_id is None:
            print(f"  ! expected document not found: {e['document']}")
            continue
        want.add((doc_id, int(e["page"])))
    if not want:
        return {"recall_at_k": None, "mrr": None}
    top = retrieved[:k]
    recall = len(want.intersection(top)) / len(want)
    mrr = next((1 / rank for rank, hit in enumerate(top, start=1) if hit in want), 0.0)
    return {"recall_at_k": recall, "mrr": mrr}


def judge(question: str, reference: str, final: dict, sources: list[Source]) -> Judgement:
    cited_ids = {c["id"] for c in final["citations"]}
    cited = [s for s in sources if s.id in cited_ids]
    content = (
        f"<question>\n{question}\n</question>\n\n"
        f"<reference_answer>\n{reference or '(none provided)'}\n</reference_answer>\n\n"
        f"<assistant_answer>\n{final['answer']}\n</assistant_answer>\n\n"
        f"<cited_sources>\n{format_sources(cited) or '(none)'}\n</cited_sources>"
    )
    return llm.parse(
        model=get_settings().judge_model,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=Judgement,
        effort="high",
    )


def run_one(db, item: dict, docs: dict[str, str], k: int, use_judge: bool) -> dict:
    labels = resolve_labels(db, item.get("labels", []))
    sources: list[Source] = []
    final: dict = {}
    started = time.monotonic()
    for event in pipeline.run(db, item["question"], labels, []):
        if event["type"] == "sources":
            sources = [Source(**{**s, "content": s["snippet"]}) for s in event["sources"]]
        elif event["type"] == "final":
            final = event
    elapsed = time.monotonic() - started

    # The sources event carries truncated snippets; fetch full chunk text for judging.
    if sources:
        full = db.table("chunks").select("id,content").in_("id", [s.chunk_id for s in sources]).execute().data
        text = {row["id"]: row["content"] for row in full}
        for s in sources:
            s.content = text.get(s.chunk_id, s.content)

    retrieved = [(s.document_id, s.page_index) for s in sources]
    row = {
        "id": item.get("id", ""),
        "type": item.get("type", ""),
        "question": item["question"],
        **retrieval_metrics(item.get("expected", []), retrieved, docs, k),
        "verdict": final.get("eval", {}).get("verdict"),
        "grounded_score": final.get("eval", {}).get("grounded_score"),
        "regenerated": final.get("regenerated"),
        "n_citations": len(final.get("citations", [])),
        "latency_s": round(elapsed, 2),
        "input_tokens": final.get("usage", {}).get("input_tokens"),
        "output_tokens": final.get("usage", {}).get("output_tokens"),
        "answer": final.get("answer", ""),
    }

    refused_by_pipeline = final.get("eval", {}).get("verdict") == "no_sources" or not final.get("citations")
    if use_judge and final:
        j = judge(item["question"], item.get("reference_answer", ""), final, sources)
        row.update(
            correctness=j.correctness,
            relevance=j.relevance,
            faithfulness=j.faithfulness,
            citation_accuracy=j.citation_accuracy,
            refused=j.refused,
            judge_rationale=j.rationale,
        )
    else:
        row["refused"] = refused_by_pipeline
    if item.get("type") == "unanswerable":
        row["refusal_correct"] = bool(row["refused"])
    return row


def mean(values) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(statistics.fmean(vals), 3) if vals else None


def summarise(rows: list[dict], k: int) -> dict:
    answerable = [r for r in rows if r["type"] != "unanswerable"]
    unanswerable = [r for r in rows if r["type"] == "unanswerable"]
    latencies = sorted(r["latency_s"] for r in rows)
    return {
        "questions": len(rows),
        f"recall@{k}": mean(r["recall_at_k"] for r in answerable),
        "mrr": mean(r["mrr"] for r in answerable),
        "citation_accuracy (judge)": mean(r.get("citation_accuracy") for r in answerable),
        "faithfulness (judge)": mean(r.get("faithfulness") for r in answerable),
        "correctness 1-5 (judge)": mean(r.get("correctness") for r in answerable),
        "relevance 1-5 (judge)": mean(r.get("relevance") for r in answerable),
        "evaluator grounded_score": mean(r["grounded_score"] for r in answerable),
        "refusal accuracy": mean(1.0 if r["refusal_correct"] else 0.0 for r in unanswerable) if unanswerable else None,
        "regeneration rate": mean(1.0 if r["regenerated"] else 0.0 for r in rows),
        "latency p50 (s)": latencies[len(latencies) // 2] if latencies else None,
        "latency p95 (s)": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
        "avg input tokens": mean(r["input_tokens"] for r in rows),
        "avg output tokens": mean(r["output_tokens"] for r in rows),
    }


TARGETS = {"recall@": 0.85, "citation_accuracy (judge)": 0.9, "refusal accuracy": 0.9}


def write_report(rows: list[dict], summary: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"eval-{stamp}.csv"
    fields = sorted({key for r in rows for key in r}, key=lambda f: (f != "id", f))
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    lines = [f"# Eval report {stamp}", "", "| Metric | Value | Target |", "|---|---|---|"]
    for key, value in summary.items():
        target = next((f"≥ {t}" for prefix, t in TARGETS.items() if key.startswith(prefix)), "")
        lines.append(f"| {key} | {value if value is not None else '–'} | {target} |")
    lines += ["", "## Weakest answers", ""]
    weakest = sorted(rows, key=lambda r: (r.get("correctness") or 5, r.get("grounded_score") or 1))[:5]
    for r in weakest:
        lines.append(
            f"- **{r['id']}** ({r['type']}) {r['question']}: verdict {r['verdict']}, correctness {r.get('correctness', '–')}"
        )
        if r.get("judge_rationale"):
            lines.append(f"  - {r['judge_rationale']}")
    md_path = out_dir / f"eval-{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", type=Path, default=Path(__file__).with_name("golden_set.jsonl"))
    parser.add_argument("--k", type=int, default=10, help="cut-off for Recall@k / MRR")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (cheaper, retrieval + evaluator only)")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("reports"))
    args = parser.parse_args()

    golden = load_golden(args.golden)[: args.limit]
    db = service_client()  # bypasses RLS; label filtering still comes from each item's "labels"
    docs = document_lookup(db)

    rows = []
    for n, item in enumerate(golden, start=1):
        print(f"[{n}/{len(golden)}] {item['question'][:80]}")
        try:
            rows.append(run_one(db, item, docs, args.k, not args.no_judge))
        except Exception as e:  # keep going; one failure shouldn't sink the run
            print(f"  ! failed: {e}")
            rows.append(
                {
                    "id": item.get("id", ""),
                    "type": item.get("type", ""),
                    "question": item["question"],
                    "error": str(e),
                    "latency_s": 0,
                    "regenerated": False,
                    "recall_at_k": None,
                    "mrr": None,
                    "grounded_score": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "verdict": "error",
                    "refusal_correct": False,
                }
            )

    summary = summarise(rows, args.k)
    report = write_report(rows, summary, args.out)
    print()
    for key, value in summary.items():
        print(f"{key:>28}: {value}")
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
