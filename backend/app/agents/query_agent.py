from app.agents import prompts
from app.agents.schemas import QueryPlan
from app.config import get_settings
from app.llm import deepseek as llm

HISTORY_TURNS = 6


def plan_query(question: str, history: list[dict], usage: llm.Usage | None = None) -> QueryPlan:
    recent = history[-HISTORY_TURNS:]
    transcript = "\n".join(f"{m['role'].upper()}: {m['content'][:1500]}" for m in recent)
    content = (
        f"<conversation>\n{transcript}\n</conversation>\n\n" if transcript else ""
    ) + f"<latest_message>\n{question}\n</latest_message>"

    plan = llm.parse(
        model=get_settings().query_model,
        system=prompts.load("query"),
        messages=[{"role": "user", "content": content}],
        output_format=QueryPlan,
        effort=get_settings().query_effort or None,
        usage=usage,
    )
    plan.sub_queries = [q.strip() for q in plan.sub_queries if q.strip()][:3] or [plan.standalone_question or question]
    plan.keywords = [k.strip() for k in plan.keywords if k.strip()][:6]
    if not plan.standalone_question.strip():
        plan.standalone_question = question
    return plan
