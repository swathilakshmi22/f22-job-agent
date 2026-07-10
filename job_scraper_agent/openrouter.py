from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .trace import TraceRecorder
from .utils import parse_json_from_text


@dataclass
class OpenRouterResponse:
    content: str
    model: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: str = "http://localhost",
        app_name: str = "job_scraper_agent",
        trace: TraceRecorder | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.site_url = site_url
        self.app_name = app_name
        self.trace = trace
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> OpenRouterResponse:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for model calls")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.site_url,
                "X-Title": self.app_name,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

        choices = raw.get("choices") or []
        message = (choices[0] or {}).get("message", {}) if choices else {}
        content = message.get("content", "")
        usage = raw.get("usage") or {}

        if self.trace:
            self.trace.log_llm("model_call", model, messages, content, usage)

        return OpenRouterResponse(content=content, model=model, usage=usage, raw=raw)

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
    ) -> tuple[dict[str, Any], OpenRouterResponse]:
        response = self.chat(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json_from_text(response.content), response
