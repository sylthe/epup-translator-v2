"""Anthropic API client wrapper with retry and token counting."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import anthropic
import tiktoken

logger = logging.getLogger(__name__)

# Token costs per million (update if pricing changes)
_INPUT_COST_PER_MILLION = 3.0   # USD
_OUTPUT_COST_PER_MILLION = 15.0  # USD


class ClaudeClient:
    """
    Async wrapper around anthropic.AsyncAnthropic with:
    - Exponential retry on 429/500/502/503 and timeouts (max 3 retries)
    - Pre-call token counting via tiktoken
    - Cumulative usage tracking for cost estimation
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

        # Tiktoken encoding (cl100k_base is a reasonable proxy for Claude)
        try:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoding = None  # type: ignore[assignment]

        # Cumulative usage
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._call_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """Estimate the number of tokens in *text* using tiktoken."""
        if self._encoding is None:
            return len(text) // 4  # rough fallback
        return len(self._encoding.encode(text))

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_retries: int = 3,
    ) -> str:
        """
        Send a single-turn chat completion and return the assistant text.

        Retries with exponential back-off on transient errors.
        """
        messages = [{"role": "user", "content": user}]
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = 2 ** attempt  # 2, 4, 8 seconds
                logger.warning("Retry %d/%d after %.0fs", attempt, max_retries, delay)
                await asyncio.sleep(delay)

            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system,
                    messages=messages,  # type: ignore[arg-type]
                )
                self._record_usage(response.usage)
                text = _extract_text(response)
                return text

            except anthropic.RateLimitError as exc:
                last_exc = exc
                logger.warning("Rate limit hit: %s", exc)
            except anthropic.APIStatusError as exc:
                if exc.status_code in (500, 502, 503):
                    last_exc = exc
                    logger.warning("Server error %d: %s", exc.status_code, exc)
                else:
                    raise
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
                last_exc = exc
                logger.warning("Connection/timeout error: %s", exc)

        raise RuntimeError(
            f"Claude API failed after {max_retries} retries"
        ) from last_exc

    def get_usage_summary(self) -> dict[str, Any]:
        """Return a dict with cumulative token counts and estimated costs (USD)."""
        input_cost = (self._total_input_tokens / 1_000_000) * _INPUT_COST_PER_MILLION
        output_cost = (self._total_output_tokens / 1_000_000) * _OUTPUT_COST_PER_MILLION
        return {
            "calls": self._call_count,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "total_tokens": self._total_input_tokens + self._total_output_tokens,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_usage(self, usage: Any) -> None:
        self._call_count += 1
        if usage is not None:
            self._total_input_tokens += getattr(usage, "input_tokens", 0)
            self._total_output_tokens += getattr(usage, "output_tokens", 0)


def _extract_text(response: Any) -> str:
    """Extract the first text block from a Messages response."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
