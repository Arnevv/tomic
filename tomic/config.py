from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel


class AppConfig(BaseModel):
    """Typed configuration loaded from YAML or environment."""

    DEFAULT_SYMBOLS: List[str] = [
        "AAPL",
        "ASML",
        "CRM",
        "DIA",
        "EWG",
        "EWJ",
        "EWZ",
        "FEZ",
        "FXI",
        "GLD",
        "INDA",
        "NVDA",
        "QQQ",
        "RUT",
        "SPY",
        "TSLA",
        "VIX",
        "XLE",
        "XLF",
        "XLV",
    ]
    POSITIONS_FILE: str = "positions.json"
    ACCOUNT_INFO_FILE: str = "account_info.json"
    PORTFOLIO_META_FILE: str = "portfolio_meta.json"
    JOURNAL_FILE: str = "journal.json"
    VOLATILITY_DATA_FILE: str = "volatility_data.json"
    EXPORT_DIR: str = "exports"
    IB_HOST: str = "127.0.0.1"
    IB_PORT: int = 7497
    LOG_LEVEL: str = "INFO"


_BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> Dict[str, Any]:
    """Parse simple KEY=VALUE lines from an .env file."""
    data: Dict[str, Any] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            data[key.strip()] = val.strip()
    return data


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load configuration from a YAML file using PyYAML if available."""
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PyYAML required for YAML config") from exc

    with open(path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
    return content or {}


def load_config() -> AppConfig:
    """Load configuration from .env or YAML file."""
    config_path = os.environ.get("TOMIC_CONFIG")
    if config_path:
        path = Path(config_path)
    else:
        candidates = [
            _BASE_DIR / "config.yaml",
            _BASE_DIR / "config.yml",
            _BASE_DIR / ".env",
        ]
        path = next((p for p in candidates if p.exists()), None)

    data: Dict[str, Any] = {}
    if path and path.exists():
        if path.suffix in {".yaml", ".yml"}:
            try:
                data = _load_yaml(path)
            except Exception:
                data = {}
        else:
            data = _load_env(path)

    cfg = {**AppConfig().dict(), **data}
    return AppConfig(**cfg)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Persist configuration to a YAML file."""
    if path is None:
        env_path = os.environ.get("TOMIC_CONFIG")
        path = Path(env_path) if env_path else _BASE_DIR / "config.yaml"
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PyYAML required for YAML config") from exc
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.dict(), f)


CONFIG = load_config()


def get(name: str, default: Any | None = None) -> Any:
    """Return configuration value for name with optional fallback."""
    return getattr(CONFIG, name, default)


def reload() -> None:
    """Reload configuration from disk into the global CONFIG object."""
    global CONFIG
    CONFIG = load_config()


def update(values: Dict[str, Any]) -> None:
    """Update global configuration with provided key/value pairs and persist."""
    for key, val in values.items():
        if hasattr(CONFIG, key):
            setattr(CONFIG, key, val)
    save_config(CONFIG)
