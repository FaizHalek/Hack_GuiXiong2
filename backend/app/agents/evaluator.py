from app.agents import prompts
from app.agents.citations import format_sources, resolve
from app.agents.schemas import ClaimCheck, Evaluation, Source, Verdict
from app.config import get_settings
from app.llm import deepseek as llm


def evaluate(question: str, answer: str, sources: list[Source], usage: llm.Usage | None = None) -> Evaluation:
    cited, invented = resolve(answer, sources)
    content = (
        f"<question>\n{question}\n</question>\n\n"
        f"<answer>\n{answer}\n</answer>\n\n"
        f"<cited_sources>\n{format_sources(cited) or '(none)'}\n</cited_sources>"
    )
    evaluation = llm.parse(
        model=get_settings().evaluator_model,
        system=prompts.load("evaluator"),
        messages=[{"role": "user", "content": content}],
        output_format=Evaluation,
        effort=get_settings().evaluator_effort or None,
        usage=usage,
    )
    # Citations to ids that were never provided are always wrong, whatever the judge said.
    for sid in invented:
        evaluation.claims.append(
            ClaimCheck(
                claim=f"Citation [{sid}]",
                source_ids=[sid],
                verdict="unsupported",
                citation_correct=False,
                evidence_quote="",
                note="Cited a source id that was not provided.",
            )
        )
    evaluation.grounded_score = max(0.0, min(1.0, evaluation.grounded_score))
    return evaluation


def passes(evaluation: Evaluation) -> bool:
    if not evaluation.claims:  # e.g. "the selected libraries don't cover this"
        return True
    min_score = get_settings().min_grounded_score
    return evaluation.grounded_score >= min_score and not any(c.verdict == "unsupported" for c in evaluation.claims)


def verdict(evaluation: Evaluation) -> Verdict:
    if not evaluation.claims:
        return "not_applicable"
    if not passes(evaluation):
        return "low_confidence"
    clean = all(c.verdict == "supported" and c.citation_correct for c in evaluation.claims)
    return "grounded" if clean and evaluation.grounded_score >= 0.9 else "partial"
