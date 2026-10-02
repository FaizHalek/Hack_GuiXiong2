from collections.abc import Iterator

from app.agents import prompts
from app.agents.citations import format_sources
from app.agents.schemas import Evaluation, Source
from app.config import get_settings
from app.llm import deepseek as llm


def _feedback_block(evaluation: Evaluation) -> str:
    problems = [
        f'- "{c.claim}" ({", ".join(c.source_ids) or "no citation"}): {c.verdict}'
        + ("" if c.citation_correct else ", wrong citation")
        + (f". {c.note}" if c.note else "")
        for c in evaluation.claims
        if c.verdict != "supported" or not c.citation_correct
    ]
    return (
        "<review_of_previous_draft>\nA reviewer checked your previous draft against the sources and found these problems:\n"
        + "\n".join(problems)
        + "\nWrite a new answer that fixes them: drop or correct unsupported claims"
        + " and cite the source that actually contains each fact.\n</review_of_previous_draft>\n\n"
    )


def stream_answer(
    question: str,
    sources: list[Source],
    feedback: Evaluation | None = None,
    usage: llm.Usage | None = None,
) -> Iterator[str]:
    content = (
        f"<sources>\n{format_sources(sources)}\n</sources>\n\n"
        + (_feedback_block(feedback) if feedback else "")
        + f"<question>\n{question}\n</question>"
    )
    yield from llm.stream_text(
        model=get_settings().answer_model,
        system=prompts.load("answer"),
        messages=[{"role": "user", "content": content}],
        max_tokens=16000,
        effort=get_settings().answer_effort or None,
        usage=usage,
    )
