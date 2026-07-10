from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import EvaluationReport
from ..openrouter import OpenRouterClient
from ..settings import Settings
from ..trace import TraceRecorder


class Evaluator:
    def __init__(self, settings: Settings, trace: TraceRecorder | None = None) -> None:
        self.settings = settings
        self.trace = trace
        self.client = OpenRouterClient(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            trace=trace,
            timeout_seconds=settings.request_timeout_seconds,
        )

    def evaluate(
        self,
        *,
        script_path: Path,
        design_json: dict[str, Any],
        verification_report: dict[str, Any],
        feedback: str | None = None,
    ) -> EvaluationReport:
        if not self.client.available:
            return self._evaluate_locally(script_path, design_json, verification_report, feedback)

        system = (
            "You are an expert Python reviewer. Evaluate the generated scraper code against the specification. "
            "Respond with JSON only and use PASS or FAIL."
        )
        user = {
            "script_path": str(script_path),
            "design": design_json,
            "verification": verification_report,
            "repair_feedback": feedback,
            "requirements": [
                "Standalone Python only.",
                "No LLM calls at runtime.",
                "No CrewAI runtime dependency.",
                "Output JSONL with the required schema.",
                "No regex for field extraction.",
                "India jobs only.",
            ],
        }
        try:
            payload, response = self.client.chat_json(
                model=self.settings.evaluation_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": str(user)}],
                temperature=0.0,
            )
            verdict = str(payload.get("verdict", "FAIL")).upper()
            reasoning = str(payload.get("reasoning", ""))
            findings = list(payload.get("findings", []) or [])
            suggestions = list(payload.get("suggestions", []) or [])
            report = EvaluationReport(
                verdict="PASS" if verdict == "PASS" else "FAIL",
                reasoning=reasoning,
                findings=findings,
                suggestions=suggestions,
                model=response.model,
                raw_response=response.content,
            )
            if self.trace:
                self.trace.log_result("evaluation", report.model_dump())
            return report
        except Exception as exc:
            fallback = self._evaluate_locally(script_path, design_json, verification_report, feedback)
            fallback.reasoning = f"OpenRouter evaluation failed, so local checks were used: {exc}"
            return fallback

    def _evaluate_locally(
        self,
        script_path: Path,
        design_json: dict[str, Any],
        verification_report: dict[str, Any],
        feedback: str | None = None,
    ) -> EvaluationReport:
        text = script_path.read_text(encoding="utf-8")
        findings: list[str] = []
        if "TODO" in text:
            findings.append("Script still contains TODO markers.")
        if "pass" in text and "except" in text:
            findings.append("Potentially weak exception handling detected.")
        if not verification_report.get("passed"):
            findings.append("Verification did not pass.")
        verdict = "PASS" if not findings else "FAIL"
        report = EvaluationReport(
            verdict=verdict,
            reasoning="Local fallback evaluation based on repository and verification signals.",
            findings=findings,
            suggestions=["Use richer site-specific selectors and rerun verification."] if findings else [],
            model=None,
            raw_response=None,
        )
        if self.trace:
            self.trace.log_result("evaluation", report.model_dump())
        return report
