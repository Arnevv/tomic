from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

# Default settings used when no config file is provided
DEFAULTS: Dict[str, Any] = {
    "DEFAULT_SYMBOLS": [
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
    ],
    "POSITIONS_FILE": "positions.json",
    "ACCOUNT_INFO_FILE": "account_info.json",
    "PORTFOLIO_META_FILE": "portfolio_meta.json",
    "JOURNAL_FILE": "journal.json",
    "VOLATILITY_DATA_FILE": "volatility_data.json",
    "EXPORT_DIR": "exports",
    "IB_HOST": "127.0.0.1",
    "IB_PORT": 7497,
}

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


def load_config() -> Dict[str, Any]:
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
    cfg = DEFAULTS.copy()
    cfg.update(data)
    return cfg


CONFIG = load_config()


def get(name: str, default: Any | None = None) -> Any:
    """Return configuration value for name with optional fallback."""
    return CONFIG.get(name, default)
