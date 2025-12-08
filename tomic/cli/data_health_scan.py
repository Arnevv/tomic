"""CLI tool to inspect data coverage and spot simple gaps per symbol."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Sequence

try:  # pragma: no cover - optional dependency
    import holidays  # type: ignore
except Exception:  # pragma: no cover - fallback when package is missing

    class _NoHolidays:
        def __contains__(self, _date: date) -> bool:
            return False

    holidays = SimpleNamespace(US=lambda: _NoHolidays(), NYSE=lambda: _NoHolidays())  # type: ignore

from tomic.config import get as cfg_get
from tomic.infrastructure.storage import load_json
from tomic.cli.services.vol_helpers import MIN_IV_HISTORY_DAYS

from ._tabulate import tabulate


_US_MARKET_HOLIDAYS = None


def _us_market_holidays():
    """Return a holiday calendar for US equity markets."""
    global _US_MARKET_HOLIDAYS
    if _US_MARKET_HOLIDAYS is None:
        try:
            calendar_factory = getattr(holidays, "NYSE")
        except AttributeError:  # pragma: no cover - NYSE calendar missing
            calendar_factory = getattr(holidays, "US")
        _US_MARKET_HOLIDAYS = calendar_factory()
    return _US_MARKET_HOLIDAYS


def _is_trading_day(d: date) -> bool:
    """Return True if d is a US trading day (weekday and not a holiday)."""
    if d.weekday() >= 5:  # Weekend
        return False
    return d not in _us_market_holidays()


def _count_trading_days(start: date, end: date) -> int:
    """Count expected trading days between start and end (inclusive)."""
    if start > end:
        return 0
    count = 0
    current = start
    while current <= end:
        if _is_trading_day(current):
            count += 1
        current += timedelta(days=1)
    return count


@dataclass
class SeriesWindow:
    """Simple container describing the available date range for a dataset."""

    start: date | None
    end: date | None
    actual_count: int = 0

    @property
    def missing(self) -> bool:
        return self.start is None or self.end is None

    @property
    def expected_count(self) -> int:
        """Expected number of trading days between start and end."""
        if self.start is None or self.end is None:
            return 0
        return _count_trading_days(self.start, self.end)

    @property
    def gap_pct(self) -> float | None:
        """Percentage of missing trading days, or None if no data."""
        expected = self.expected_count
        if expected == 0:
            return None
        missing = expected - self.actual_count
        if missing <= 0:
            return 0.0
        return (missing / expected) * 100


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
        return SeriesWindow(None, None, 0)
    dates: list[date] = []
    for entry in records:  # type: ignore[assignment]
        if not isinstance(entry, dict):
            continue
        parsed = _parse_date(entry.get(date_key))
        if parsed:
            dates.append(parsed)
    if not dates:
        return SeriesWindow(None, None, 0)
    # Use unique dates to count actual data points
    unique_dates = set(dates)
    return SeriesWindow(min(dates), max(dates), len(unique_dates))


def _load_series(path: Path) -> list[dict]:
    data = load_json(path, default_factory=list)
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _count_iv_records_with_atm(records: list[dict]) -> int:
    """Count IV records that have a valid atm_iv value."""
    count = 0
    for entry in records:
        atm_iv = entry.get("atm_iv")
        if atm_iv is not None:
            try:
                if float(atm_iv) > 0:
                    count += 1
            except (TypeError, ValueError):
                continue
    return count


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
    gap = window.gap_pct
    gap_str = f" ({gap:.1f}%)" if gap is not None and gap > 0 else ""
    if window.start == window.end:
        return window.start.isoformat() + gap_str
    return f"{window.start.isoformat()} → {window.end.isoformat()}{gap_str}"


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


@dataclass
class DataGap:
    """Represents a gap in data coverage."""

    start: date  # Last date with data before gap
    end: date  # First date with data after gap
    trading_days_missing: int  # Number of trading days in the gap


def _detect_gaps(
    records: list[dict],
    *,
    date_key: str = "date",
    min_gap_trading_days: int = 5,
) -> list[DataGap]:
    """Detect significant gaps in a date series.

    Args:
        records: List of records with date field
        date_key: Key for date field in records
        min_gap_trading_days: Minimum gap size to report (default 5 trading days)

    Returns:
        List of DataGap objects for gaps >= min_gap_trading_days
    """
    dates: list[date] = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        parsed = _parse_date(entry.get(date_key))
        if parsed:
            dates.append(parsed)

    if len(dates) < 2:
        return []

    sorted_dates = sorted(set(dates))
    gaps: list[DataGap] = []

    for i in range(1, len(sorted_dates)):
        prev_date = sorted_dates[i - 1]
        curr_date = sorted_dates[i]

        # Count trading days between the two dates (exclusive of both endpoints)
        gap_start = prev_date + timedelta(days=1)
        gap_end = curr_date - timedelta(days=1)

        if gap_start > gap_end:
            continue  # Consecutive dates, no gap

        trading_days = _count_trading_days(gap_start, gap_end)

        if trading_days >= min_gap_trading_days:
            gaps.append(
                DataGap(
                    start=prev_date,
                    end=curr_date,
                    trading_days_missing=trading_days,
                )
            )

    return gaps


def _format_gap(gap: DataGap) -> str:
    """Format a gap for display."""
    return f"{gap.start} → {gap.end} ({gap.trading_days_missing} trading days)"


def _scan_symbol(
    symbol: str,
    *,
    spot_dir: Path,
    hv_dir: Path,
    iv_dir: Path,
    earnings_file: Path,
    limits: dict[str, int],
    min_gap_trading_days: int = 5,
) -> tuple[str, SeriesWindow, SeriesWindow, SeriesWindow, list[date], int, list[str], list[DataGap]]:
    spot_records = _load_series(spot_dir / f"{symbol}.json")
    spot_window = _series_window(spot_records)
    hv_window = _series_window(_load_series(hv_dir / f"{symbol}.json"))
    iv_records = _load_series(iv_dir / f"{symbol}.json")
    iv_window = _series_window(iv_records)
    iv_history_count = _count_iv_records_with_atm(iv_records)
    earnings_dates = _load_earnings(earnings_file, symbol)

    # Detect gaps in IV data (primary data source for backtesting)
    iv_gaps = _detect_gaps(iv_records, min_gap_trading_days=min_gap_trading_days)

    issues: list[str] = []
    if spot_window.missing:
        issues.append("missing_spot")
    if hv_window.missing:
        issues.append("missing_hv")
    if iv_window.missing:
        issues.append("missing_iv")
    if not earnings_dates:
        issues.append("missing_earnings")

    # Check if IV history is insufficient for reliable rank/percentile calculation
    if not iv_window.missing and iv_history_count < MIN_IV_HISTORY_DAYS:
        issues.append("iv_history_insufficient")

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

    # Add issue if significant gaps found
    if iv_gaps:
        total_gap_days = sum(g.trading_days_missing for g in iv_gaps)
        issues.append(f"iv_gaps({len(iv_gaps)}:{total_gap_days}d)")

    return symbol, spot_window, hv_window, iv_window, earnings_dates, iv_history_count, sorted(set(issues)), iv_gaps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scan datasets for missing or stale entries per symbol")
    parser.add_argument(
        "--symbols",
        help="Komma-gescheiden lijst met symbolen (fallback: DEFAULT_SYMBOLS uit config)",
    )
    parser.add_argument(
        "--min-gap-days",
        type=int,
        default=5,
        help="Minimum gap grootte in trading dagen om te rapporteren (default: 5)",
    )
    parser.add_argument(
        "--show-gaps",
        action="store_true",
        default=True,
        help="Toon gedetailleerde gap informatie (default: True)",
    )
    parser.add_argument(
        "--no-gaps",
        action="store_true",
        help="Verberg gedetailleerde gap informatie",
    )
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    else:
        from tomic.services.symbol_service import get_symbol_service
        symbol_service = get_symbol_service()
        # Use active symbols (excludes disqualified) when no specific symbols provided
        symbols = symbol_service.get_active_symbols()

    if not symbols:
        print("Geen symbolen opgegeven via --symbols of DEFAULT_SYMBOLS.")
        return

    spot_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")).expanduser()
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility")).expanduser()
    iv_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary")).expanduser()
    earnings_file = Path(cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")).expanduser()
    limits = _thresholds()

    rows = []
    all_gaps: dict[str, list[DataGap]] = {}

    for symbol in sorted({sym.upper() for sym in symbols}):
        sym, spot, hv, iv, earnings_dates, iv_count, issues, iv_gaps = _scan_symbol(
            symbol,
            spot_dir=spot_dir,
            hv_dir=hv_dir,
            iv_dir=iv_dir,
            earnings_file=earnings_file,
            limits=limits,
            min_gap_trading_days=args.min_gap_days,
        )
        # Store gaps for detailed output
        if iv_gaps:
            all_gaps[sym] = iv_gaps

        # Format IV count with indicator if insufficient
        iv_count_str = str(iv_count)
        if iv_count < MIN_IV_HISTORY_DAYS:
            iv_count_str = f"{iv_count} ⚠️"
        rows.append(
            [
                sym,
                _format_window(spot),
                _format_window(hv),
                _format_window(iv),
                iv_count_str,
                _format_earnings(earnings_dates),
                ", ".join(issues),
            ]
        )

    headers = ["Symbol", "Spot range", "HV range", "IV range", "IV#", "Earnings", "Issues"]
    print(tabulate(rows, headers=headers, tablefmt="github"))

    # Show detailed gap information if requested and gaps exist
    show_gaps = args.show_gaps and not args.no_gaps
    if show_gaps and all_gaps:
        print("\n")
        print("=" * 80)
        print("DATA GAPS DETECTED (IV data)")
        print("=" * 80)
        print(f"Minimum gap threshold: {args.min_gap_days} trading days\n")

        for sym, gaps in sorted(all_gaps.items()):
            total_days = sum(g.trading_days_missing for g in gaps)
            print(f"{sym}: {len(gaps)} gap(s), {total_days} trading days missing")
            for gap in gaps:
                print(f"  • {_format_gap(gap)}")
            print()

        print("-" * 80)
        print("Note: These gaps may affect IV percentile calculations around gap boundaries.")
        print("Consider backfilling data or documenting the impact on backtest results.")


if __name__ == "__main__":  # pragma: no cover - manual usage
    import sys

    main(sys.argv[1:])
