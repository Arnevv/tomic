"""Display VolStats records from the volatility database."""

from __future__ import annotations

from typing import List

from tabulate import tabulate

from tomic.analysis.metrics import historical_volatility
from tomic.api.market_client import fetch_market_metrics

from tomic.logutils import setup_logging
from tomic.config import get as cfg_get
from pathlib import Path
from tomic.journal.utils import load_json


def _get_closes(symbol: str) -> list[float]:
    """Return list of closing prices for ``symbol``."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if not isinstance(data, list):
        return []
    data.sort(key=lambda r: r.get("date", ""))
    return [float(rec.get("close", 0)) for rec in data]


def main(argv: List[str] | None = None) -> None:
    """Print recent volatility statistics."""
    setup_logging()
    limit = int(argv[0]) if argv else None

    symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    rows = []
    for sym in symbols:
        metrics = {}
        try:
            metrics = fetch_market_metrics(sym, timeout=10) or {}
        except Exception:  # pragma: no cover - network errors
            metrics = {}

        closes = _get_closes(sym)
        hv30 = historical_volatility(closes, window=30)
        hv90 = historical_volatility(closes, window=90)
        hv252 = historical_volatility(closes, window=252)

        def _scale(val: float | None) -> float | None:
            return val / 100 if val is not None else None

        rows.append([
            sym,
            metrics.get("spot_price"),
            metrics.get("implied_volatility"),
            _scale(hv30),
            _scale(hv90),
            _scale(hv252),
            metrics.get("iv_rank"),
            metrics.get("iv_percentile"),
            metrics.get("atr14"),
            metrics.get("vix"),
            metrics.get("skew"),
            metrics.get("term_m1_m2"),
            metrics.get("term_m1_m3"),
        ])

    if not rows:
        print("⚠️ Geen volatiliteitsdata gevonden")
        return

    rows.sort(key=lambda r: r[0])
    if limit is not None:
        rows = rows[:limit]
    headers = [
        "Symbol",
        "SpotPrice",
        "Implied_Volatility",
        "HV_30",
        "HV_90",
        "HV_252",
        "IV_Rank",
        "IV_Percentile",
        "ATR_14",
        "VIX",
        "Skew",
        "Term_M1_M2",
        "Term_M1_M3",
    ]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
