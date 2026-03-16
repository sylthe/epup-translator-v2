"""Utility helpers for epub-translator."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from json_repair import repair_json

from src.models import Config

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

# Load .env at import time so ANTHROPIC_API_KEY is available everywhere.
# Override=False: existing env vars (set manually or by the shell) take priority.
load_dotenv(override=False)


def extract_json_candidate(text: str) -> str:
    """Extract the most likely JSON object from a raw LLM response."""
    stripped = text.strip()
    fence = _JSON_FENCE_RE.search(stripped)
    if fence:
        return fence.group(1).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def parse_llm_json(text: str, label: str) -> dict[str, Any]:
    """
    Parse JSON from an LLM response using a cascade:
    1. json.loads on the extracted candidate
    2. json_repair for malformed but recoverable JSON
    3. Returns {} (non-fatal)
    """
    candidate = extract_json_candidate(text)
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    try:
        repaired = repair_json(candidate, return_objects=True)
        if isinstance(repaired, dict) and repaired:
            logger.info("JSON repaired for %r", label)
            return repaired
    except Exception:
        pass
    logger.warning("Could not parse JSON for %r — empty result.\nRaw (first 300): %s", label, text[:300])
    return {}


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """Load configuration from a YAML file and return a Config instance."""
    path = Path(config_path)
    if not path.exists():
        return Config()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(**data)
