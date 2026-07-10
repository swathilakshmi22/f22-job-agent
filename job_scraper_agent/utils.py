from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def normalize_domain(domain: str) -> str:
    cleaned = str(domain or "").strip().lower()
    if not cleaned:
        return ""
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        cleaned = parsed.netloc or parsed.path
    else:
        cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned.split("?", 1)[0].split("#", 1)[0]
    cleaned = cleaned.rsplit("@", 1)[-1]
    if ":" in cleaned and not cleaned.startswith("["):
        cleaned = cleaned.split(":", 1)[0]
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned.rstrip(".")


def is_valid_company_domain(domain: str) -> bool:
    normalized = normalize_domain(domain)
    labels = normalized.split(".")
    if len(labels) < 2:
        return False
    if len(labels[-1]) < 2 or not labels[-1].isalpha():
        return False
    for label in labels:
        if not label or label.startswith("-") or label.endswith("-"):
            return False
        if not all(ch.isalnum() or ch == "-" for ch in label):
            return False
    return True


def company_domain_error(domain: str) -> str | None:
    if is_valid_company_domain(domain):
        return None
    return "Please enter a full company domain such as `f22labs.com` or `swissre.com`."


def slugify_domain(domain: str) -> str:
    normalized = normalize_domain(domain)
    parts = [part for part in normalized.split(".") if part]
    if len(parts) >= 2 and parts[0] == "www":
        parts = parts[1:]
    base = parts[0] if parts else normalized
    return "".join(ch if ch.isalnum() else "_" for ch in base).strip("_") or "company"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json_maybe(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json_from_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("No JSON object found in text")


def valid_http_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
