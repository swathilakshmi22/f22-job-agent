#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
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


SCRAPER_PLAN = json.loads("""__SCRAPER_PLAN_JSON__""")
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
        if not records:
            fallback_records, fallback_summary = self._run_listing_fallback(max_pages)
            if fallback_records:
                records = fallback_records
            summary = {**summary, **fallback_summary}
        deduped = self._dedupe(records)
        return deduped, {**summary, "record_count": len(deduped)}

    def _start_urls(self) -> list[str]:
        urls = [url for url in self.plan.get("start_urls", []) if self._is_http_url(url)]
        urls.extend(url for url in self.plan.get("candidate_urls", []) if self._is_http_url(url))
        domain = str(self.plan.get("company_domain") or "").strip().lower()
        if not urls and self._looks_like_domain(domain):
            urls = [f"https://{domain}"]
        return self._dedupe_urls(urls)

    def _get(self, url: str, **kwargs: Any) -> Any | None:
        try:
            response = self.session.get(url, **kwargs)
            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"
            return response
        except requests.RequestException:
            return None

    def _post_json(self, url: str, payload: dict[str, Any], **kwargs: Any) -> Any | None:
        try:
            response = self.session.post(url, json=payload, **kwargs)
            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding or "utf-8"
            return response
        except requests.RequestException:
            return None

    def _run_rest(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        url = self.plan.get("api_endpoint")
        if not url:
            return self._run_html(max_pages)
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
            response = self._get(url, params=params, timeout=30)
            if response is None or response.status_code >= 400:
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
            response = self._post_json(endpoint, {"query": query, "variables": variables}, timeout=30)
            if response is None or response.status_code >= 400:
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
            response = self._get(start_url, timeout=30)
            if response is None or response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            listing_records = self._records_from_embedded_jobs(soup, start_url)
            if listing_records:
                records.extend(listing_records)
                continue
            payload = self._extract_embedded_json(soup)
            items = self._extract_items_from_json(payload)
            if items:
                records.extend(self._records_from_items(items))
            else:
                record = self._build_record_from_page(soup, start_url)
                if record:
                    records.append(record)
        return records, {"pagination_complete": True}

    def _run_html(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        pagination_complete = False
        item_selector = self.plan.get("item_selector") or ""
        for start_url in self._start_urls():
            current_url = start_url
            for _ in range(max_pages):
                response = self._get(current_url, timeout=30)
                if response is None or response.status_code >= 400:
                    break
                soup = BeautifulSoup(response.text, "html.parser")
                listing_records = self._records_from_embedded_jobs(soup, current_url)
                if listing_records:
                    records.extend(listing_records)
                    pagination_complete = True
                    break
                if item_selector:
                    items = soup.select(item_selector)
                else:
                    items = []
                if items:
                    records.extend(self._records_from_html_items(items, current_url))
                else:
                    record = self._build_record_from_page(soup, current_url)
                    if record:
                        records.append(record)
                    detail_urls = self._collect_candidate_links(soup, current_url)
                    for detail_url in detail_urls[:max_pages]:
                        detail_response = self._get(detail_url, timeout=30)
                        if detail_response is None or detail_response.status_code >= 400:
                            continue
                        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
                        detail_record = self._build_record_from_page(detail_soup, detail_url)
                        if detail_record:
                            records.append(detail_record)
                    if not item_selector:
                        pagination_complete = True
                        break
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
        item_selector = self.plan.get("item_selector") or ""
        if not item_selector:
            return records, {"pagination_complete": True}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for start_url in self._start_urls():
                try:
                    page.goto(start_url, wait_until="networkidle", timeout=60000)
                except Exception:
                    continue
                page.wait_for_timeout(1000)
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                listing_records = self._records_from_embedded_jobs(soup, page.url)
                if listing_records:
                    records.extend(listing_records)
                    continue
                items = soup.select(item_selector)
                if items:
                    records.extend(self._records_from_html_items(items, page.url))
                else:
                    record = self._build_record_from_page(soup, page.url)
                    if record:
                        records.append(record)
                    for detail_url in self._collect_candidate_links(soup, page.url)[:max_pages]:
                        try:
                            page.goto(detail_url, wait_until="networkidle", timeout=60000)
                        except Exception:
                            continue
                        page.wait_for_timeout(1000)
                        detail_soup = BeautifulSoup(page.content(), "html.parser")
                        detail_record = self._build_record_from_page(detail_soup, page.url)
                        if detail_record:
                            records.append(detail_record)
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
        country = self._extract_value(item, fields.get("country"))
        country_code = self._extract_value(item, fields.get("country_code"))
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
        country = self._extract_from_selector(item, fields.get("country"))
        country_code = self._extract_from_selector(item, fields.get("country_code"))
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

    def _build_record_from_page(self, soup: BeautifulSoup, page_url: str) -> dict[str, Any] | None:
        jsonld = self._extract_jobposting_jsonld(soup)
        if not jsonld and not self._looks_like_job_detail_page(soup, page_url):
            return None
        fields = self.plan.get("field_rules", {})
        title = self._first_nonempty(
            [
                self._extract_jsonld_value(jsonld, ("title",)),
                self._extract_meta_content(soup, "og:title"),
                self._extract_meta_content(soup, "twitter:title"),
                self._extract_from_selectors(soup, ["h1", "main h1", "article h1", "title"]),
                self._extract_from_selector(soup, fields.get("title"), page_url=page_url),
            ]
        )
        job_id = self._first_nonempty(
            [
                self._extract_jsonld_value(jsonld, ("identifier", "value")),
                self._extract_jsonld_value(jsonld, ("identifier",)),
                self._job_id_from_url(page_url),
                self._extract_from_selector(soup, fields.get("job_id"), page_url=page_url),
            ]
        )
        location = self._extract_location_from_jobposting(jsonld)
        if not location:
            location = {
                "city": self._extract_from_selector(soup, fields.get("city"), page_url=page_url),
                "state": self._extract_from_selector(soup, fields.get("state"), page_url=page_url),
                "country": self._extract_from_selector(soup, fields.get("country"), page_url=page_url),
                "country_code": self._extract_from_selector(soup, fields.get("country_code"), page_url=page_url),
            }
        url = self._first_nonempty(
            [
                self._extract_from_selector(soup, fields.get("url"), page_url=page_url),
                page_url,
            ]
        )
        apply_url = self._first_nonempty(
            [
                self._extract_from_selector(soup, fields.get("apply_url"), page_url=page_url),
                self._find_apply_url(soup, page_url),
                url,
            ]
        )
        record = {
            "title": title,
            "job_id": job_id,
            "location": location or {"city": None, "state": None, "country": None, "country_code": None},
            "url": url,
            "apply_url": apply_url,
            "date_posted": self._first_nonempty(
                [
                    self._extract_jsonld_value(jsonld, ("datePosted",)),
                    self._extract_from_selector(soup, fields.get("date_posted"), page_url=page_url),
                ]
            ),
            "date_posted_text": self._first_nonempty(
                [
                    self._extract_from_selector(soup, fields.get("date_posted_text"), page_url=page_url),
                    self._extract_meta_content(soup, "article:published_time"),
                ]
            ),
            "job_description": self._first_nonempty(
                [
                    self._extract_jsonld_value(jsonld, ("description",)),
                    self._extract_from_selectors(soup, ["main", "article", "[role='main']"]),
                    self._extract_meta_content(soup, "description"),
                    self._extract_from_selector(soup, fields.get("job_description"), page_url=page_url),
                ]
            ),
            "employment_type": self._first_nonempty(
                [
                    self._extract_jsonld_value(jsonld, ("employmentType",)),
                    self._extract_from_selector(soup, fields.get("employment_type"), page_url=page_url),
                ]
            ),
            "work_type": self._first_nonempty(
                [
                    self._extract_jsonld_value(jsonld, ("jobLocationType",)),
                    self._extract_from_selector(soup, fields.get("work_type"), page_url=page_url),
                ]
            ),
            "salary_range": self._first_nonempty(
                [
                    self._extract_salary_range(jsonld),
                    self._extract_from_selector(soup, fields.get("salary_range"), page_url=page_url),
                ]
            ),
        }
        return record if record.get("title") or record.get("job_id") or record.get("url") else None

    def _records_from_embedded_jobs(self, soup: BeautifulSoup, page_url: str) -> list[dict[str, Any]]:
        jobs = self._extract_hidden_jobs(soup)
        if not jobs:
            return []
        meta = self._extract_hidden_meta(soup)
        return [record for job in jobs if (record := self._record_from_job_object(job, meta, page_url))]

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

    def _extract_from_selectors(self, soup: BeautifulSoup, selectors: list[str]) -> str | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                content = node.get("content")
                if content:
                    return " ".join(str(content).split()) or None
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                return text
        return None

    def _extract_meta_content(self, soup: BeautifulSoup, name: str) -> str | None:
        node = soup.select_one(f'meta[property="{name}"], meta[name="{name}"]')
        if not node:
            return None
        content = node.get("content")
        if not content:
            return None
        return " ".join(str(content).split()) or None

    def _extract_hidden_jobs(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        node = soup.find("input", id="jobs")
        if not node:
            return []
        raw = node.get("value") or ""
        if not raw.strip():
            return []
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _extract_hidden_meta(self, soup: BeautifulSoup) -> dict[str, Any]:
        node = soup.find("input", id="meta")
        if not node:
            return {}
        raw = node.get("value") or ""
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _record_from_job_object(self, job: dict[str, Any], meta: dict[str, Any], page_url: str) -> dict[str, Any] | None:
        title = self._coalesce_text(job.get("Posting_Title") or job.get("Job_Opening_Name"))
        job_id = self._coalesce_text(job.get("id"))
        city = self._coalesce_text(job.get("City"))
        state = self._coalesce_text(job.get("State"))
        country = self._coalesce_text(job.get("Country"))
        country_code = self._country_code_from_country(country)
        detail_url = self._build_job_detail_url(meta, job, page_url)
        record = {
            "title": title,
            "job_id": job_id,
            "location": {
                "city": city,
                "state": state,
                "country": country,
                "country_code": country_code,
            },
            "url": detail_url,
            "apply_url": detail_url,
            "date_posted": self._coalesce_text(job.get("Date_Opened")),
            "date_posted_text": self._coalesce_text(job.get("Date_Opened")),
            "job_description": self._coalesce_text(job.get("Job_Description")),
            "employment_type": self._coalesce_text(job.get("Job_Type")),
            "work_type": self._work_type_from_job(job),
            "salary_range": self._coalesce_text(job.get("Salary")),
        }
        return record if record.get("title") or record.get("job_id") or record.get("url") else None

    def _build_job_detail_url(self, meta: dict[str, Any], job: dict[str, Any], page_url: str) -> str | None:
        job_id = self._coalesce_text(job.get("id"))
        title = self._coalesce_text(job.get("Posting_Title") or job.get("Job_Opening_Name"))
        if not job_id or not title:
            return None
        slug = self._slugify_title(title)
        base = self._coalesce_text(meta.get("list_url")) or page_url
        if not base:
            return None
        base = base.rstrip("/")
        return f"{base}/{job_id}/{slug}?source=CareerSite"

    def _slugify_title(self, value: str) -> str:
        cleaned = []
        for ch in value.strip():
            if ch.isalnum():
                cleaned.append(ch.lower())
            elif cleaned and cleaned[-1] != "-":
                cleaned.append("-")
        slug = "".join(cleaned).strip("-")
        return slug or "job"

    def _work_type_from_job(self, job: dict[str, Any]) -> str | None:
        remote = job.get("Remote_Job")
        if remote is True:
            return "remote"
        if remote is False:
            return "on-site"
        return None

    def _country_code_from_country(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip().lower()
        if normalized == "india":
            return "IN"
        return None

    def _extract_jobposting_jsonld(self, soup: BeautifulSoup) -> dict[str, Any]:
        for payload in self._jsonld_payloads(soup):
            if isinstance(payload, dict):
                types = payload.get("@type")
                if isinstance(types, list):
                    if any(str(item).lower() == "jobposting" for item in types):
                        return payload
                elif str(types).lower() == "jobposting":
                    return payload
        return {}

    def _jsonld_payloads(self, soup: BeautifulSoup) -> list[Any]:
        payloads: list[Any] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            if not text:
                continue
            try:
                data = json.loads(text)
            except Exception:
                continue
            payloads.extend(self._flatten_jsonld(data))
        return payloads

    def _flatten_jsonld(self, data: Any) -> list[Any]:
        if isinstance(data, list):
            items: list[Any] = []
            for item in data:
                items.extend(self._flatten_jsonld(item))
            return items
        if isinstance(data, dict):
            items = [data]
            graph = data.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    items.extend(self._flatten_jsonld(item))
            return items
        return []

    def _extract_jsonld_value(self, payload: dict[str, Any], path: tuple[str, ...]) -> Any:
        current: Any = payload
        for part in path:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        if isinstance(current, dict):
            for key in ("name", "value", "text"):
                value = current.get(key)
                if value:
                    return value
            return None
        if isinstance(current, list):
            values = [str(item).strip() for item in current if item]
            return ", ".join(values) if values else None
        return current

    def _extract_location_from_jobposting(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not payload:
            return None
        job_location = payload.get("jobLocation")
        if isinstance(job_location, list):
            job_location = job_location[0] if job_location else None
        if not isinstance(job_location, dict):
            return None
        address = job_location.get("address")
        if not isinstance(address, dict):
            return None
        city = self._coalesce_text(address.get("addressLocality"))
        state = self._coalesce_text(address.get("addressRegion"))
        country_value = address.get("addressCountry")
        country = self._coalesce_text(country_value)
        country_code = None
        if isinstance(country_value, dict):
            country_code = self._coalesce_text(country_value.get("alternateName") or country_value.get("name"))
            if not country and country_code:
                country = country_code
        elif isinstance(country_value, str) and len(country_value.strip()) == 2:
            country_code = country_value.strip().upper()
        location = {
            "city": city,
            "state": state,
            "country": country,
            "country_code": country_code,
        }
        return location

    def _extract_salary_range(self, payload: dict[str, Any]) -> str | None:
        if not payload:
            return None
        base_salary = payload.get("baseSalary")
        if not isinstance(base_salary, dict):
            return None
        currency = self._coalesce_text(base_salary.get("currency"))
        value = base_salary.get("value")
        if isinstance(value, dict):
            minimum = self._coalesce_text(value.get("minValue"))
            maximum = self._coalesce_text(value.get("maxValue"))
            unit = self._coalesce_text(value.get("unitText"))
            parts = [part for part in [minimum, maximum] if part]
            if parts:
                text = " - ".join(parts)
                if currency:
                    text = f"{currency} {text}"
                if unit:
                    text = f"{text} / {unit}"
                return text
        return currency

    def _find_apply_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.get_text(" ", strip=True).lower().split())
            href = anchor.get("href") or ""
            if any(token in text or token in href.lower() for token in ("apply", "apply now", "submit")):
                return urljoin(page_url, href)
        return None

    def _job_id_from_url(self, url: str) -> str | None:
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return None
        last_part = path_parts[-1]
        if last_part.lower() in {"jobs", "job", "careers", "career", "openings", "vacancies"}:
            return None
        return last_part

    def _collect_candidate_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        links: list[str] = []
        keywords = ("career", "job", "opening", "vacanc", "join", "apply", "role", "position")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href") or ""
            text = " ".join(anchor.get_text(" ", strip=True).lower().split())
            href_lower = href.lower()
            if not href_lower:
                continue
            if any(token in text or token in href_lower for token in keywords):
                full_url = urljoin(page_url, href)
                if self._is_candidate_job_url(full_url) and full_url not in links and full_url != page_url:
                    links.append(full_url)
        return self._dedupe_urls(links)

    def _run_listing_fallback(self, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        records: list[dict[str, Any]] = []
        discovered_links: list[str] = []
        visited: set[str] = set()
        for start_url in self._start_urls():
            if start_url in visited:
                continue
            visited.add(start_url)
            try:
                response = self._get(start_url, timeout=30)
            except Exception:
                continue
            if response is None or response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            record = self._build_record_from_page(soup, start_url)
            if record:
                records.append(record)
            discovered_links.extend(self._collect_candidate_links(soup, start_url))
        for detail_url in self._dedupe_urls(discovered_links)[:max_pages]:
            try:
                response = self._get(detail_url, timeout=30)
            except Exception:
                continue
            if response is None or response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            record = self._build_record_from_page(soup, detail_url)
            if record:
                records.append(record)
        return records, {"pagination_complete": True, "fallback_used": True, "discovered_links": len(discovered_links)}

    def _coalesce_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("name", "value", "text", "code"):
                nested = value.get(key)
                if nested:
                    return self._coalesce_text(nested)
            return None
        if isinstance(value, list):
            values = [self._coalesce_text(item) for item in value]
            values = [item for item in values if item]
            return ", ".join(values) if values else None
        text = " ".join(html.unescape(str(value)).split())
        text = self._repair_mojibake(text)
        return text or None

    def _repair_mojibake(self, text: str) -> str:
        if "â" not in text and "Ã" not in text:
            return text
        try:
            repaired = text.encode("cp1252").decode("utf-8")
        except UnicodeError:
            return text
        if repaired.count("â") + repaired.count("Ã") <= text.count("â") + text.count("Ã"):
            return repaired
        return text

    def _first_nonempty(self, values: list[Any]) -> Any:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

    def _dedupe_urls(self, urls: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for url in urls:
            if not self._is_http_url(url) or url in seen:
                continue
            seen.add(url)
            ordered.append(url)
        return ordered

    def _is_http_url(self, value: str | None) -> bool:
        if not value:
            return False
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _looks_like_domain(self, value: str | None) -> bool:
        if not value or "/" in value:
            return False
        labels = value.split(".")
        if len(labels) < 2 or len(labels[-1]) < 2 or not labels[-1].isalpha():
            return False
        return all(label and all(ch.isalnum() or ch == "-" for ch in label) for label in labels)

    def _is_low_value_page_url(self, value: str | None) -> bool:
        if not self._is_http_url(value):
            return True
        parsed = urlparse(value)
        path_parts = [part.lower() for part in parsed.path.split("/") if part]
        if not path_parts:
            return True
        last_part = path_parts[-1]
        low_value_parts = {
            "search",
            "results",
            "applications",
            "support",
            "help",
            "eeo",
            "legal",
            "privacy",
            "terms",
            "how-we-hire",
            "hiring-process",
        }
        if last_part in low_value_parts or last_part.endswith(".pdf"):
            return True
        return any(part in {"support", "legal", "help"} for part in path_parts)

    def _looks_like_job_detail_page(self, soup: BeautifulSoup, page_url: str) -> bool:
        if self._is_low_value_page_url(page_url):
            return False
        path_parts = [part.lower() for part in urlparse(page_url).path.split("/") if part]
        has_job_path = any(part in {"job", "jobs", "career", "careers", "opening", "openings"} for part in path_parts)
        has_detail_path = has_job_path and len(path_parts) >= 3 and self._job_id_from_url(page_url)
        has_heading = soup.select_one("h1, main h1, article h1") is not None
        has_apply = self._find_apply_url(soup, page_url) is not None
        return bool(has_apply or (has_detail_path and has_heading))

    def _is_candidate_job_url(self, value: str | None) -> bool:
        if not self._is_http_url(value):
            return False
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        if any(domain in host for domain in ("facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com", "youtube.com", "tiktok.com", "pinterest.com")):
            return False
        if self._is_low_value_page_url(value):
            return False
        return any(
            token in host or token in path
            for token in (
                "career",
                "careers",
                "job",
                "jobs",
                "opening",
                "openings",
                "vacanc",
                "join",
                "apply",
                "role",
                "position",
                "recruit",
                "portal",
            )
        )

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
