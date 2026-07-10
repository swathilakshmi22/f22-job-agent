from __future__ import annotations

"""Backward-compatible shim for older imports.

The project now uses OpenAI directly, but some files or notebooks may still
import `job_scraper_agent.openrouter`. Keep that path working by re-exporting
the OpenAI client implementation.
"""

from .openai_client import OpenAIClient as OpenRouterClient
from .openai_client import OpenAIResponse as OpenRouterResponse

