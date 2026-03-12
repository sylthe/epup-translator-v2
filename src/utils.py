"""Utility helpers for epub-translator."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.models import Config


def load_config(config_path: str | Path = "config.yaml") -> Config:
    """Load configuration from a YAML file and return a Config instance."""
    path = Path(config_path)
    if not path.exists():
        return Config()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(**data)
