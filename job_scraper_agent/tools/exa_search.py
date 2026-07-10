from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request, urlopen

from ..trace import TraceRecorder
from ..utils import valid_http_url


@dataclass
class ExaSearchResult:
    urls: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ExaSearchTool:
    name = "exa_search"
    description = "Search for company careers pages when crawler discovery is inconclusive."

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.exa.ai",
        timeout_seconds: float = 30.0,
        trace: TraceRecorder | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.trace = trace

    def _run(self, company_domain: str) -> dict[str, Any]:
        result = self.search(company_domain)
        return {"urls": result.urls, "raw": result.raw}

    def run(self, company_domain: str) -> dict[str, Any]:
        return self._run(company_domain)

    def search(self, company_domain: str) -> ExaSearchResult:
        if self.api_key:
            try:
                payload = json.dumps({"query": f"site:{company_domain} careers jobs"}).encode("utf-8")
                request = Request(
                    f"{self.base_url}/search",
                    data=payload,
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                urls = [item.get("url") for item in raw.get("results", []) if valid_http_url(item.get("url"))]
                if self.trace:
                    self.trace.log_tool("discovery", self.name, {"company_domain": company_domain}, {"urls": urls[:10]})
                return ExaSearchResult(urls=urls, raw=raw)
            except Exception as exc:
                if self.trace:
                    self.trace.log_tool("discovery", self.name, {"company_domain": company_domain}, {"error": str(exc)})
        return ExaSearchResult()
