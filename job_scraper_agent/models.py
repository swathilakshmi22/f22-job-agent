from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DiscoveryResult(BaseModel):
    company_domain: str
    career_page: str | None = None
    candidate_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    ats_type: str = "unknown"


class PaginationSpec(BaseModel):
    mode: Literal["none", "page", "offset", "cursor", "next_url", "load_more", "infinite_scroll"] = "none"
    page_param: str | None = None
    offset_param: str | None = None
    limit_param: str | None = None
    cursor_path: str | None = None
    next_url_path: str | None = None
    load_more_selector: str | None = None
    scroll_steps: int = 0
    max_pages: int = 50


class FieldRule(BaseModel):
    kind: Literal["json_path", "selector", "attribute", "constant"] = "json_path"
    selector: str | None = None
    json_path: str | None = None
    attribute: str | None = None
    constant: Any | None = None
    multiple: bool = False


class SiteProfile(BaseModel):
    company_domain: str
    career_page: str | None = None
    ats_type: str = "unknown"
    transport: Literal["rest", "graphql", "embedded_json", "html", "playwright", "unknown"] = "unknown"
    start_urls: list[str] = Field(default_factory=list)
    api_endpoint: str | None = None
    graphql_endpoint: str | None = None
    graphql_query: str | None = None
    item_selector: str | None = None
    container_selector: str | None = None
    item_json_path: str | None = None
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)
    field_rules: dict[str, FieldRule] = Field(default_factory=dict)
    candidate_api_endpoints: list[str] = Field(default_factory=list)
    candidate_urls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    raw_observations: dict[str, Any] = Field(default_factory=dict)


class ScraperDesign(BaseModel):
    company_domain: str
    transport: Literal["rest", "graphql", "embedded_json", "html", "playwright"]
    start_urls: list[str] = Field(default_factory=list)
    api_endpoint: str | None = None
    graphql_endpoint: str | None = None
    graphql_query: str | None = None
    item_selector: str | None = None
    container_selector: str | None = None
    item_json_path: str | None = None
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)
    field_rules: dict[str, FieldRule] = Field(default_factory=dict)
    target_country_code: str = "IN"
    notes: list[str] = Field(default_factory=list)


class GeneratedScraperPlan(BaseModel):
    company_domain: str
    company_slug: str
    target_country_code: str = "IN"
    transport: Literal["rest", "graphql", "embedded_json", "html", "playwright"]
    start_urls: list[str] = Field(default_factory=list)
    api_endpoint: str | None = None
    graphql_endpoint: str | None = None
    graphql_query: str | None = None
    item_selector: str | None = None
    container_selector: str | None = None
    item_json_path: str | None = None
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)
    field_rules: dict[str, FieldRule] = Field(default_factory=dict)
    location_rules: dict[str, str | None] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class VerificationIssue(BaseModel):
    severity: Literal["info", "warning", "error"] = "error"
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class VerificationReport(BaseModel):
    passed: bool
    script_path: str
    output_path: str | None = None
    record_count: int = 0
    issues: list[VerificationIssue] = Field(default_factory=list)
    execution_seconds: float = 0.0
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    patch_feedback: str | None = None


class EvaluationReport(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    reasoning: str
    findings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    model: str | None = None
    raw_response: str | None = None


class RunArtifacts(BaseModel):
    company_domain: str
    company_slug: str
    run_dir: str | None = None
    discovery: DiscoveryResult | None = None
    site_profile: SiteProfile | None = None
    generated_script: str | None = None
    readme: str | None = None
    verification: VerificationReport | None = None
    evaluation: EvaluationReport | None = None
    trace_json: str | None = None
    trace_md: str | None = None
    run_log: str | None = None
    smoke_test_passed: bool | None = None
    smoke_test_stdout: str | None = None
    smoke_test_stderr: str | None = None
