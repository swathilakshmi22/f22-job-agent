from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Resolve .env from the repo root so the app still loads it when launched
    # from a different working directory.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    discovery_model: str = Field(default="gpt-4.1-mini", alias="DISCOVERY_MODEL")
    investigation_model: str = Field(default="gpt-4.1-mini", alias="INVESTIGATION_MODEL")
    design_model: str = Field(default="gpt-4.1-mini", alias="DESIGN_MODEL")
    generation_model: str = Field(default="gpt-4.1", alias="GENERATION_MODEL")
    evaluation_model: str = Field(default="gpt-4.1", alias="EVALUATION_MODEL")

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
