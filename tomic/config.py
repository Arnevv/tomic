from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel


def _asdict(model: BaseModel) -> Dict[str, Any]:
    """Return model data as a plain ``dict`` for Pydantic v1 or v2."""
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[attr-defined]
    return model.dict()


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
    VOLATILITY_DB: str = "data/volatility.db"
    EXPORT_DIR: str = "exports"
    IB_HOST: str = "127.0.0.1"
    IB_PORT: int = 7497
    IB_CLIENT_ID: int = 100
    LOG_LEVEL: str = "INFO"
    INTEREST_RATE: float = 0.05
    PRIMARY_EXCHANGE: str = "SMART"
    STRIKE_RANGE: int = 50
    AMOUNT_REGULARS: int = 3
    AMOUNT_WEEKLIES: int = 4
    DELTA_MIN: float = -0.8
    DELTA_MAX: float = 0.8

    # Network tuning -------------------------------------------------
    MAX_CONCURRENT_REQUESTS: int = 5
    CONTRACT_DETAILS_TIMEOUT: int = 2
    CONTRACT_DETAILS_RETRIES: int = 0
    DOWNLOAD_TIMEOUT: int = 10
    DOWNLOAD_RETRIES: int = 2


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

    cfg = {**_asdict(AppConfig()), **data}
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
        yaml.safe_dump(_asdict(config), f)


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
