"""Utility helpers for epub-translator."""

from __future__ import annotations

from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.models import Config

# Load .env at import time so ANTHROPIC_API_KEY is available everywhere.
# Override=False: existing env vars (set manually or by the shell) take priority.
load_dotenv(override=False)


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """Load configuration from a YAML file and return a Config instance."""
    path = Path(config_path)
    if not path.exists():
        return Config()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(**data)
