"""Thin wrapper around the DeepSeek API (OpenAI-compatible) shared by all agents.

DeepSeek's JSON mode guarantees a JSON object but not a particular schema, so
`parse` puts the pydantic schema in the system prompt, validates the reply, and
retries once with the validation error if it doesn't fit.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings


class RefusalError(RuntimeError):
    """The provider's content filter stopped the response."""


class LLMOutputError(RuntimeError):
    """The model didn't return usable output after retrying."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, usage) -> None:
        if usage is None:
            return
        self.input_tokens += usage.prompt_tokens or 0
        self.output_tokens += usage.completion_tokens or 0


@lru_cache
def client() -> openai.OpenAI:
    s = get_settings()
    return openai.OpenAI(api_key=s.deepseek_api_key or None, base_url=s.deepseek_base_url, max_retries=3)


def _thinking_kwargs(effort: str | None) -> dict:
    """effort=None disables thinking (fastest); otherwise "low" | "high" | "max"."""
    if effort is None:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {"reasoning_effort": effort, "extra_body": {"thinking": {"type": "enabled"}}}


def _schema_instructions(output_format: type[BaseModel]) -> str:
    schema = json.dumps(output_format.model_json_schema(), indent=2)
    return (
        "\n\n## Output format\n"
        "Respond with a single json object (no markdown fences, no extra text) that conforms to this JSON schema:\n"
        f"{schema}"
    )


def parse[T: BaseModel](
    *,
    model: str,
    system: str,
    messages: list[dict],
    output_format: type[T],
    max_tokens: int = 16000,  # includes reasoning tokens when thinking is on
    effort: str | None = None,
    usage: Usage | None = None,
) -> T:
    """Structured output call; returns a validated pydantic instance."""
    convo = [{"role": "system", "content": system + _schema_instructions(output_format)}, *messages]
    last_error = "empty response"
    for _attempt in range(2):
        response = client().chat.completions.create(
            model=model,
            messages=convo,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            **_thinking_kwargs(effort),
        )
        if usage is not None:
            usage.add(response.usage)
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise RefusalError("The model declined this request.")
        content = (choice.message.content or "").strip()
        if not content:
            last_error = "empty response"
        elif choice.finish_reason == "length":
            last_error = "response was cut off by max_tokens"
        else:
            try:
                return output_format.model_validate_json(content)
            except ValidationError as e:
                last_error = str(e)
                convo = [
                    *convo,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"That json object did not match the schema:\n{last_error}\n\n"
                        "Reply again with only a corrected json object.",
                    },
                ]
    raise LLMOutputError(f"No valid structured output from {model}: {last_error}")


def stream_text(
    *,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int = 16000,
    effort: str | None = None,
    usage: Usage | None = None,
) -> Iterator[str]:
    """Stream answer text deltas (reasoning tokens are not forwarded)."""
    stream = client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, *messages],
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        **_thinking_kwargs(effort),
    )
    finish_reason = None
    for chunk in stream:
        if chunk.usage is not None and usage is not None:
            usage.add(chunk.usage)
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta and choice.delta.content:
            yield choice.delta.content
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    if finish_reason == "content_filter":
        raise RefusalError("The model declined this request.")
