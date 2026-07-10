from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..generator.code_generator import CodeGenerator
from ..generator.evaluator import Evaluator
from ..generator.verifier import Verifier
from ..models import DiscoveryResult, RunArtifacts, ScraperDesign, SiteProfile
from ..openrouter import OpenRouterClient
from ..settings import Settings
from ..trace import TraceRecorder
from ..tools.exa_search import ExaSearchTool
from ..tools.playwright_tool import PlaywrightTool
from ..tools.you_crawler import YouCrawlerTool
from ..utils import company_domain_error, normalize_domain, slugify_domain, valid_http_url
from .agents import (
    build_discovery_agent,
    build_generation_agent,
    build_investigation_agent,
    build_verification_agent,
)
from .tasks import (
    build_discovery_task,
    build_generation_task,
    build_investigation_task,
    build_verification_task,
)


class JobScraperCrew:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()

    def run(
        self,
        company_domain: str,
        *,
        on_trace_event: Any | None = None,
        run_dir: Path | None = None,
    ) -> RunArtifacts:
        company_domain = normalize_domain(company_domain)
        error_message = company_domain_error(company_domain)
        if error_message:
            raise ValueError(error_message)
        company_slug = slugify_domain(company_domain)
        run_stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        final_run_dir = run_dir or (self.settings.logs_dir / f"{company_slug}_{run_stamp}")
        final_run_dir.mkdir(parents=True, exist_ok=True)
        trace = TraceRecorder(company_domain=company_domain, company_slug=company_slug, enabled=True)
        if on_trace_event is not None:
            trace.subscribe(on_trace_event)
        trace.log("start", "workflow", {"message": f"Workflow: starting for {company_domain}", "company_domain": company_domain})

        openrouter = OpenRouterClient(
            api_key=self.settings.openrouter_api_key,
            base_url=self.settings.openrouter_base_url,
            site_url=self.settings.openrouter_site_url,
            app_name=self.settings.openrouter_app_name,
            trace=trace,
            timeout_seconds=self.settings.request_timeout_seconds,
        )
        you_tool = YouCrawlerTool(
            api_key=self.settings.you_crawler_api_key,
            base_url=self.settings.you_crawler_base_url,
            timeout_seconds=self.settings.request_timeout_seconds,
            trace=trace,
        )
        exa_tool = ExaSearchTool(
            api_key=self.settings.exa_api_key,
            base_url=self.settings.exa_base_url,
            timeout_seconds=self.settings.request_timeout_seconds,
            trace=trace,
        )
        playwright_tool = PlaywrightTool(timeout_seconds=self.settings.request_timeout_seconds, trace=trace)

        _ = build_discovery_agent([you_tool, exa_tool]).create()
        _ = build_investigation_agent([playwright_tool]).create()
        _ = build_generation_agent([]).create()
        _ = build_verification_agent([]).create()
        _ = (
            build_discovery_task(),
            build_investigation_task(),
            build_generation_task(),
            build_verification_task(),
        )

        discovery = self._discover(company_domain, trace, you_tool, exa_tool, openrouter)
        site_profile = self._investigate(company_domain, discovery, trace, playwright_tool, openrouter)
        generator = CodeGenerator(self.settings, trace)

        repair_feedback: str | None = None
        script_path: str | None = None
        verification = None
        evaluation = None
        generated_plan = None
        max_attempts = max(1, min(5, self.settings.max_retry_count))
        for attempt in range(1, max_attempts + 1):
            trace.log("iteration", "codegen", {"message": f"Codegen: writing script (attempt {attempt})", "attempt": attempt})
            generated_plan, script_path = generator.generate(
                site_profile,
                repair_feedback=repair_feedback,
                output_path=final_run_dir / "scraper.py",
            )
            trace.log("result", "codegen", {"message": "Codegen: script written", "script_path": script_path, "attempt": attempt})
            verification = Verifier(self.settings, trace).run(Path(script_path), country_code=self.settings.target_country_code)
            if verification.passed:
                trace.log("result", "verifier", {"message": f"Verifier: approved on attempt {attempt}", "attempt": attempt})
                break
            repair_feedback = verification.patch_feedback or self._compose_feedback(verification.model_dump(), {})
            trace.log(
                "repair",
                "verifier",
                {
                    "message": f"Verifier: attempt {attempt} failed, patching",
                    "attempt": attempt,
                    "issues": [issue.model_dump() for issue in verification.issues],
                    "patch_feedback": repair_feedback,
                },
            )
        if not verification or not verification.passed:
            trace.log("result", "verifier", {"message": "Verifier: did not approve within retry cap", "attempts": max_attempts})

        smoke_passed = False
        smoke_stdout = ""
        smoke_stderr = ""
        if verification and verification.passed:
            smoke_passed, smoke_stdout, smoke_stderr = self._smoke_test_script(Path(script_path) if script_path else None, trace)
            try:
                evaluation = Evaluator(self.settings, trace).evaluate(
                    script_path=Path(script_path) if script_path else final_run_dir / "scraper.py",
                    design_json=generated_plan.model_dump() if generated_plan else site_profile.model_dump(),
                    verification_report=verification.model_dump(),
                    feedback=repair_feedback,
                )
            except Exception as exc:  # pragma: no cover
                trace.log_result("evaluation_fallback", {"message": f"Evaluation failed: {type(exc).__name__}: {exc}"})
        else:
            trace.log("result", "smoke_test", {"message": "Smoke test: skipped because verifier did not approve"})
        readme_path = final_run_dir / "README.md"
        readme_path.write_text(self._build_readme(company_domain, script_path), encoding="utf-8")

        trace_path = final_run_dir / "trace.json"
        trace_md_path = final_run_dir / "trace.md"
        run_log_path = final_run_dir / "run.log"
        llm_summary = trace.llm_usage_summary()
        model_bits = [
            f"{model}: calls={usage['calls']}, tokens={usage['total_tokens']}"
            for model, usage in llm_summary["models"].items()
        ]
        trace.log_result(
            "summary",
            {
                "message": "Run summary: "
                + (f"{llm_summary['calls']} LLM calls" if llm_summary["calls"] else "no LLM calls")
                + (f" | {'; '.join(model_bits)}" if model_bits else ""),
                "llm_usage": llm_summary,
            },
        )
        trace.write(trace_path, trace_md_path)
        run_log_path.write_text(trace.to_plaintext(), encoding="utf-8")

        trace.log(
            "result",
            "handoff",
            {
                "message": "Handoff: wrote scraper.py, README.md, trace.json, trace.md, and run.log",
                "run_dir": str(final_run_dir),
                "script_path": script_path,
                "readme_path": str(readme_path),
                "trace_path": str(trace_path),
                "trace_md_path": str(trace_md_path),
                "run_log_path": str(run_log_path),
            },
        )
        trace.write(trace_path, trace_md_path)
        run_log_path.write_text(trace.to_plaintext(), encoding="utf-8")

        artifacts = RunArtifacts(
            company_domain=company_domain,
            company_slug=company_slug,
            run_dir=str(final_run_dir),
            discovery=discovery,
            site_profile=site_profile,
            generated_script=str(script_path) if script_path else None,
            readme=str(readme_path),
            verification=verification,
            evaluation=evaluation,
            trace_json=str(trace_path),
            trace_md=str(trace_md_path),
            run_log=str(run_log_path),
            smoke_test_passed=smoke_passed,
            smoke_test_stdout=smoke_stdout,
            smoke_test_stderr=smoke_stderr,
        )
        trace.log("end", "workflow", {"message": "Workflow: complete", "run_dir": str(final_run_dir)})
        trace.write(trace_path, trace_md_path)
        run_log_path.write_text(trace.to_plaintext(), encoding="utf-8")
        if on_trace_event is not None:
            try:
                on_trace_event({"timestamp": datetime.now(UTC).isoformat(), "stage": "workflow", "message": "Workflow complete"})
            except Exception:
                pass
        return artifacts

    def _discover(
        self,
        company_domain: str,
        trace: TraceRecorder,
        you_tool: YouCrawlerTool,
        exa_tool: ExaSearchTool,
        openrouter: OpenRouterClient,
    ) -> DiscoveryResult:
        raw_result = you_tool.discover(company_domain)
        result = DiscoveryResult(
            company_domain=company_domain,
            career_page=raw_result.career_page,
            candidate_urls=raw_result.candidate_urls,
            confidence=raw_result.confidence,
            ats_type=raw_result.ats_type,
        )
        if not result.career_page:
            exa = exa_tool.search(company_domain)
            urls = exa.urls
            result.candidate_urls.extend([url for url in urls if url not in result.candidate_urls])
            if urls:
                result.career_page = urls[0]
                result.confidence = max(result.confidence, 0.5)
        if openrouter.available and result.candidate_urls:
            try:
                payload, response = openrouter.chat_json(
                    model=self.settings.discovery_model,
                    messages=[
                        {"role": "system", "content": "Classify the company careers entry points. Return JSON only."},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "company_domain": company_domain,
                                    "career_page": result.career_page,
                                    "candidate_urls": result.candidate_urls,
                                    "confidence": result.confidence,
                                    "ats_type_guess": result.ats_type,
                                },
                                indent=2,
                            ),
                        },
                    ],
                    temperature=0.0,
                )
                result = DiscoveryResult.model_validate(
                    {
                        "company_domain": company_domain,
                        "career_page": payload.get("career_page", result.career_page),
                        "candidate_urls": payload.get("candidate_urls", result.candidate_urls),
                        "confidence": payload.get("confidence", result.confidence),
                        "ats_type": payload.get("ats_type", result.ats_type),
                    }
                )
                trace.log_result(
                    "discovery",
                    {
                        "message": f"Discovery: found {len(result.candidate_urls)} candidates",
                        "model": response.model,
                        "result": result.model_dump(),
                    },
                )
            except Exception as exc:
                trace.log_result("discovery_fallback", {"error": str(exc), "result": result.model_dump()})
        else:
            trace.log_result(
                "discovery",
                {
                    "message": f"Discovery: found {len(result.candidate_urls)} candidates",
                    "result": result.model_dump(),
                },
            )
        return result

    def _investigate(
        self,
        company_domain: str,
        discovery: DiscoveryResult,
        trace: TraceRecorder,
        playwright_tool: PlaywrightTool,
        openrouter: OpenRouterClient,
    ) -> SiteProfile:
        candidates = [url for url in [discovery.career_page, *discovery.candidate_urls] if url]
        observations: list[dict[str, Any]] = []
        for candidate in candidates[:3]:
            try:
                obs = asyncio.run(playwright_tool.inspect(candidate))
                observations.append(obs.__dict__)
            except Exception as exc:
                observations.append({"candidate_url": candidate, "error": str(exc)})

        profile = SiteProfile(
            company_domain=company_domain,
            career_page=discovery.career_page,
            ats_type=discovery.ats_type,
            transport=self._infer_transport(observations),
            start_urls=[url for url in [discovery.career_page, *discovery.candidate_urls] if url],
            candidate_urls=discovery.candidate_urls,
            raw_observations={"observations": observations},
        )

        if openrouter.available and observations:
            try:
                payload, response = openrouter.chat_json(
                    model=self.settings.investigation_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Analyze the observations and return a strict SiteProfile JSON object.",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "company_domain": company_domain,
                                    "discovery": discovery.model_dump(),
                                    "observations": observations,
                                    "schema": SiteProfile.model_json_schema(),
                                },
                                indent=2,
                            ),
                        },
                    ],
                    temperature=0.1,
                )
                payload["company_domain"] = company_domain
                payload.setdefault("career_page", discovery.career_page)
                payload.setdefault("ats_type", discovery.ats_type)
                payload.setdefault("transport", profile.transport)
                start_urls = [url for url in payload.get("start_urls", []) if valid_http_url(url)]
                payload["start_urls"] = start_urls or profile.start_urls
                profile = SiteProfile.model_validate(payload)
                trace.log_result(
                    "investigation",
                    {
                        "message": f"Investigation: source_type={profile.transport}",
                        "model": response.model,
                        "site_profile": profile.model_dump(),
                    },
                )
            except Exception as exc:
                trace.log_result("investigation_fallback", {"error": str(exc), "site_profile": profile.model_dump()})
        else:
            trace.log_result(
                "investigation",
                {
                    "message": f"Investigation: source_type={profile.transport}",
                    "site_profile": profile.model_dump(),
                },
            )
        return profile

    def _design(self, site_profile: SiteProfile, trace: TraceRecorder, openrouter: OpenRouterClient) -> ScraperDesign:
        design = ScraperDesign(
            company_domain=site_profile.company_domain,
            transport=site_profile.transport if site_profile.transport != "unknown" else self._infer_transport_from_profile(site_profile),
            start_urls=site_profile.start_urls,
            api_endpoint=site_profile.api_endpoint,
            graphql_endpoint=site_profile.graphql_endpoint,
            graphql_query=site_profile.graphql_query,
            item_selector=site_profile.item_selector,
            container_selector=site_profile.container_selector,
            item_json_path=site_profile.item_json_path,
            pagination=site_profile.pagination,
            field_rules=site_profile.field_rules,
            target_country_code=self.settings.target_country_code,
            notes=site_profile.notes,
        )

        if openrouter.available:
            try:
                payload, response = openrouter.chat_json(
                    model=self.settings.design_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Create a scraper design with explicit extraction rules and null for unknown values.",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"site_profile": site_profile.model_dump(), "schema": ScraperDesign.model_json_schema()},
                                indent=2,
                            ),
                        },
                    ],
                    temperature=0.0,
                )
                payload.setdefault("company_domain", site_profile.company_domain)
                payload.setdefault("target_country_code", self.settings.target_country_code)
                payload.setdefault("transport", design.transport)
                payload.setdefault("start_urls", design.start_urls)
                design = ScraperDesign.model_validate(payload)
                trace.log_result("design", {"model": response.model, "design": design.model_dump()})
            except Exception as exc:
                trace.log_result("design_fallback", {"error": str(exc), "design": design.model_dump()})
        else:
            trace.log_result("design", design.model_dump())
        return design

    def _compose_feedback(self, verification: dict[str, Any], evaluation: dict[str, Any]) -> str:
        issues = verification.get("issues", [])
        findings = evaluation.get("findings", [])
        return json.dumps({"verification_issues": issues, "evaluation_findings": findings}, indent=2)

    def _infer_transport(self, observations: list[dict[str, Any]]) -> str:
        for observation in observations:
            if observation.get("graphql_requests"):
                return "graphql"
            if observation.get("candidate_api_endpoints"):
                return "rest"
            if observation.get("script_data_keys"):
                return "embedded_json"
        return "html"

    def _infer_transport_from_profile(self, profile: SiteProfile) -> str:
        if profile.graphql_endpoint or profile.graphql_query:
            return "graphql"
        if profile.api_endpoint:
            return "rest"
        if profile.item_json_path:
            return "embedded_json"
        if profile.item_selector:
            return "html"
        return "playwright"

    def _build_readme(self, company_domain: str, script_path: str | None) -> str:
        run_command = "python scraper.py --output jobs.jsonl"
        lines = [
            f"# {company_domain} Scraper",
            "",
            "Standalone scraper generated by the crew.",
            "",
            "## Deliverables",
            "",
            "- `scraper.py`",
            "- `trace.json`",
            "- `trace.md`",
            "- `run.log`",
            "",
            "## Requirements",
            "",
            "- Python 3.10+",
            "- `requests`",
            "- `beautifulsoup4`",
            "- `playwright` if the site requires browser rendering",
            "",
            "## Run",
            "",
            f"```bash\n{run_command}\n```",
            "",
            "The crew keeps JSONL as scratch output only during verification.",
            "The script produces JSONL only when the user runs it - no JSONL shipped by the crew.",
            "The trace includes every tool call, every model call, and a token-usage summary.",
        ]
        if script_path:
            lines.extend(["", f"Generated script: `{Path(script_path).name}`"])
        return "\n".join(lines) + "\n"

    def _smoke_test_script(self, script_path: Path | None, trace: TraceRecorder) -> tuple[bool, str, str]:
        if script_path is None or not script_path.exists():
            return False, "", "Missing generated script"
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Path(tmpdir)
            copied_script = sandbox / script_path.name
            shutil.copy2(script_path, copied_script)
            output_path = sandbox / "jobs.jsonl"
            summary_path = sandbox / "jobs.meta.json"
            trace.log("result", "smoke_test", {"message": "Smoke test: rerunning scraper in a fresh shell"})
            proc = subprocess.run(
                [sys.executable, str(copied_script), "--output", str(output_path), "--summary", str(summary_path)],
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=self.settings.verification_timeout_seconds,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            valid = proc.returncode == 0 and output_path.exists() and self._is_valid_jsonl(output_path)
            trace.log(
                "result",
                "smoke_test",
                {
                    "message": "Smoke test: passed" if valid else "Smoke test: failed",
                    "returncode": proc.returncode,
                    "stdout": stdout[-2000:],
                    "stderr": stderr[-2000:],
                },
            )
            return valid, stdout, stderr

    def _is_valid_jsonl(self, path: Path) -> bool:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                json.loads(line)
            return True
        except Exception:
            return False


def kickoff(
    company_domain: str,
    *,
    settings: Settings | None = None,
    on_trace_event: Any | None = None,
    run_dir: Path | None = None,
) -> RunArtifacts:
    crew = JobScraperCrew(settings or Settings())
    return crew.run(company_domain, on_trace_event=on_trace_event, run_dir=run_dir)
