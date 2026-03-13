"""Anthropic API client wrapper with retry, token counting, and prompt caching."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import anthropic
import tiktoken

logger = logging.getLogger(__name__)

# Per-model pricing (USD per million tokens)
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0, "output": 15.0,
        "cache_write": 3.75, "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.00,
        "cache_write": 1.00, "cache_read": 0.08,
    },
}
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30}

_CACHE_BETA_HEADER = "prompt-caching-2024-07-31"


class ClaudeClient:
    """
    Async wrapper around anthropic.AsyncAnthropic with:
    - Exponential retry on 429/500/502/503 and timeouts (max 3 retries)
    - Pre-call token counting via tiktoken
    - Prompt caching support (cache_system=True)
    - Per-model cost tracking including cache read/write tokens
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

        try:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoding = None  # type: ignore[assignment]

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cache_creation_tokens: int = 0
        self._total_cache_read_tokens: int = 0
        self._call_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """Estimate the number of tokens in *text* using tiktoken."""
        if self._encoding is None:
            return len(text) // 4
        return len(self._encoding.encode(text))

    async def complete(
        self,
        system: str,
        user: str,
        *,
        cache_system: bool = False,
        max_retries: int = 3,
    ) -> str:
        """
        Send a single-turn chat completion and return the assistant text.

        When cache_system=True, the system prompt is marked for Anthropic's
        prompt caching (beta). Cache reads cost ~10% of normal input price.
        Cache TTL is 5 minutes — sufficient for all segments of one run.
        """
        if cache_system:
            system_param: Any = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
            extra_headers: dict[str, str] = {"anthropic-beta": _CACHE_BETA_HEADER}
        else:
            system_param = system
            extra_headers = {}

        messages = [{"role": "user", "content": user}]
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = 2 ** attempt
                logger.warning("Retry %d/%d after %.0fs", attempt, max_retries, delay)
                await asyncio.sleep(delay)

            try:
                kwargs: dict[str, Any] = dict(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system_param,
                    messages=messages,  # type: ignore[arg-type]
                )
                if extra_headers:
                    kwargs["extra_headers"] = extra_headers

                response = await self._client.messages.create(**kwargs)
                self._record_usage(response.usage)
                return _extract_text(response)

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
        """Return cumulative token counts and estimated costs (USD)."""
        pricing = _MODEL_PRICING.get(self.model, _DEFAULT_PRICING)
        input_cost  = (self._total_input_tokens          / 1_000_000) * pricing["input"]
        output_cost = (self._total_output_tokens          / 1_000_000) * pricing["output"]
        cw_cost     = (self._total_cache_creation_tokens  / 1_000_000) * pricing["cache_write"]
        cr_cost     = (self._total_cache_read_tokens      / 1_000_000) * pricing["cache_read"]
        return {
            "calls": self._call_count,
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "cache_creation_tokens": self._total_cache_creation_tokens,
            "cache_read_tokens": self._total_cache_read_tokens,
            "estimated_cost_usd": round(input_cost + output_cost + cw_cost + cr_cost, 4),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_usage(self, usage: Any) -> None:
        self._call_count += 1
        if usage is not None:
            self._total_input_tokens          += getattr(usage, "input_tokens", 0)
            self._total_output_tokens         += getattr(usage, "output_tokens", 0)
            self._total_cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0)
            self._total_cache_read_tokens     += getattr(usage, "cache_read_input_tokens", 0)


def _extract_text(response: Any) -> str:
    """Extract the first text block from a Messages response."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""
