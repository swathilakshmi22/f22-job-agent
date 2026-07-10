from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .trace import TraceRecorder
from .utils import parse_json_from_text


@dataclass
class OpenAIResponse:
    content: str
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class OpenAIClient:
    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
        trace: TraceRecorder | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.base_url = base_url.rstrip("/")
        self.trace = trace
        self.timeout_seconds = timeout_seconds
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        ) if self.api_key else None

    @property
    def available(self) -> bool:
        return bool(self._client)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> OpenAIResponse:
        if not self._client:
            raise RuntimeError("OPENAI_API_KEY is required for model calls")

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        choices = getattr(response, "choices", []) or []
        message = choices[0].message if choices else None
        content = getattr(message, "content", "") if message else ""
        usage = self._usage_to_dict(getattr(response, "usage", None))
        raw = self._model_dump(response)

        if self.trace:
            self.trace.log_llm("model_call", model, messages, content, usage)

        return OpenAIResponse(content=content, model=model, usage=usage, raw=raw)

    def chat_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        return self.chat(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens).content

    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], OpenAIResponse]:
        response = self.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return parse_json_from_text(response.content), response

    def _usage_to_dict(self, usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        result: dict[str, Any] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None)
            if value is not None:
                result[key] = value
        return result

    def _model_dump(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        return {"response": str(response)}
