from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tomic import config as cfg
from tomic.services.chain_sources import (
    ChainSourceDecision,
    ChainSourceError,
    ChainSourceName,
    PolygonFileAdapter,
    resolve_chain_source,
)

if TYPE_CHECKING:  # pragma: no cover - import hints only
    from .iv_polygon import fetch_polygon_iv_data
    from .price_history_ib import fetch_ib_daily_prices
    from .price_history_polygon import fetch_polygon_price_history
    from .volatility import (
        compute_polygon_volatility_stats,
        compute_volatility_stats,
        fetch_iv30d,
    )
    from tomic.providers.polygon_iv import fetch_polygon_option_chain


_LAZY_ATTRS = {
    "fetch_polygon_iv_data": "tomic.cli.services.iv_polygon",
    "fetch_ib_daily_prices": "tomic.cli.services.price_history_ib",
    "fetch_polygon_price_history": "tomic.cli.services.price_history_polygon",
    "compute_polygon_volatility_stats": "tomic.cli.services.volatility",
    "compute_volatility_stats": "tomic.cli.services.volatility",
    "fetch_iv30d": "tomic.cli.services.volatility",
    "fetch_polygon_option_chain": "tomic.providers.polygon_iv",
}


def __getattr__(name: str):
    module_name = _LAZY_ATTRS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name)
    attr = getattr(module, name)
    globals()[name] = attr
    return attr


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
    raise ChainSourceError(
        "TWS option-chain export is verwijderd. Gebruik Polygon-paden."
    )


def fetch_polygon_chain(symbol: str) -> Path | None:
    try:
        decision = resolve_chain_decision(symbol, source="polygon")
    except ChainSourceError:
        return None
    return decision.path


def _polygon_adapter() -> PolygonFileAdapter:
    fetcher = globals().get("fetch_polygon_option_chain")
    if fetcher is None:
        from tomic.providers.polygon_iv import fetch_polygon_option_chain as _fetcher

        fetcher = _fetcher

    export_dir = Path(cfg.get("EXPORT_DIR", "exports"))
    schema_version = cfg.get("POLYGON_CHAIN_SCHEMA_VERSION")
    schema_str = str(schema_version) if schema_version else "polygon.v1"
    return PolygonFileAdapter(
        export_dir=export_dir,
        fetcher=fetcher,
        schema_version=schema_str,
    )


class _DisabledTwsAdapter:
    """Placeholder adapter used now that TWS exports are unsupported."""

    def acquire(self, symbol: str) -> ChainSourceDecision:  # pragma: no cover - guard
        raise ChainSourceError(
            "TWS option-chain export is verwijderd. Gebruik Polygon-paden."
        )


_DISABLED_TWS = _DisabledTwsAdapter()


def resolve_chain_decision(
    symbol: str,
    *,
    source: str,
    existing_dir: Path | str | None = None,
) -> ChainSourceDecision:
    choice = source.strip().lower()
    if choice not in {"polygon", "tws"}:
        raise ChainSourceError(f"Onbekende chain-bron: {source!r}")
    if choice == "tws":
        raise ChainSourceError(
            "TWS option-chain export is verwijderd. Gebruik Polygon-paden."
        )

    polygon = _polygon_adapter()
    resolved_dir: Path | None
    if existing_dir is None or isinstance(existing_dir, Path):
        resolved_dir = existing_dir if isinstance(existing_dir, Path) else None
    else:
        resolved_dir = Path(existing_dir)

    return resolve_chain_source(
        symbol,
        source=cast(ChainSourceName, choice),
        polygon=polygon,
        tws=_DISABLED_TWS,
        existing_dir=resolved_dir,
    )


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
    "resolve_chain_decision",
    "git_commit",
]
