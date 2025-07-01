from __future__ import annotations

import os
import threading
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
    PRICE_HISTORY_DIR: str = "tomic/data/spot_prices"
    IV_HISTORY_DIR: str = "tomic/data/iv_history"
    IV_DAILY_SUMMARY_DIR: str = "tomic/data/iv_daily_summary"
    IV_DEBUG_DIR: str = "iv_debug"
    HISTORICAL_VOLATILITY_DIR: str = "tomic/data/historical_volatility"
    EXPORT_DIR: str = "exports"
    IB_HOST: str = "127.0.0.1"
    IB_PORT: int = 7497
    IB_CLIENT_ID: int = 100
    DATA_PROVIDER: str = "ib"
    POLYGON_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    INTEREST_RATE: float = 0.05
    # Default venues for retrieving market data
    UNDERLYING_EXCHANGE: str = "SMART"
    UNDERLYING_PRIMARY_EXCHANGE: str = "ARCA"
    OPTIONS_EXCHANGE: str = "SMART"
    OPTIONS_PRIMARY_EXCHANGE: str = "ARCA"
    STRIKE_RANGE: int = 50
    STRIKE_STDDEV_MULTIPLIER: float = 1.0
    AMOUNT_REGULARS: int = 3
    AMOUNT_WEEKLIES: int = 4
    FIRST_EXPIRY_MIN_DTE: int = 15
    DELTA_MIN: float = -0.8
    DELTA_MAX: float = 0.8
    USE_HISTORICAL_IV_WHEN_CLOSED: bool = True
    INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN: bool = True

    # Parameters for IV history snapshots -------------------------------
    IV_TRACKING_DELTAS: List[float] = [0.25, 0.5]
    IV_EXPIRY_LOOKAHEAD_DAYS: List[int] = [0, 30, 60]

    # Network tuning -------------------------------------------------
    MAX_CONCURRENT_REQUESTS: int = 5
    CONTRACT_DETAILS_TIMEOUT: int = 2
    CONTRACT_DETAILS_RETRIES: int = 0
    DOWNLOAD_TIMEOUT: int = 10
    DOWNLOAD_RETRIES: int = 2
    BID_ASK_TIMEOUT: int = 5
    MARKET_DATA_TIMEOUT: int = 120
    OPTION_DATA_RETRIES: int = 0
    OPTION_RETRY_WAIT: int = 1
    OPTION_PARAMS_TIMEOUT: int = 20
    OPTION_MAX_MARKETDATA_TIME: int = 30

    # Historical and market data settings ---------------------------------
    HIST_DURATION: str = "1 D"
    HIST_BARSIZE: str = "1 day"
    HIST_WHAT: str = "TRADES"
    MKT_GENERIC_TICKS: str = "100,101,106"

    # Polygon API tuning
    POLYGON_SLEEP_BETWEEN: float = 1.2
    POLYGON_DELAY_SNAPSHOT_MS: int = 200
    MAX_SYMBOLS_PER_RUN: int | None = None
    POLYGON_API_KEYS: List[str] = []


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
    """Load configuration from a YAML file.

    Falls back to a very small built-in parser when ``PyYAML`` is not
    available. The fallback supports simple ``key: value`` pairs with
    boolean, integer and floating point values.
    """
    try:
        import yaml  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        data: Dict[str, Any] = {}
        current_key: str | None = None
        for line in path.read_text().splitlines():
            line = line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            if (
                line.startswith("- ")
                and current_key
                and isinstance(data.get(current_key), list)
            ):
                data[current_key].append(line[2:].strip())
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if not val:
                    data[key] = []
                    current_key = key
                    continue
                current_key = key
                low = val.lower()
                if low in {"true", "false"}:
                    data[key] = low == "true"
                    continue
                if low in {"null", "none"}:
                    data[key] = None
                    continue
                if val.lower() in {"null", "none"}:
                    data[key] = None
                    continue
                try:
                    if "." in val:
                        data[key] = float(val)
                    else:
                        data[key] = int(val)
                except ValueError:
                    data[key] = val
        return data
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
    if "POLYGON_API_KEYS" in cfg and isinstance(cfg["POLYGON_API_KEYS"], str):
        cfg["POLYGON_API_KEYS"] = [
            k.strip() for k in cfg["POLYGON_API_KEYS"].split(",") if k.strip()
        ]
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
LOCK = threading.Lock()


def get(name: str, default: Any | None = None) -> Any:
    """Return configuration value for name with optional fallback.

    Both reads and writes are synchronized using ``LOCK`` so concurrent
    access from multiple threads is safe.
    """
    with LOCK:
        return getattr(CONFIG, name, default)


def reload() -> None:
    """Reload configuration from disk into the global CONFIG object."""
    global CONFIG
    with LOCK:
        CONFIG = load_config()


def update(values: Dict[str, Any]) -> None:
    """Update global configuration with provided key/value pairs and persist."""
    with LOCK:
        for key, val in values.items():
            if hasattr(CONFIG, key):
                setattr(CONFIG, key, val)
        save_config(CONFIG)
