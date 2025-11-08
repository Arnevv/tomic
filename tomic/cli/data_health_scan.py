"""CLI tool to inspect data coverage and spot simple gaps per symbol."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from tomic.config import get as cfg_get
from tomic.infrastructure.storage import load_json

from ._tabulate import tabulate


@dataclass
class SeriesWindow:
    """Simple container describing the available date range for a dataset."""

    start: date | None
    end: date | None

    @property
    def missing(self) -> bool:
        return self.start is None or self.end is None


DEFAULT_THRESHOLDS = {
    "spot_max_age_days": 3,
    "hv_max_age_days": 7,
    "iv_max_age_days": 7,
    "earnings_max_age_days": 120,
}


def _parse_date(value: object) -> date | None:
    if isinstance(value, str):
        try:
            # Some datasets include timestamps – slice to ``YYYY-MM-DD``.
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _series_window(records: object, *, date_key: str = "date") -> SeriesWindow:
    if not isinstance(records, Iterable):  # pragma: no cover - defensive guard
        return SeriesWindow(None, None)
    dates: list[date] = []
    for entry in records:  # type: ignore[assignment]
        if not isinstance(entry, dict):
            continue
        parsed = _parse_date(entry.get(date_key))
        if parsed:
            dates.append(parsed)
    if not dates:
        return SeriesWindow(None, None)
    return SeriesWindow(min(dates), max(dates))


def _load_series(path: Path) -> list[dict]:
    data = load_json(path, default_factory=list)
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _load_earnings(path: Path, symbol: str) -> list[date]:
    raw = load_json(path, default_factory=dict)
    if not isinstance(raw, dict):
        return []
    entries = raw.get(symbol, [])
    if not isinstance(entries, Sequence):
        return []
    parsed: list[date] = []
    for value in entries:
        parsed_date = _parse_date(value)
        if parsed_date:
            parsed.append(parsed_date)
    return sorted(parsed)


def _format_window(window: SeriesWindow) -> str:
    if window.missing:
        return "-"
    if window.start == window.end:
        return window.start.isoformat()
    return f"{window.start.isoformat()} → {window.end.isoformat()}"


def _format_earnings(dates: Sequence[date]) -> str:
    if not dates:
        return "-"
    upcoming = [d for d in dates if d >= date.today()]
    if upcoming:
        return f"next {upcoming[0].isoformat()} ({len(dates)} total)"
    return f"latest {dates[-1].isoformat()} ({len(dates)} total)"


def _thresholds() -> dict[str, int]:
    cfg_val = cfg_get("DATA_HEALTH_THRESHOLDS", {}) or {}
    merged = DEFAULT_THRESHOLDS.copy()
    if isinstance(cfg_val, dict):
        for key, value in cfg_val.items():
            if isinstance(value, (int, float)):
                merged[key] = int(value)
    return merged


def _check_stale(window: SeriesWindow, *, key: str, today: date, limits: dict[str, int]) -> bool:
    if window.missing:
        return False
    threshold = limits.get(key)
    if not threshold or threshold <= 0:
        return False
    if window.end and (today - window.end).days > threshold:
        return True
    return False


def _scan_symbol(
    symbol: str,
    *,
    spot_dir: Path,
    hv_dir: Path,
    iv_dir: Path,
    earnings_file: Path,
    limits: dict[str, int],
) -> tuple[str, SeriesWindow, SeriesWindow, SeriesWindow, list[date], list[str]]:
    spot_window = _series_window(_load_series(spot_dir / f"{symbol}.json"))
    hv_window = _series_window(_load_series(hv_dir / f"{symbol}.json"))
    iv_window = _series_window(_load_series(iv_dir / f"{symbol}.json"))
    earnings_dates = _load_earnings(earnings_file, symbol)

    issues: list[str] = []
    if spot_window.missing:
        issues.append("missing_spot")
    if hv_window.missing:
        issues.append("missing_hv")
    if iv_window.missing:
        issues.append("missing_iv")
    if not earnings_dates:
        issues.append("missing_earnings")

    today = date.today()
    if _check_stale(spot_window, key="spot_max_age_days", today=today, limits=limits):
        issues.append("spot_stale")
    if _check_stale(hv_window, key="hv_max_age_days", today=today, limits=limits):
        issues.append("hv_stale")
    if _check_stale(iv_window, key="iv_max_age_days", today=today, limits=limits):
        issues.append("iv_stale")

    if earnings_dates:
        threshold = limits.get("earnings_max_age_days", 0)
        latest_known = max((d for d in earnings_dates if d <= today), default=earnings_dates[-1])
        if threshold and (today - latest_known).days > threshold:
            issues.append("earnings_stale")
        if not any(d >= today for d in earnings_dates):
            issues.append("earnings_missing_future")

    if not spot_window.missing and not hv_window.missing:
        if hv_window.start and spot_window.start and hv_window.start < spot_window.start:
            issues.append("hv_before_spot")
        if hv_window.end and spot_window.end and hv_window.end > spot_window.end:
            issues.append("hv_after_spot")

    if not spot_window.missing and not iv_window.missing:
        if iv_window.start and spot_window.start and iv_window.start < spot_window.start:
            issues.append("iv_before_spot")
        if iv_window.end and spot_window.end and iv_window.end > spot_window.end:
            issues.append("iv_after_spot")

    return symbol, spot_window, hv_window, iv_window, earnings_dates, sorted(set(issues))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scan datasets for missing or stale entries per symbol")
    parser.add_argument(
        "--symbols",
        help="Komma-gescheiden lijst met symbolen (fallback: DEFAULT_SYMBOLS uit config)",
    )
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    else:
        symbols = [sym.upper() for sym in cfg_get("DEFAULT_SYMBOLS", []) or []]

    if not symbols:
        print("Geen symbolen opgegeven via --symbols of DEFAULT_SYMBOLS.")
        return

    spot_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")).expanduser()
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility")).expanduser()
    iv_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary")).expanduser()
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")).expanduser()
    limits = _thresholds()

    rows = []
    for symbol in sorted({sym.upper() for sym in symbols}):
        sym, spot, hv, iv, earnings_dates, issues = _scan_symbol(
            symbol,
            spot_dir=spot_dir,
            hv_dir=hv_dir,
            iv_dir=iv_dir,
            earnings_file=earnings_file,
            limits=limits,
        )
        rows.append(
            [
                sym,
                _format_window(spot),
                _format_window(hv),
                _format_window(iv),
                _format_earnings(earnings_dates),
                ", ".join(issues),
            ]
        )

    headers = ["Symbol", "Spot range", "HV range", "IV range", "Earnings", "Issues"]
    print(tabulate(rows, headers=headers, tablefmt="github"))


if __name__ == "__main__":  # pragma: no cover - manual usage
    import sys

    main(sys.argv[1:])
