from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .utils import ensure_parent


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TraceRecorder:
    company_domain: str
    company_slug: str
    enabled: bool = True
    listeners: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now)
    _perf_start: float = field(default_factory=perf_counter)

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self.listeners.append(callback)

    def log(self, event_type: str, stage: str, payload: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        event = {
            "timestamp": utc_now(),
            "elapsed_seconds": round(perf_counter() - self._perf_start, 3),
            "event_type": event_type,
            "stage": stage,
            "payload": payload or {},
        }
        self.events.append(event)
        for callback in list(self.listeners):
            try:
                callback(event)
            except Exception:
                pass

    def log_llm(
        self,
        stage: str,
        model: str,
        messages: list[dict[str, Any]],
        response: str,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.log("llm", stage, {"model": model, "messages": messages, "response": response, "usage": usage or {}})

    def log_tool(self, stage: str, tool_name: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        self.log("tool", stage, {"tool": tool_name, "inputs": inputs, "outputs": outputs})

    def log_result(self, stage: str, result: dict[str, Any]) -> None:
        self.log("result", stage, result)

    def llm_usage_summary(self) -> dict[str, Any]:
        models: dict[str, dict[str, int]] = {}
        calls = 0
        for event in self.events:
            if event.get("event_type") != "llm":
                continue
            calls += 1
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            model = str(payload.get("model") or "unknown")
            usage = payload.get("usage") or {}
            model_summary = models.setdefault(
                model,
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
            model_summary["calls"] += 1
            if isinstance(usage, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    try:
                        model_summary[key] += int(usage.get(key) or 0)
                    except Exception:
                        pass
        return {"calls": calls, "models": models}

    def summary(self) -> dict[str, Any]:
        stage_counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        for event in self.events:
            stage = str(event.get("stage") or "workflow")
            event_type = str(event.get("event_type") or "result")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        return {
            "event_count": len(self.events),
            "stage_counts": stage_counts,
            "event_type_counts": event_counts,
            "llm_usage": self.llm_usage_summary(),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "company_domain": self.company_domain,
            "company_slug": self.company_slug,
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "events": self.events,
            "summary": self.summary(),
        }

    def to_markdown(self) -> str:
        lines = [f"# Trace for {self.company_domain}", "", f"- Started: {self.started_at}", ""]
        for event in self.events:
            lines.append(
                f"- [{event['timestamp']}] {event['stage']} {event['event_type']} ({event['elapsed_seconds']}s)"
            )
            payload = event.get("payload", {})
            if payload:
                summary = json.dumps(payload, ensure_ascii=False)[:2000]
                lines.append(f"  - `{summary}`")
        summary = self.summary()
        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- Events: {summary['event_count']}",
                f"- LLM calls: {summary['llm_usage']['calls']}",
            ]
        )
        for model, usage in summary["llm_usage"]["models"].items():
            lines.append(
                f"- {model}: calls={usage['calls']}, prompt_tokens={usage['prompt_tokens']}, "
                f"completion_tokens={usage['completion_tokens']}, total_tokens={usage['total_tokens']}"
            )
        return "\n".join(lines) + "\n"

    def to_plaintext(self) -> str:
        lines: list[str] = []
        for event in self.events:
            payload = event.get("payload", {})
            message = payload.get("message") if isinstance(payload, dict) else None
            if not message:
                summary = payload.get("summary") if isinstance(payload, dict) else None
                if summary:
                    message = summary
            if not message and isinstance(payload, dict) and payload:
                message = f"{event['stage']}: {json.dumps(payload, ensure_ascii=False)[:1000]}"
            if not message:
                message = f"{event['stage']}"
            lines.append(str(message))
        summary = self.summary()
        lines.append("")
        lines.append("Summary:")
        lines.append(f"  events={summary['event_count']}")
        lines.append(f"  llm_calls={summary['llm_usage']['calls']}")
        for model, usage in summary["llm_usage"]["models"].items():
            lines.append(
                f"  {model}: calls={usage['calls']}, prompt_tokens={usage['prompt_tokens']}, "
                f"completion_tokens={usage['completion_tokens']}, total_tokens={usage['total_tokens']}"
            )
        return "\n".join(lines) + "\n"

    def write(self, json_path: Path, md_path: Path) -> None:
        if not self.enabled:
            return
        ensure_parent(json_path)
        ensure_parent(md_path)
        json_path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
