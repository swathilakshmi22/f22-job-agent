#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlencode, urlunparse, parse_qsl

try:
    import requests
except Exception as exc:  # pragma: no cover
    raise RuntimeError("requests is required to run the generated scraper") from exc

try:
    from bs4 import BeautifulSoup
except Exception as exc:  # pragma: no cover
    raise RuntimeError("beautifulsoup4 is required to run the generated scraper") from exc


SCRAPER_PLAN = json.loads("""{
  "company_domain": "example.com",
  "company_slug": "example",
  "target_country_code": "IN",
  "transport": "html",
  "start_urls": [
    "https://www.example.com/careers",
    "https://example.com/careers",
    "https://example.com/jobs",
    "https://example.com/join-us",
    "https://example.com/vacancies",
    "https://example.com/work-with-us",
    "https://www.example.com/careers",
    "https://www.example.com/jobs",
    "https://www.example.com/join-us",
    "https://www.example.com/vacancies",
    "https://www.example.com/work-with-us"
  ],
  "api_endpoint": null,
  "graphql_endpoint": null,
  "graphql_query": null,
  "item_selector": null,
  "container_selector": null,
  "item_json_path": null,
  "pagination": {
    "mode": "none",
    "page_param": null,
    "offset_param": null,
    "limit_param": null,
    "cursor_path": null,
    "next_url_path": null,
    "load_more_selector": null,
    "scroll_steps": 0,
    "max_pages": 50
  },
  "field_rules": {
    "title": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "job_id": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "city": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "state": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "country": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "country_code": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "url": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "apply_url": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "date_posted": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "date_posted_text": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "job_description": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "employment_type": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "work_type": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    },
    "salary_range": {
      "kind": "json_path",
      "selector": null,
      "json_path": null,
      "attribute": null,
      "constant": null,
      "multiple": false
    }
  },
  "location_rules": {
    "country_code": "IN",
    "country": "India"
  },
  "validation_rules": {
    "dedupe": true,
    "india_only": true,
    "jsonl": true
  },
  "notes": []
}""")
PLAN: dict[str, Any] = SCRAPER_PLAN
TARGET_COUNTRY_CODE = PLAN.get("target_country_code", "IN")
DEFAULT_OUTPUT = "jobs.jsonl"


@dataclass
class JobRecord:
    title: str | None
    job_id: str | None
    location: dict[str, Any]
    url: str | None
    apply_url: str | None
    date_posted: str | None
    date_posted_text: str | None
    job_description: str | None
    employment_type: str | None
    work_type: str | None
    salary_range: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "job_id": self.job_id,
            "location": self.location,
            "url": self.url,
            "apply_url": self.apply_url,
            "date_posted": self.date_posted,
            "date_posted_text": self.date_posted_text,
            "job_description": self.job_description,
            "employment_type": self.employment_type,
            "work_type": self.work_type,
            "salary_range": self.salary_range,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Scrape jobs for {PLAN.get('company_domain', 'a company')}")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--max-pages", type=int, default=int(PLAN.get("pagination", {}).get("max_pages", 50)))
    return parser.parse_args()


class Scraper:
    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan
        self.session = requests.Session()
        self.seen: set[str] = set()

    def run(self, max_pages: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        transport = self.plan.get("transport", "html")
        if transport == "rest":
            records, summary = self._run_rest(max_pages)
        elif transport == "graphql":
            records, summary = self._run_graphql(max_pages)
        elif transport == "embedded_json":
            records, summary = self._run_embedded_json(max_pages)
        elif transport == "playwright":
            records, summary = self._run_playwright(max_pages)
        else:
            records, summary = self._run_html(max_pages)
        deduped = self._dedupe(records)
        return deduped, {**summary, "record_count": len(deduped)}

    def _start_urls(self) -> list[str]:
        urls = [url for url in self.plan.get("start_urls", []) if url]
        if not urls and self.plan.get("company_domain"):
            urls = [f"https://{self.plan['company_domain']}"]
        return urls

    def _run_rest(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        url = self.plan.get("api_endpoint")
        if not url:
            return [], {"pagination_complete": True}
        pagination = self.plan.get("pagination", {})
        page_param = pagination.get("page_param") or "page"
        offset_param = pagination.get("offset_param")
        limit_param = pagination.get("limit_param")
        cursor_path = pagination.get("cursor_path")
        records: list[dict[str, Any]] = []
        page = 1
        offset = 0
        cursor: str | None = None
        pagination_complete = False
        for _ in range(max_pages):
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            elif offset_param:
                params[offset_param] = offset
                if limit_param:
                    params[limit_param] = 50
            else:
                params[page_param] = page
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code >= 400:
                break
            payload = response.json()
            items = self._extract_items_from_json(payload)
            if not items:
                pagination_complete = True
                break
            records.extend(self._records_from_items(items))
            next_cursor = self._get_json_path(payload, cursor_path) if cursor_path else None
            if next_cursor and next_cursor != cursor:
                cursor = str(next_cursor)
            elif offset_param:
                offset += 50
            else:
                page += 1
            if cursor_path and not next_cursor:
                pagination_complete = True
                break
        return records, {"pagination_complete": pagination_complete}

    def _run_graphql(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        endpoint = self.plan.get("graphql_endpoint") or self.plan.get("api_endpoint")
        query = self.plan.get("graphql_query")
        if not endpoint or not query:
            return [], {"pagination_complete": True}
        records: list[dict[str, Any]] = []
        cursor: str | None = None
        pagination = self.plan.get("pagination", {})
        cursor_path = pagination.get("cursor_path")
        pagination_complete = False
        for _ in range(max_pages):
            variables: dict[str, Any] = {}
            if cursor:
                variables["cursor"] = cursor
            response = self.session.post(endpoint, json={"query": query, "variables": variables}, timeout=30)
            if response.status_code >= 400:
                break
            payload = response.json()
            items = self._extract_items_from_json(payload)
            if not items:
                pagination_complete = True
                break
            records.extend(self._records_from_items(items))
            next_cursor = self._get_json_path(payload, cursor_path) if cursor_path else None
            if next_cursor and next_cursor != cursor:
                cursor = str(next_cursor)
            else:
                pagination_complete = True
                break
        return records, {"pagination_complete": pagination_complete}

    def _run_embedded_json(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for start_url in self._start_urls():
            response = self.session.get(start_url, timeout=30)
            if response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            payload = self._extract_embedded_json(soup)
            items = self._extract_items_from_json(payload)
            if items:
                records.extend(self._records_from_items(items))
        return records, {"pagination_complete": True}

    def _run_html(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        pagination_complete = False
        for start_url in self._start_urls():
            current_url = start_url
            for _ in range(max_pages):
                response = self.session.get(current_url, timeout=30)
                if response.status_code >= 400:
                    break
                soup = BeautifulSoup(response.text, "html.parser")
                items = soup.select(self.plan.get("item_selector") or "")
                if not items:
                    pagination_complete = True
                    break
                records.extend(self._records_from_html_items(items, current_url))
                next_url = self._discover_next_url(soup, current_url)
                if not next_url or next_url == current_url:
                    pagination_complete = True
                    break
                current_url = next_url
        return records, {"pagination_complete": pagination_complete}

    def _run_playwright(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Playwright is required for this scraper plan") from exc
        records: list[dict[str, Any]] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for start_url in self._start_urls():
                page.goto(start_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1000)
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                items = soup.select(self.plan.get("item_selector") or "")
                if items:
                    records.extend(self._records_from_html_items(items, page.url))
                else:
                    records.extend(self._records_from_html_items(soup.select(self.plan.get("item_selector") or ""), page.url))
            browser.close()
        return records, {"pagination_complete": True}

    def _records_from_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in items:
            record = self._build_record(item)
            if record and self._is_india_record(record):
                records.append(record)
        return records

    def _records_from_html_items(self, items: list[Any], page_url: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in items:
            record = self._build_record_from_html(item, page_url)
            if record and self._is_india_record(record):
                records.append(record)
        return records

    def _build_record(self, item: dict[str, Any]) -> dict[str, Any] | None:
        fields = self.plan.get("field_rules", {})
        title = self._extract_value(item, fields.get("title"))
        job_id = self._extract_value(item, fields.get("job_id"))
        city = self._extract_value(item, fields.get("city"))
        state = self._extract_value(item, fields.get("state"))
        country = self._extract_value(item, fields.get("country")) or "India"
        country_code = self._extract_value(item, fields.get("country_code")) or TARGET_COUNTRY_CODE
        url = self._extract_value(item, fields.get("url"))
        apply_url = self._extract_value(item, fields.get("apply_url")) or url
        record = {
            "title": title,
            "job_id": job_id,
            "location": {"city": city, "state": state, "country": country, "country_code": country_code},
            "url": url,
            "apply_url": apply_url,
            "date_posted": self._extract_value(item, fields.get("date_posted")),
            "date_posted_text": self._extract_value(item, fields.get("date_posted_text")),
            "job_description": self._extract_value(item, fields.get("job_description")),
            "employment_type": self._extract_value(item, fields.get("employment_type")),
            "work_type": self._extract_value(item, fields.get("work_type")),
            "salary_range": self._extract_value(item, fields.get("salary_range")),
        }
        return record if record.get("title") or record.get("job_id") or record.get("url") else None

    def _build_record_from_html(self, item: Any, page_url: str) -> dict[str, Any] | None:
        fields = self.plan.get("field_rules", {})
        title = self._extract_from_selector(item, fields.get("title"))
        job_id = self._extract_from_selector(item, fields.get("job_id"))
        city = self._extract_from_selector(item, fields.get("city"))
        state = self._extract_from_selector(item, fields.get("state"))
        country = self._extract_from_selector(item, fields.get("country")) or "India"
        country_code = self._extract_from_selector(item, fields.get("country_code")) or TARGET_COUNTRY_CODE
        url = self._extract_from_selector(item, fields.get("url"), page_url=page_url)
        apply_url = self._extract_from_selector(item, fields.get("apply_url"), page_url=page_url) or url
        record = {
            "title": title,
            "job_id": job_id,
            "location": {"city": city, "state": state, "country": country, "country_code": country_code},
            "url": url,
            "apply_url": apply_url,
            "date_posted": self._extract_from_selector(item, fields.get("date_posted")),
            "date_posted_text": self._extract_from_selector(item, fields.get("date_posted_text")),
            "job_description": self._extract_from_selector(item, fields.get("job_description")),
            "employment_type": self._extract_from_selector(item, fields.get("employment_type")),
            "work_type": self._extract_from_selector(item, fields.get("work_type")),
            "salary_range": self._extract_from_selector(item, fields.get("salary_range")),
        }
        return record if record.get("title") or record.get("job_id") or record.get("url") else None

    def _extract_value(self, item: dict[str, Any], rule: dict[str, Any] | None) -> Any:
        if not rule:
            return None
        kind = rule.get("kind")
        if kind == "constant":
            return rule.get("constant")
        if kind == "json_path":
            return self._get_json_path(item, rule.get("json_path"))
        return None

    def _extract_from_selector(self, item: Any, rule: dict[str, Any] | None, page_url: str | None = None) -> Any:
        if not rule:
            return None
        kind = rule.get("kind")
        if kind == "constant":
            return rule.get("constant")
        selector = rule.get("selector") or ""
        if not selector:
            return None
        target = item.select_one(selector) if hasattr(item, "select_one") else None
        if target is None:
            return None
        attribute = rule.get("attribute")
        if attribute:
            value = target.get(attribute)
            return urljoin(page_url, value) if value and page_url else value
        return " ".join(target.get_text(" ", strip=True).split()) or None

    def _extract_embedded_json(self, soup: BeautifulSoup) -> Any:
        for script in soup.find_all("script"):
            text = script.get_text(strip=True)
            if not text:
                continue
            if "__NEXT_DATA__" in text or text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    return json.loads(text[start : end + 1])
        return {}

    def _extract_items_from_json(self, payload: Any) -> list[dict[str, Any]]:
        path = self.plan.get("item_json_path")
        if not path:
            if isinstance(payload, dict):
                for key in ("jobs", "results", "data", "items", "positions"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, dict)]
            return []
        value = self._get_json_path(payload, path)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _get_json_path(self, payload: Any, path: str | None) -> Any:
        if not path:
            return None
        current = payload
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, list):
                if not part.isdigit():
                    return None
                index = int(part)
                if index >= len(current):
                    return None
                current = current[index]
                continue
            if isinstance(current, dict):
                current = current.get(part)
                continue
            return None
        return current

    def _discover_next_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        pagination = self.plan.get("pagination", {})
        selector = pagination.get("load_more_selector")
        if selector:
            node = soup.select_one(selector)
            if node and node.get("href"):
                return urljoin(page_url, node.get("href"))
        next_link = soup.find("a", attrs={"rel": "next"})
        if next_link and next_link.get("href"):
            return urljoin(page_url, next_link.get("href"))
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.get_text(" ", strip=True).lower().split())
            if "next" in text or "more" in text:
                return urljoin(page_url, anchor.get("href"))
        return None

    def _is_india_record(self, record: dict[str, Any]) -> bool:
        location = record.get("location") or {}
        country_code = (location.get("country_code") or "").upper()
        country = (location.get("country") or "").lower()
        if country_code and country_code != TARGET_COUNTRY_CODE.upper():
            return False
        if country and country != "india" and not country_code:
            return False
        return True

    def _dedupe(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for record in records:
            fingerprint = record.get("job_id") or record.get("url") or record.get("title")
            if not fingerprint:
                continue
            if fingerprint in self.seen:
                continue
            self.seen.add(fingerprint)
            deduped.append(record)
        return deduped


def main() -> int:
    args = parse_args()
    scraper = Scraper(PLAN)
    records, summary = scraper.run(max_pages=args.max_pages)
    output_path = Path(args.output)
    output_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + ("\n" if records else ""),
        encoding="utf-8",
    )
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
