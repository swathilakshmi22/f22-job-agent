from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from ..trace import TraceRecorder
from ..utils import dedupe_preserve_order, valid_http_url


CAREERS_KEYWORDS = ("career", "careers", "jobs", "job", "join-us", "joinus", "work-with-us", "vacancies")


@dataclass
class YouCrawlerResult:
    career_page: str | None
    candidate_urls: list[str] = field(default_factory=list)
    confidence: float = 0.0
    ats_type: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


class YouCrawlerTool:
    name = "you_crawler"
    description = "Discover careers pages and likely ATS entry points."

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.ydc-index.io",
        timeout_seconds: float = 30.0,
        trace: TraceRecorder | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.trace = trace

    def _run(self, company_domain: str) -> dict[str, Any]:
        result = self.discover(company_domain)
        return {
            "career_page": result.career_page,
            "candidate_urls": result.candidate_urls,
            "confidence": result.confidence,
            "ats_type": result.ats_type,
            "raw": result.raw,
        }

    def run(self, company_domain: str) -> dict[str, Any]:
        return self._run(company_domain)

    def discover(self, company_domain: str) -> YouCrawlerResult:
        if self.api_key:
            try:
                result = self._discover_with_api(company_domain)
                if result.career_page:
                    return result
            except Exception as exc:
                if self.trace:
                    self.trace.log_tool("discovery", self.name, {"company_domain": company_domain}, {"error": str(exc)})

        fallback = self._discover_locally(company_domain)
        if self.trace:
            self.trace.log_tool(
                "discovery",
                self.name,
                {"company_domain": company_domain},
                {
                    "career_page": fallback.career_page,
                    "candidate_urls": fallback.candidate_urls,
                    "confidence": fallback.confidence,
                    "ats_type": fallback.ats_type,
                },
            )
        return fallback

    def _discover_with_api(self, company_domain: str) -> YouCrawlerResult:
        payload = json.dumps({"query": f"site:{company_domain} careers jobs"}).encode("utf-8")
        request = Request(
            f"{self.base_url}/search",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        results = raw.get("results") or raw.get("hits") or []
        urls = dedupe_preserve_order([item.get("url") for item in results if valid_http_url(item.get("url"))])
        career_page = self._pick_career_page(urls)
        return YouCrawlerResult(
            career_page=career_page,
            candidate_urls=urls[:25],
            confidence=0.8 if career_page else 0.4,
            raw=raw,
        )

    def _discover_locally(self, company_domain: str) -> YouCrawlerResult:
        roots = [f"https://{company_domain}", f"https://www.{company_domain}"]
        candidates: list[str] = []
        for root in roots:
            candidates.extend(self._extract_candidate_urls(root))
        candidates = dedupe_preserve_order(candidates)
        career_page = self._pick_career_page(candidates)
        confidence = 0.7 if career_page else (0.3 if candidates else 0.0)
        ats_type = self._classify_ats(career_page or "")
        return YouCrawlerResult(career_page=career_page, candidate_urls=candidates[:50], confidence=confidence, ats_type=ats_type)

    def _extract_candidate_urls(self, root_url: str) -> list[str]:
        try:
            with urlopen(root_url, timeout=self.timeout_seconds) as response:
                html = response.read().decode("utf-8", errors="ignore")
        except Exception:
            return []
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            if not href:
                continue
            text = " ".join(anchor.get_text(" ", strip=True).lower().split())
            href_lower = href.lower()
            if any(keyword in href_lower or keyword in text for keyword in CAREERS_KEYWORDS):
                full_url = urljoin(root_url, href)
                if valid_http_url(full_url) and full_url not in seen:
                    seen.add(full_url)
                    urls.append(full_url)
        for prefix in ("/careers", "/jobs", "/join-us", "/vacancies", "/work-with-us"):
            candidate = urljoin(root_url, prefix)
            if candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)
        return dedupe_preserve_order(urls)

    def _pick_career_page(self, urls: list[str]) -> str | None:
        if not urls:
            return None
        scored = sorted(urls, key=self._score_url, reverse=True)
        return scored[0]

    def _score_url(self, url: str) -> tuple[int, int]:
        lowered = url.lower()
        score = sum(1 for keyword in CAREERS_KEYWORDS if keyword in lowered)
        return score, len(url)

    def _classify_ats(self, url: str) -> str:
        lowered = url.lower()
        if "workday" in lowered:
            return "workday"
        if "greenhouse" in lowered:
            return "greenhouse"
        if "lever" in lowered:
            return "lever"
        if "successfactors" in lowered:
            return "successfactors"
        if "eightfold" in lowered:
            return "eightfold"
        if "oracle" in lowered:
            return "oracle"
        if "sap" in lowered:
            return "sap"
        return "custom" if url else "unknown"
