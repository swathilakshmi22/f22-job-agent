from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TaskSpec:
    description: str
    expected_output: str
    agent_role: str
    tools: list[Any] | None = None


def build_discovery_task() -> TaskSpec:
    return TaskSpec(
        description="Discover the careers page, hosted ATS, and candidate URLs from the company domain.",
        expected_output="career page, candidate URLs, confidence, ATS type",
        agent_role="Discovery Agent",
    )


def build_investigation_task() -> TaskSpec:
    return TaskSpec(
        description="Inspect the careers site with Playwright and summarize observed network and DOM behavior.",
        expected_output="Site Profile JSON",
        agent_role="Investigation Agent",
    )


def build_design_task() -> TaskSpec:
    return TaskSpec(
        description="Convert the site profile into a scraper design with explicit extraction rules.",
        expected_output="Scraper Design JSON",
        agent_role="Scraper Design Agent",
    )


def build_generation_task() -> TaskSpec:
    return TaskSpec(
        description="Generate a standalone scraper plan for the given site profile and scraper design.",
        expected_output="Generated scraper plan JSON",
        agent_role="Code Generation Agent",
    )


def build_verification_task() -> TaskSpec:
    return TaskSpec(
        description="Execute the generated scraper and validate the emitted jobs.jsonl against the schema.",
        expected_output="Verification report JSON",
        agent_role="Verification Agent",
    )


def build_evaluation_task() -> TaskSpec:
    return TaskSpec(
        description="Review the generated scraper code and return PASS or FAIL with reasoning.",
        expected_output="Evaluation report JSON",
        agent_role="Evaluation Agent",
    )
