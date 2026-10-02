from types import SimpleNamespace as NS

import pytest

from app.agents.schemas import QueryPlan
from app.llm import deepseek


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def completion(content: str, finish_reason: str = "stop"):
    return NS(
        choices=[NS(message=NS(content=content), finish_reason=finish_reason)],
        usage=NS(prompt_tokens=10, completion_tokens=5),
    )


def chunk(text=None, finish_reason=None, usage=None, empty=False):
    choices = [] if empty else [NS(delta=NS(content=text), finish_reason=finish_reason)]
    return NS(choices=choices, usage=usage)


@pytest.fixture
def fake(monkeypatch):
    def install(responses):
        completions = FakeCompletions(responses)
        monkeypatch.setattr(deepseek, "client", lambda: NS(chat=NS(completions=completions)))
        return completions

    return install


VALID_PLAN = '{"needs_retrieval": true, "standalone_question": "Q?", "sub_queries": ["q"], "keywords": ["k"]}'


def test_parse_validates_and_counts_usage(fake):
    calls = fake([completion(VALID_PLAN)])
    usage = deepseek.Usage()
    plan = deepseek.parse(model="deepseek-flash", system="sys", messages=[], output_format=QueryPlan, usage=usage)

    assert plan.sub_queries == ["q"] and plan.direct_reply == ""
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)
    request = calls.calls[0]
    assert request["response_format"] == {"type": "json_object"}
    assert "json" in request["messages"][0]["content"]  # JSON mode requires the word in the prompt
    assert "standalone_question" in request["messages"][0]["content"]  # schema is included
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_parse_enables_thinking_with_effort(fake):
    calls = fake([completion(VALID_PLAN)])
    deepseek.parse(model="m", system="s", messages=[], output_format=QueryPlan, effort="low")
    assert calls.calls[0]["reasoning_effort"] == "low"
    assert calls.calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}


def test_parse_retries_with_validation_error(fake):
    calls = fake([completion('{"needs_retrieval": "maybe"}'), completion(VALID_PLAN)])
    plan = deepseek.parse(model="m", system="s", messages=[], output_format=QueryPlan)
    assert plan.standalone_question == "Q?"
    retry_messages = calls.calls[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "did not match the schema" in retry_messages[-1]["content"]


def test_parse_retries_empty_content_then_fails(fake):
    fake([completion(""), completion("", finish_reason="length")])
    with pytest.raises(deepseek.LLMOutputError):
        deepseek.parse(model="m", system="s", messages=[], output_format=QueryPlan)


def test_parse_content_filter_raises_refusal(fake):
    fake([completion("", finish_reason="content_filter")])
    with pytest.raises(deepseek.RefusalError):
        deepseek.parse(model="m", system="s", messages=[], output_format=QueryPlan)


def test_stream_text_yields_content_and_usage(fake):
    fake(
        [
            iter(
                [
                    chunk(text=None),  # reasoning-only delta
                    chunk(text="Revenue "),
                    chunk(text="grew [S1].", finish_reason="stop"),
                    chunk(empty=True, usage=NS(prompt_tokens=100, completion_tokens=20)),
                ]
            )
        ]
    )
    usage = deepseek.Usage()
    text = "".join(deepseek.stream_text(model="m", system="s", messages=[], usage=usage))
    assert text == "Revenue grew [S1]."
    assert usage.output_tokens == 20


def test_stream_text_content_filter(fake):
    fake([iter([chunk(text="partial", finish_reason="content_filter")])])
    with pytest.raises(deepseek.RefusalError):
        list(deepseek.stream_text(model="m", system="s", messages=[]))
