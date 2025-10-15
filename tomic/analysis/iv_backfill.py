from __future__ import annotations

"""Helpers for parsing IV backfill CSV files and generating diff reports."""

from dataclasses import dataclass, field
from datetime import datetime
import csv
from pathlib import Path
from typing import Iterable, List, Sequence

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json


REQUIRED_COLUMNS: Sequence[str] = (
    "Date",
    "IV30",
    "IV30 20-Day MA",
    "OHLC 20-Day Vol",
    "OHLC 52-Week Vol",
    "Options Volume",
)


DEFAULT_SUMMARY_DIR = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
DEFAULT_HV_DIR = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
DEFAULT_SPOT_DIR = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))


class IVBackfillValidationError(ValueError):
    """Raised when the CSV structure does not meet expectations."""


@dataclass(frozen=True)
class IVBackfillRow:
    """Normalized record from the backfill CSV."""

    date: str
    atm_iv: float
    source_iv30: float


@dataclass(frozen=True)
class IVBackfillUpdate:
    """Represents an update for an existing IV record."""

    date: str
    old_atm_iv: float | None
    new_atm_iv: float
    abs_diff: float
    pct_diff: float | None


@dataclass
class SupportDataStatus:
    """Holds information about missing HV/spot support data."""

    missing_spot_dates: List[str] = field(default_factory=list)
    missing_hv_dates: List[str] = field(default_factory=list)


@dataclass
class IVBackfillParseResult:
    """Result of parsing the backfill CSV."""

    rows: List[IVBackfillRow]
    duplicate_dates: List[str]
    row_errors: List[str]

    def has_errors(self) -> bool:
        return bool(self.row_errors)


@dataclass
class IVBackfillReport:
    """Aggregated diff information used for CLI preview and reporting."""

    symbol: str
    rows: List[IVBackfillRow]
    new_rows: List[IVBackfillRow]
    updated_rows: List[IVBackfillUpdate]
    unchanged_dates: List[str]
    existing_only_dates: List[str]
    duplicates: List[str]
    parse_errors: List[str]
    support_status: SupportDataStatus
    date_range: tuple[str | None, str | None]
    threshold: float

    def has_warnings(self) -> bool:
        return bool(
            self.duplicates
            or self.parse_errors
            or self.support_status.missing_spot_dates
            or self.support_status.missing_hv_dates
        )


def parse_iv_backfill_csv(path: Path | str) -> IVBackfillParseResult:
    """Parse ``path`` and normalize IV data ready for diffing."""

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames or reader.fieldnames is None]
        if missing:
            raise IVBackfillValidationError(
                f"CSV file {csv_path} is missing required columns: {', '.join(missing)}"
            )

        rows: list[IVBackfillRow] = []
        duplicates: list[str] = []
        row_errors: list[str] = []
        seen_dates: set[str] = set()

        for line_no, raw in enumerate(reader, start=2):
            if not any(raw.values()):
                # Completely empty row – skip silently.
                continue

            date_raw = (raw.get("Date") or "").strip()
            if not date_raw:
                row_errors.append(f"Row {line_no}: missing Date")
                continue

            try:
                norm_date = _normalize_date(date_raw)
            except ValueError:
                row_errors.append(f"Row {line_no}: invalid Date '{date_raw}'")
                continue

            iv_raw = raw.get("IV30")
            if iv_raw is None or str(iv_raw).strip() == "":
                row_errors.append(f"Row {line_no}: missing IV30 value for {norm_date}")
                continue

            try:
                iv_value = _parse_iv30(iv_raw)
            except ValueError:
                row_errors.append(
                    f"Row {line_no}: could not parse IV30 value '{iv_raw}' for {norm_date}"
                )
                continue

            if norm_date in seen_dates:
                duplicates.append(norm_date)
                # Skip duplicate rows but retain the first occurrence.
                continue

            seen_dates.add(norm_date)
            rows.append(
                IVBackfillRow(
                    date=norm_date,
                    atm_iv=iv_value,
                    source_iv30=float(iv_value * 100.0),
                )
            )

    rows.sort(key=lambda row: row.date)
    duplicates = sorted(set(duplicates))
    return IVBackfillParseResult(rows=rows, duplicate_dates=duplicates, row_errors=row_errors)


def build_iv_backfill_report(
    symbol: str,
    parse_result: IVBackfillParseResult,
    *,
    summary_dir: Path | None = None,
    hv_dir: Path | None = None,
    spot_dir: Path | None = None,
    diff_threshold: float = 0.03,
) -> IVBackfillReport:
    """Generate a diff report comparing CSV rows with existing JSON data."""

    if summary_dir is None:
        summary_dir = DEFAULT_SUMMARY_DIR
    if hv_dir is None:
        hv_dir = DEFAULT_HV_DIR
    if spot_dir is None:
        spot_dir = DEFAULT_SPOT_DIR

    rows = list(parse_result.rows)
    existing_records = _load_json_list(summary_dir / f"{symbol}.json")
    existing_by_date = {
        str(rec.get("date")): rec for rec in existing_records if rec.get("date")
    }

    new_rows: list[IVBackfillRow] = []
    updated_rows: list[IVBackfillUpdate] = []
    unchanged_dates: list[str] = []

    for row in rows:
        current = existing_by_date.get(row.date)
        if current is None:
            new_rows.append(row)
            continue

        old_value = _coerce_float(current.get("atm_iv"))
        if old_value is None:
            updated_rows.append(
                IVBackfillUpdate(
                    date=row.date,
                    old_atm_iv=None,
                    new_atm_iv=row.atm_iv,
                    abs_diff=row.atm_iv,
                    pct_diff=None,
                )
            )
            continue

        diff = abs(row.atm_iv - old_value)
        if diff > diff_threshold:
            pct_diff = diff / old_value if old_value else None
            updated_rows.append(
                IVBackfillUpdate(
                    date=row.date,
                    old_atm_iv=old_value,
                    new_atm_iv=row.atm_iv,
                    abs_diff=diff,
                    pct_diff=pct_diff,
                )
            )
        else:
            unchanged_dates.append(row.date)

    csv_dates = {row.date for row in rows}
    existing_dates = {date for date in existing_by_date}
    existing_only_dates = sorted(date for date in existing_dates if date not in csv_dates)

    support_dates = sorted({row.date for row in new_rows} | {upd.date for upd in updated_rows})
    missing_spot = _find_missing_support_dates(spot_dir / f"{symbol}.json", support_dates)
    missing_hv = _find_missing_support_dates(hv_dir / f"{symbol}.json", support_dates)
    support_status = SupportDataStatus(
        missing_spot_dates=missing_spot,
        missing_hv_dates=missing_hv,
    )

    date_range = _compute_date_range(rows)

    return IVBackfillReport(
        symbol=symbol,
        rows=rows,
        new_rows=sorted(new_rows, key=lambda r: r.date),
        updated_rows=sorted(updated_rows, key=lambda r: r.date),
        unchanged_dates=sorted(unchanged_dates),
        existing_only_dates=existing_only_dates,
        duplicates=list(parse_result.duplicate_dates),
        parse_errors=list(parse_result.row_errors),
        support_status=support_status,
        date_range=date_range,
        threshold=diff_threshold,
    )


def _normalize_date(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(value)


def _parse_iv30(value: str | float | int) -> float:
    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1]
    if not text:
        raise ValueError(value)
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(value) from exc
    return number / 100.0


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_date_range(rows: Sequence[IVBackfillRow]) -> tuple[str | None, str | None]:
    if not rows:
        return (None, None)
    return (rows[0].date, rows[-1].date)


def _load_json_list(path: Path) -> list[dict]:
    data = load_json(path)
    if not isinstance(data, list):
        return []
    return [rec for rec in data if isinstance(rec, dict)]


def _find_missing_support_dates(path: Path, target_dates: Iterable[str]) -> List[str]:
    if not target_dates:
        return []
    available = {
        str(entry.get("date"))
        for entry in _load_json_list(path)
        if entry.get("date")
    }
    return sorted({date for date in target_dates if date not in available})


__all__ = [
    "IVBackfillRow",
    "IVBackfillUpdate",
    "IVBackfillParseResult",
    "IVBackfillReport",
    "SupportDataStatus",
    "IVBackfillValidationError",
    "parse_iv_backfill_csv",
    "build_iv_backfill_report",
]
