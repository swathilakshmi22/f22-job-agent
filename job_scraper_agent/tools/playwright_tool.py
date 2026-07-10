from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..trace import TraceRecorder
from ..utils import valid_http_url


@dataclass
class PlaywrightObservation:
    url: str
    final_url: str
    title: str | None
    html: str
    text_excerpt: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    responses: list[dict[str, Any]] = field(default_factory=list)
    graphql_requests: list[dict[str, Any]] = field(default_factory=list)
    candidate_api_endpoints: list[str] = field(default_factory=list)
    pagination_hints: list[str] = field(default_factory=list)
    script_data_keys: list[str] = field(default_factory=list)
    dom_hints: list[str] = field(default_factory=list)


class PlaywrightTool:
    name = "playwright_tool"
    description = "Inspect live pages with Playwright, capturing network traffic and DOM structure."

    def __init__(self, timeout_seconds: float = 45.0, trace: TraceRecorder | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.trace = trace

    def _run(self, url: str) -> dict[str, Any]:
        return asyncio.run(self.inspect(url)).__dict__

    def run(self, url: str) -> dict[str, Any]:
        return self._run(url)

    async def inspect(self, url: str) -> PlaywrightObservation:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Playwright is required for investigation") from exc

        requests: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []
        graphql_requests: list[dict[str, Any]] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def on_request(request):
                if request.resource_type in {"xhr", "fetch"}:
                    item = {"method": request.method, "url": request.url, "resource_type": request.resource_type}
                    requests.append(item)
                    if "graphql" in request.url.lower() or "graphql" in (request.post_data or "").lower():
                        graphql_requests.append(item)

            async def on_response(response):
                req = response.request
                if req.resource_type in {"xhr", "fetch"}:
                    responses.append(
                        {
                            "status": response.status,
                            "url": response.url,
                            "method": req.method,
                            "content_type": response.headers.get("content-type", ""),
                        }
                    )

            page.on("request", on_request)
            page.on("response", on_response)
            await page.goto(url, wait_until="networkidle", timeout=int(self.timeout_seconds * 1000))
            await page.wait_for_timeout(1500)
            html = await page.content()
            title = await page.title()
            body_text = await page.locator("body").inner_text()
            text_excerpt = body_text[:4000]

            script_data_keys: list[str] = []
            dom_hints: list[str] = []
            pagination_hints: list[str] = []
            candidate_api_endpoints: list[str] = []

            links = await page.locator("a[href]").evaluate_all(
                """els => els.map(el => ({href: el.href, text: (el.innerText || '').trim()})).slice(0, 400)"""
            )
            for link in links:
                href = link.get("href", "")
                text = link.get("text", "").lower()
                if any(keyword in text or keyword in href.lower() for keyword in ("career", "job", "vacanc", "join")):
                    dom_hints.append(href)
                if valid_http_url(href):
                    candidate_api_endpoints.append(href)

            scripts = await page.locator("script").evaluate_all(
                """els => els.map((el, idx) => ({
                    idx,
                    id: el.id || null,
                    type: el.type || null,
                    text: (el.textContent || '').slice(0, 5000)
                }))"""
            )
            for script in scripts:
                text = script.get("text") or ""
                if "__NEXT_DATA__" in text or "initialstate" in text.lower() or "apollo" in text.lower():
                    script_data_keys.append(f"script-{script.get('idx')}")
                if "load more" in text.lower() or "next" in text.lower():
                    pagination_hints.append("script-pagination-hint")

            pagination_candidates = await page.locator("button, a, [role='button']").evaluate_all(
                """els => els.map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean).slice(0, 200)"""
            )
            for value in pagination_candidates:
                lowered = value.lower()
                if any(token in lowered for token in ("next", "more", "load more", "show more", "view more", "page")):
                    pagination_hints.append(value)

            final_url = page.url
            await browser.close()

        return PlaywrightObservation(
            url=url,
            final_url=final_url,
            title=title,
            html=html,
            text_excerpt=text_excerpt,
            requests=requests,
            responses=responses,
            graphql_requests=graphql_requests,
            candidate_api_endpoints=_dedupe(candidate_api_endpoints),
            pagination_hints=_dedupe(pagination_hints),
            script_data_keys=_dedupe(script_data_keys),
            dom_hints=_dedupe(dom_hints),
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
