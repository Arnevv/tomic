from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

import yaml
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Application configuration loaded from YAML and environment."""

    DEFAULT_SYMBOLS: List[str] = Field(default_factory=list)
    POSITIONS_FILE: str = "positions.json"
    ACCOUNT_INFO_FILE: str = "account_info.json"
    JOURNAL_FILE: str = "journal.json"
    VOLATILITY_DATA_FILE: str = "volatility_data.json"
    EXPORT_DIR: str = "exports"
    IB_HOST: str = "127.0.0.1"
    IB_PORT: int = 7497

    class Config:
        env_prefix = ""
        env_file = ".env"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def load_settings() -> Settings:
    """Return settings from base.yaml merged with environment overrides."""
    config_env = os.environ.get("TOMIC_CONFIG")
    if config_env:
        path = Path(config_env)
    else:
        path = Path(__file__).resolve().parent.parent / "config" / "base.yaml"
    data: dict[str, Any] = {}
    if path.exists():
        data = _load_yaml(path)
    return Settings(**data)


settings = load_settings()


def get(name: str, default: Any | None = None) -> Any:
    """Return a configuration value with optional fallback."""
    return getattr(settings, name, default)
