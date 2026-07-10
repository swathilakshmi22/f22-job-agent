from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import VerificationIssue, VerificationReport
from ..openai_client import OpenAIClient
from ..settings import Settings
from ..trace import TraceRecorder
from ..utils import valid_http_url


REQUIRED_SCHEMA = [
    "title",
    "job_id",
    "location",
    "url",
    "apply_url",
    "date_posted",
    "date_posted_text",
    "job_description",
    "employment_type",
    "work_type",
    "salary_range",
]


class Verifier:
    def __init__(self, settings: Settings, trace: TraceRecorder | None = None) -> None:
        self.settings = settings
        self.trace = trace
        self.client = OpenAIClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            trace=trace,
            timeout_seconds=settings.request_timeout_seconds,
        )

    def run(self, script_path: Path, country_code: str = "IN") -> VerificationReport:
        start = time.perf_counter()
        issues: list[VerificationIssue] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Path(tmpdir)
            copied_script = sandbox / script_path.name
            shutil.copy2(script_path, copied_script)
            output_path = sandbox / "jobs.jsonl"
            summary_path = sandbox / "jobs.meta.json"
            cmd = [sys.executable, str(copied_script), "--output", str(output_path), "--summary", str(summary_path)]
            proc = subprocess.run(
                cmd,
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=self.settings.verification_timeout_seconds,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            if proc.returncode != 0:
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="nonzero_exit",
                        message="Generated scraper exited with a non-zero status.",
                        detail={"returncode": proc.returncode, "stderr": stderr[-2000:]},
                    )
                )

            if not output_path.exists():
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="missing_output",
                        message="jobs.jsonl was not created.",
                        detail={"stdout": stdout[-2000:], "stderr": stderr[-2000:]},
                    )
                )
                report = VerificationReport(
                    passed=False,
                    script_path=str(script_path),
                    output_path=str(output_path),
                    issues=issues,
                    execution_seconds=round(time.perf_counter() - start, 3),
                    exit_code=proc.returncode,
                    stdout=stdout,
                    stderr=stderr,
                )
                report.patch_feedback = self._build_patch_feedback(report)
                self._log(report)
                return report

            records = self._load_jsonl(output_path, issues)
            self._validate_records(records, country_code, issues)
            summary = self._load_summary(summary_path)
            if summary and summary.get("pagination_complete") is False:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        code="pagination_incomplete",
                        message="The scraper reported incomplete pagination.",
                        detail=summary,
                    )
                )
            if self.settings.strict_link_checks:
                self._validate_links(records, issues)

            passed = proc.returncode == 0 and not any(issue.severity == "error" for issue in issues)
            report = VerificationReport(
                passed=passed,
                script_path=str(script_path),
                output_path=str(output_path),
                record_count=len(records),
                issues=issues,
                execution_seconds=round(time.perf_counter() - start, 3),
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                summary=summary or {},
            )
            if not report.passed:
                report.patch_feedback = self._build_patch_feedback(report)
            self._log(report)
            return report

    def _load_jsonl(self, path: Path, issues: list[VerificationIssue]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="invalid_jsonl",
                        message=f"Line {index} is not valid JSON.",
                        detail={"line": index, "error": str(exc)},
                    )
                )
                continue
            fingerprint = record.get("job_id") or record.get("url") or f"line-{index}"
            if fingerprint in seen:
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="duplicate_record",
                        message="Duplicate record detected.",
                        detail={"fingerprint": fingerprint},
                    )
                )
            else:
                seen.add(fingerprint)
            records.append(record)
        return records

    def _validate_records(self, records: list[dict[str, Any]], country_code: str, issues: list[VerificationIssue]) -> None:
        for index, record in enumerate(records, start=1):
            missing = [key for key in REQUIRED_SCHEMA if key not in record]
            if missing:
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="schema_missing",
                        message="A record is missing required fields.",
                        detail={"record_index": index, "missing": missing},
                    )
                )
            location = record.get("location") or {}
            if not isinstance(location, dict):
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="invalid_location",
                        message="Location field must be an object.",
                        detail={"record_index": index},
                    )
                )
                continue
            record_country_code = location.get("country_code")
            record_country = location.get("country")
            if record_country_code and str(record_country_code).upper() != country_code.upper():
                issues.append(
                    VerificationIssue(
                        severity="error",
                        code="country_filter",
                        message="A record is not filtered to the requested country.",
                        detail={"record_index": index, "country_code": record_country_code},
                    )
                )
            elif record_country and str(record_country).lower() != "india" and not record_country_code:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        code="country_ambiguous",
                        message="Location country is ambiguous.",
                        detail={"record_index": index, "country": record_country},
                    )
                )
            for url_field in ("url", "apply_url"):
                if not valid_http_url(record.get(url_field)):
                    issues.append(
                        VerificationIssue(
                            severity="error",
                            code="invalid_url",
                            message=f"{url_field} is not a valid URL.",
                            detail={"record_index": index, "field": url_field, "value": record.get(url_field)},
                        )
                    )

    def _validate_links(self, records: list[dict[str, Any]], issues: list[VerificationIssue]) -> None:
        import urllib.request
        from urllib.error import HTTPError, URLError

        for index, record in enumerate(records, start=1):
            for field in ("url", "apply_url"):
                url = record.get(field)
                if not valid_http_url(url):
                    continue
                request = urllib.request.Request(url, method="HEAD")
                try:
                    with urllib.request.urlopen(request, timeout=10):
                        pass
                except (HTTPError, URLError, TimeoutError) as exc:
                    issues.append(
                        VerificationIssue(
                            severity="warning",
                            code="dead_link",
                            message=f"{field} could not be reached.",
                            detail={"record_index": index, "field": field, "value": url, "error": str(exc)},
                        )
                    )

    def _load_summary(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _log(self, report: VerificationReport) -> None:
        if self.trace:
            self.trace.log_result(
                "verification",
                {
                    "message": "Verifier: approved" if report.passed else "Verifier: failed",
                    "report": report.model_dump(),
                },
            )

    def _build_patch_feedback(self, report: VerificationReport) -> str:
        concrete_evidence = {
            "script_path": report.script_path,
            "output_path": report.output_path,
            "exit_code": report.exit_code,
            "record_count": report.record_count,
            "issues": [issue.model_dump() for issue in report.issues],
            "stdout": report.stdout[-4000:],
            "stderr": report.stderr[-4000:],
            "summary": report.summary,
        }
        if self.client.available:
            try:
                payload, response = self.client.chat_json(
                    model=self.settings.evaluation_model,
                    messages=[
                        {
                            "role": "system",
                        "content": (
                            "Turn verifier failures into a short, concrete patch note for the codegen agent. "
                            "Return JSON only with a single field named patch_feedback."
                        ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(concrete_evidence, indent=2, ensure_ascii=False),
                        },
                    ],
                    temperature=0.0,
                )
                patch_feedback = str(payload.get("patch_feedback") or "").strip()
                if patch_feedback:
                    if self.trace:
                        self.trace.log_result(
                            "patch_feedback",
                            {
                                "message": "Verifier: generated patch feedback",
                                "model": response.model,
                                "patch_feedback": patch_feedback,
                                "evidence": concrete_evidence,
                            },
                        )
                    return patch_feedback
            except Exception as exc:
                if self.trace:
                    self.trace.log_result(
                        "patch_feedback_fallback",
                        {
                            "message": "Verifier: using local failure evidence",
                            "error": str(exc),
                            "evidence": concrete_evidence,
                        },
                    )
        return json.dumps(concrete_evidence, indent=2, ensure_ascii=False)
