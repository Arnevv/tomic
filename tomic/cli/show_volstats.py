"""Display VolStats records from the volatility database."""

from __future__ import annotations

from typing import List

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate missing

    def tabulate(
        rows: List[List[str]],
        headers: List[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        if headers:
            table_rows = [headers] + rows
        else:
            table_rows = rows
        col_w = [max(len(str(c)) for c in col) for col in zip(*table_rows)]

        def fmt(row: List[str]) -> str:
            return "| " + " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(row)) + " |"

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append("|-" + "-|-".join("-" * col_w[i] for i in range(len(col_w))) + "-|")
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)

from tomic.analysis.metrics import historical_volatility
from tomic.analysis.vol_json import get_latest_summary

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


def _load_json_list(path: Path) -> list[dict]:
    data = load_json(path)
    return list(data) if isinstance(data, list) else []


def _latest_rec(records: list[dict]) -> dict:
    if not records:
        return {}
    records.sort(key=lambda r: r.get("date", ""))
    return records[-1]


def _load_latest_hv(symbol: str) -> dict:
    base = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
    return _latest_rec(_load_json_list(base / f"{symbol}.json"))


def _load_latest_snapshot(symbol: str) -> dict:
    path = Path(cfg_get("VOLATILITY_DATA_FILE", "tomic/data/volatility_data.json"))
    records = [r for r in _load_json_list(path) if r.get("symbol") == symbol]
    return _latest_rec(records)


def main(argv: List[str] | None = None) -> None:
    """Print recent volatility statistics."""
    setup_logging()
    limit = int(argv[0]) if argv else None

    symbols = [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    rows = []
    for sym in symbols:
        summary = get_latest_summary(sym)
        closes = _get_closes(sym)

        hv_record = _load_latest_hv(sym)
        snapshot = _load_latest_snapshot(sym)

        hv30 = hv_record.get("hv30")
        hv90 = hv_record.get("hv90")
        hv252 = hv_record.get("hv252")

        if hv30 is None:
            hv30 = historical_volatility(closes, window=30)
            hv30 = hv30 / 100 if hv30 is not None else None
        if hv90 is None:
            hv90 = historical_volatility(closes, window=90)
            hv90 = hv90 / 100 if hv90 is not None else None
        if hv252 is None:
            hv252 = historical_volatility(closes, window=252)
            hv252 = hv252 / 100 if hv252 is not None else None

        spot = snapshot.get("spot")
        if spot is None and closes:
            spot = closes[-1]

        def _to_decimal(val: float | None) -> float | None:
            if val is None:
                return None
            return val / 100 if val > 1 else val

        iv30 = None
        if summary is not None and getattr(summary, "atm_iv", None) is not None:
            iv30 = _to_decimal(summary.atm_iv)
        elif snapshot.get("iv30") is not None:
            iv30 = _to_decimal(snapshot["iv30"])

        iv_rank = None
        iv_pct = None
        if summary is not None:
            iv_rank = getattr(summary, "iv_rank", getattr(summary, "iv_rank (HV)", None))
            iv_pct = getattr(summary, "iv_percentile", getattr(summary, "iv_percentile (HV)", None))
        if iv_rank is None:
            iv_rank = snapshot.get("iv_rank")

        skew = snapshot.get("skew")

        rows.append([
            sym,
            spot,
            iv30,
            hv30,
            hv90,
            hv252,
            iv_rank,
            iv_pct,
            None,
            None,
            skew,
            None,
            None,
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
