"""Question-answering orchestration: Query Agent -> retrieval -> Answer Agent ->
Evaluator Agent, with one evaluator-guided regeneration.

`run` yields events that the chat route forwards to the browser as SSE:

  plan        the Query Agent's retrieval plan
  sources     the excerpts the answer may cite
  delta       a piece of answer text
  evaluating  the Evaluator Agent is checking the answer
  regenerate  the first draft failed the check; the client should clear it
  final       the finished answer, its citations and the evaluation
"""

import logging
import time
from collections.abc import Iterator

from supabase import Client

from app.agents import answer_agent, evaluator, query_agent, retrieve
from app.agents.citations import resolve
from app.agents.schemas import Evaluation, Source
from app.llm.deepseek import Usage

log = logging.getLogger(__name__)

NO_SOURCES_REPLY = (
    "I couldn't find anything relevant to this question in the selected research libraries. "
    "Try rephrasing, or select additional libraries."
)


def _citations(answer: str, sources: list[Source], evaluation: Evaluation | None) -> list[dict]:
    quotes: dict[str, str] = {}
    if evaluation:
        for claim in evaluation.claims:
            for sid in claim.source_ids:
                trusted = claim.citation_correct and claim.verdict != "unsupported"
                if claim.evidence_quote and trusted and sid not in quotes:
                    quotes[sid] = claim.evidence_quote
    cited, _ = resolve(answer, sources)
    return [s.public(snippet=quotes.get(s.id)) for s in cited]


def _eval_payload(evaluation: Evaluation | None) -> dict:
    if evaluation is None:
        return {"verdict": "unchecked", "grounded_score": None, "summary": "The answer could not be checked.", "claims": []}
    return {
        "verdict": evaluator.verdict(evaluation),
        "grounded_score": round(evaluation.grounded_score, 3),
        "summary": evaluation.summary,
        "claims": [c.model_dump() for c in evaluation.claims],
    }


def _safe_evaluate(question: str, answer: str, sources: list[Source], usage: Usage) -> Evaluation | None:
    try:
        return evaluator.evaluate(question, answer, sources, usage)
    except Exception:
        log.exception("Evaluator failed")
        return None


def run(db: Client, question: str, label_ids: list[str], history: list[dict]) -> Iterator[dict]:
    started = time.monotonic()
    usage = Usage()

    def final(
        answer: str,
        citations: list[dict],
        eval_: dict,
        sources: list[Source],
        regenerated: bool = False,
        first_draft: dict | None = None,
    ) -> dict:
        cited = {c["id"] for c in citations}
        return {
            "type": "final",
            "answer": answer,
            "citations": citations,
            "eval": eval_,
            "regenerated": regenerated,
            "plan": plan.model_dump(),
            "retrieved_chunk_ids": [s.chunk_id for s in sources],
            "latency_ms": int((time.monotonic() - started) * 1000),
            "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            # Stored in query_logs for the admin Insights view; not sent to the browser.
            "trace": {
                "retrieved": [s.trace(cited=s.id in cited) for s in sources],
                "first_draft": first_draft,
            },
        }

    plan = query_agent.plan_query(question, history, usage)
    yield {"type": "plan", "plan": plan.model_dump()}

    if not plan.needs_retrieval:
        reply = plan.direct_reply or "I answer questions using the research libraries you've selected."
        yield {"type": "delta", "text": reply}
        yield final(reply, [], {"verdict": "not_applicable", "grounded_score": None, "summary": "", "claims": []}, [])
        return

    sources = retrieve.retrieve(db, plan, label_ids)
    yield {"type": "sources", "sources": [s.public() for s in sources]}

    if not sources:
        yield {"type": "delta", "text": NO_SOURCES_REPLY}
        yield final(NO_SOURCES_REPLY, [], {"verdict": "no_sources", "grounded_score": None, "summary": "", "claims": []}, [])
        return

    answer = ""
    for text in answer_agent.stream_answer(plan.standalone_question, sources, usage=usage):
        answer += text
        yield {"type": "delta", "text": text}

    yield {"type": "evaluating"}
    evaluation = _safe_evaluate(plan.standalone_question, answer, sources, usage)

    regenerated = False
    first_draft = None
    if evaluation is not None and not evaluator.passes(evaluation):
        regenerated = True
        first_draft = {"answer": answer, "eval": _eval_payload(evaluation)}
        yield {"type": "regenerate", "reason": evaluation.summary}
        answer = ""
        for text in answer_agent.stream_answer(plan.standalone_question, sources, feedback=evaluation, usage=usage):
            answer += text
            yield {"type": "delta", "text": text}
        yield {"type": "evaluating"}
        evaluation = _safe_evaluate(plan.standalone_question, answer, sources, usage)

    yield final(answer, _citations(answer, sources, evaluation), _eval_payload(evaluation), sources, regenerated, first_draft)
