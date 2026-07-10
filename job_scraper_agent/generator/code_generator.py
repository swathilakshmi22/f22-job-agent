from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import GeneratedScraperPlan, SiteProfile
from ..openai_client import OpenAIClient
from ..settings import Settings
from ..trace import TraceRecorder
from ..utils import dedupe_preserve_order, slugify_domain, valid_http_url, write_text


class CodeGenerator:
    def __init__(self, settings: Settings, trace: TraceRecorder | None = None) -> None:
        self.settings = settings
        self.trace = trace
        self.client = OpenAIClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            trace=trace,
            timeout_seconds=settings.request_timeout_seconds,
        )

    def build_plan(
        self,
        *,
        site_profile: SiteProfile,
        repair_feedback: str | None = None,
    ) -> GeneratedScraperPlan:
        fields = self._merge_fields(site_profile)
        plan = GeneratedScraperPlan(
            company_domain=site_profile.company_domain,
            company_slug=slugify_domain(site_profile.company_domain),
            target_country_code=self.settings.target_country_code,
            transport=site_profile.transport if site_profile.transport != "unknown" else "playwright",
            start_urls=dedupe_preserve_order([url for url in site_profile.start_urls if valid_http_url(url)])
            or ([site_profile.career_page] if valid_http_url(site_profile.career_page) else []),
            api_endpoint=site_profile.api_endpoint,
            graphql_endpoint=site_profile.graphql_endpoint,
            graphql_query=site_profile.graphql_query,
            item_selector=site_profile.item_selector,
            container_selector=site_profile.container_selector,
            item_json_path=site_profile.item_json_path,
            pagination=site_profile.pagination,
            field_rules=fields,
            location_rules={"country_code": self.settings.target_country_code, "country": "India"},
            validation_rules={"dedupe": True, "india_only": True, "jsonl": True},
            notes=site_profile.notes,
        )
        if self.client.available:
            try:
                payload, response = self.client.chat_json(
                    model=self.settings.generation_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are Qwen3 Coder. Produce a concise JSON object for a standalone Python scraper plan. "
                                "Do not invent fields; null is acceptable for unknown values."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "site_profile": site_profile.model_dump(),
                                    "repair_feedback": repair_feedback,
                                    "output_schema": GeneratedScraperPlan.model_json_schema(),
                                },
                                indent=2,
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    temperature=0.1,
                )
                payload["company_domain"] = site_profile.company_domain
                payload["company_slug"] = slugify_domain(site_profile.company_domain)
                payload.setdefault("target_country_code", self.settings.target_country_code)
                start_urls = dedupe_preserve_order([url for url in payload.get("start_urls", []) if valid_http_url(url)])
                if not start_urls:
                    start_urls = plan.start_urls
                payload["start_urls"] = start_urls
                plan = GeneratedScraperPlan.model_validate(payload)
                if self.trace:
                    self.trace.log_result("code_generation_plan", {"model": response.model, "plan": plan.model_dump()})
            except Exception as exc:
                if self.trace:
                    self.trace.log_result("code_generation_plan_fallback", {"error": str(exc), "plan": plan.model_dump()})
        return plan

    def render_script(self, plan: GeneratedScraperPlan, output_path: Path) -> Path:
        template_path = self.settings.template_dir / "generated_scraper_template.py.tpl"
        template = template_path.read_text(encoding="utf-8")
        rendered = template.replace("__SCRAPER_PLAN_JSON__", json.dumps(plan.model_dump(), indent=2, ensure_ascii=False))
        rendered = rendered.replace("__COMPANY_DOMAIN__", plan.company_domain)
        rendered = rendered.replace("__COMPANY_SLUG__", plan.company_slug)
        write_text(output_path, rendered)
        return output_path

    def generate(self, site_profile: SiteProfile, repair_feedback: str | None = None, output_path: Path | None = None) -> tuple[GeneratedScraperPlan, str]:
        plan = self.build_plan(site_profile=site_profile, repair_feedback=repair_feedback)
        script_path = output_path or (self.settings.generated_dir / "scraper.py")
        self.render_script(plan, script_path)
        if self.trace:
            self.trace.log_result("generated_script", {"script_path": str(script_path), "company_domain": plan.company_domain})
        return plan, str(script_path)

    def _merge_fields(self, site_profile: SiteProfile) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for field_name in [
            "title",
            "job_id",
            "city",
            "state",
            "country",
            "country_code",
            "url",
            "apply_url",
            "date_posted",
            "date_posted_text",
            "job_description",
            "employment_type",
            "work_type",
            "salary_range",
        ]:
            if field_name in site_profile.field_rules:
                merged[field_name] = site_profile.field_rules[field_name].model_dump()
            else:
                merged[field_name] = {
                    "kind": "json_path",
                    "selector": None,
                    "json_path": None,
                    "attribute": None,
                    "constant": None,
                    "multiple": False,
                }
        return merged
