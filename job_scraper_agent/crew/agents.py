from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


try:
    from crewai import Agent as CrewAgent  # type: ignore
except Exception:  # pragma: no cover
    CrewAgent = None


@dataclass
class AgentSpec:
    role: str
    goal: str
    tools: list[Any] = field(default_factory=list)
    memory: bool = True
    expected_output: str = ""
    backstory: str = ""
    verbose: bool = True
    llm_model: str | None = None

    def create(self) -> Any:
        if CrewAgent is None:
            return self
        return CrewAgent(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            tools=self.tools,
            memory=self.memory,
            verbose=self.verbose,
            allow_delegation=False,
            llm=None,
        )


def build_discovery_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Discovery Agent",
        goal="Discover the careers page, hosted ATS, and candidate URLs for the company domain.",
        tools=tools,
        expected_output="career page, candidate URLs, confidence, ATS type",
        backstory="You find the best public entry points to jobs without guessing.",
    )


def build_investigation_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Investigation Agent",
        goal="Inspect the careers site using browser automation and determine the extraction strategy.",
        tools=tools,
        expected_output="Site Profile JSON with transport, pagination, selectors, and API clues",
        backstory="You inspect network traffic and DOM structures carefully before proposing a scraper.",
    )


def build_design_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Scraper Design Agent",
        goal="Turn a site profile into a precise scraper design using only observed facts.",
        tools=tools,
        expected_output="Scraper Design JSON with transport choice, pagination, and field rules",
        backstory="You do not infer missing values and you never use regex.",
    )


def build_generation_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Code Generation Agent",
        goal="Generate a standalone production-quality Python scraper script.",
        tools=tools,
        expected_output="A generated scraper plan or code rendering inputs",
        backstory="You write clean, typed, modular code that never depends on LLMs at runtime.",
    )


def build_verification_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Verification Agent",
        goal="Run the generated scraper, validate the JSONL, and report failures clearly.",
        tools=tools,
        expected_output="Verification report with pass/fail and structured issues",
        backstory="You are strict about schema, duplicates, and execution reliability.",
    )


def build_evaluation_agent(tools: list[Any]) -> AgentSpec:
    return AgentSpec(
        role="Evaluation Agent",
        goal="Review the generated code for correctness, robustness, and maintainability.",
        tools=tools,
        expected_output="PASS or FAIL with reasoning",
        backstory="You provide structured code review feedback without rewriting code.",
    )
