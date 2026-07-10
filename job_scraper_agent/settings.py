from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    openrouter_site_url: str = Field(default="http://localhost", alias="OPENROUTER_SITE_URL")
    openrouter_app_name: str = Field(default="job_scraper_agent", alias="OPENROUTER_APP_NAME")
    discovery_model: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="DISCOVERY_MODEL")
    investigation_model: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="INVESTIGATION_MODEL")
    design_model: str = Field(default="deepseek/deepseek-chat-v3-0324", alias="DESIGN_MODEL")
    generation_model: str = Field(default="qwen/qwen3-coder", alias="GENERATION_MODEL")
    evaluation_model: str = Field(default="openai/gpt-4.1", alias="EVALUATION_MODEL")

    you_crawler_api_key: str | None = Field(default=None, alias="YOU_CRAWLER_API_KEY")
    you_crawler_base_url: str = Field(default="https://api.ydc-index.io", alias="YOU_CRAWLER_BASE_URL")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    exa_base_url: str = Field(default="https://api.exa.ai", alias="EXA_BASE_URL")

    target_country_code: str = Field(default="IN", alias="TARGET_COUNTRY_CODE")
    max_retry_count: int = Field(default=3, alias="MAX_RETRY_COUNT")
    request_timeout_seconds: float = Field(default=30.0, alias="REQUEST_TIMEOUT_SECONDS")
    verification_timeout_seconds: float = Field(default=600.0, alias="VERIFICATION_TIMEOUT_SECONDS")
    strict_link_checks: bool = Field(default=False, alias="STRICT_LINK_CHECKS")
    verbose_tracing: bool = Field(default=True, alias="VERBOSE_TRACING")

    output_dir: Path = Field(default=Path("outputs"), alias="OUTPUT_DIR")
    generated_dir: Path = Field(default=Path("generated"), alias="GENERATED_DIR")
    trace_dir: Path = Field(default=Path("traces"), alias="TRACE_DIR")
    logs_dir: Path = Field(default=Path("logs"), alias="LOGS_DIR")
    template_dir: Path = Field(default=Path("templates"), alias="TEMPLATE_DIR")

    smoke_test_domains: list[str] = Field(
        default_factory=lambda: ["swissre.com", "adidas.com", "siemens.com", "shell.com"],
        alias="SMOKE_TEST_DOMAINS",
    )

    def ensure_directories(self) -> None:
        for path in (self.output_dir, self.generated_dir, self.trace_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
