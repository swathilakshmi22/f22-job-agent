from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .crew.crew import JobScraperCrew
from .settings import Settings
from .utils import company_domain_error, normalize_domain


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate standalone job scraper scripts for company domains.")
    parser.add_argument("company_domain", help="Company domain such as swissre.com")
    parser.add_argument("--output-dir", default=None, help="Optional output directory for artifacts")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    company_domain = normalize_domain(args.company_domain)
    error_message = company_domain_error(company_domain)
    if error_message:
        parser.error(error_message)
    settings = Settings()
    if args.output_dir:
        settings.output_dir = Path(args.output_dir)
    settings.ensure_directories()
    crew = JobScraperCrew(settings)
    artifacts = crew.run(company_domain)
    print(artifacts.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
