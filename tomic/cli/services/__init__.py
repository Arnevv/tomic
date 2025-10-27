from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from tomic import config as cfg
from tomic.api.market_export import ExportResult, export_option_chain
from tomic.providers.polygon_iv import fetch_polygon_option_chain
from .earnings_alpha import update_alpha_earnings
from .iv_polygon import fetch_polygon_iv_data
from .price_history_ib import fetch_ib_daily_prices
from .price_history_polygon import fetch_polygon_price_history
from .volatility import (
    compute_polygon_volatility_stats,
    compute_volatility_stats,
    fetch_iv30d,
)


def _latest_export_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    subdirs = [d for d in base.iterdir() if d.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda d: d.stat().st_mtime)


def find_latest_chain(symbol: str, base: Path | None = None) -> Path | None:
    if base is None:
        base = Path(cfg.get("EXPORT_DIR", "exports"))
    if not base.exists():
        return None
    pattern = f"option_chain_{symbol.upper()}_*.csv"
    chains = list(base.rglob(pattern))
    if not chains:
        return None
    return max(chains, key=lambda p: p.stat().st_mtime)


def export_chain(symbol: str) -> Path | None:
    res = export_option_chain(symbol, return_status=True)
    if isinstance(res, ExportResult) and not res.ok:
        return None
    return find_latest_chain(symbol)


def fetch_polygon_chain(symbol: str) -> Path | None:
    fetch_polygon_option_chain(symbol)
    base = Path(cfg.get("EXPORT_DIR", "exports"))
    date_dir = base / datetime.now().strftime("%Y%m%d")
    pattern = f"{symbol.upper()}_*-optionchainpolygon.csv"
    files = list(date_dir.glob(pattern)) if date_dir.exists() else []
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)


def git_commit(message: str, *dirs: Path | str) -> bool:
    subprocess.run(["git", "status", "--short"], check=True)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    if not result.stdout.strip():
        return False
    files: list[Path] = []
    for d in dirs:
        p = Path(d)
        files.extend(p.glob("*.json"))
    if not files:
        return False
    subprocess.run(["git", "add", *[str(f) for f in files]], check=True)
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)
    return True


__all__ = [
    "export_chain",
    "fetch_ib_daily_prices",
    "fetch_polygon_price_history",
    "fetch_polygon_iv_data",
    "compute_volatility_stats",
    "compute_polygon_volatility_stats",
    "fetch_iv30d",
    "find_latest_chain",
    "fetch_polygon_chain",
    "git_commit",
    "update_alpha_earnings",
]
