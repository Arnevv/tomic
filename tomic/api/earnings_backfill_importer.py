"""Import historical earnings data from MarketChameleon per-symbol CSV exports.

This module processes CSV files from the MC_earningBackfill folder, where each
file contains historical earnings data for a single symbol (filename = symbol).

The importer creates two outputs:
1. earnings_enriched.json - Full metadata including price effects, implied moves, etc.
2. Updates earnings_dates.json - Backward compatible list of reaction dates

Key feature: reaction_date calculation
- Before market earnings: reaction_date = same day (market opens, investors react)
- After market earnings: reaction_date = next day (investors react next trading day)
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from tomic.logutils import logger


def _parse_date(raw: str) -> date | None:
    """Parse date from MM/DD/YYYY format."""
    raw = raw.strip()
    if not raw:
        return None

    # Handle date ranges like "10/29/2026 - 11/3/2026" (projected)
    if " - " in raw:
        # Take the first date of the range
        raw = raw.split(" - ")[0].strip()

    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_earnings_time(raw: str) -> str:
    """Normalize earnings time to before_market/after_market/unknown."""
    raw = raw.strip().lower()
    if "before" in raw or "bmo" in raw:
        return "before_market"
    if "after" in raw or "amc" in raw:
        return "after_market"
    return "unknown"


def _calculate_reaction_date(earnings_date: date, earnings_time: str) -> date:
    """Calculate the date when investors can first react.

    - Before market: same day (market opens after announcement)
    - After market/unknown: next day (investors react next trading day)

    Note: This doesn't account for weekends/holidays. For simplicity,
    we just add 1 day for after-market. In practice, the next trading
    day logic would need a calendar, but the date stored is still useful.
    """
    if earnings_time == "before_market":
        return earnings_date
    # After market or unknown: next day
    return earnings_date + timedelta(days=1)


def _parse_float(raw: str) -> float | None:
    """Parse float, returning None for empty/invalid values."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_csv_row(row: dict[str, str], symbol: str) -> dict[str, Any] | None:
    """Parse a single CSV row into an enriched earnings record."""
    earnings_date_raw = row.get("Earnings Date", "").strip()
    earnings_date = _parse_date(earnings_date_raw)

    if earnings_date is None:
        return None

    # Skip projected dates (they have ranges and no actual data)
    status = row.get("Status", "").strip().lower()
    if status == "projected":
        return None

    earnings_time = _parse_earnings_time(row.get("Earnings Time", ""))
    reaction_date = _calculate_reaction_date(earnings_date, earnings_time)

    record: dict[str, Any] = {
        "date": earnings_date.isoformat(),
        "reaction_date": reaction_date.isoformat(),
        "time": earnings_time,
    }

    # Optional fields
    period = row.get("Period", "").strip()
    if period:
        record["period"] = period

    special_case = row.get("Special Case", "").strip()
    if special_case:
        record["special_case"] = special_case

    # Numeric fields (store as floats, None if missing)
    numeric_fields = {
        "price_effect": "Price Effect",
        "implied_straddle_pct": "Implied Straddle Pct",
        "opening_gap": "Opening Gap",
        "price_change_1w_prior": "Price Change 1-Week Prior",
        "price_change_1w_after": "Price Change 1-Week After",
    }

    for key, csv_col in numeric_fields.items():
        value = _parse_float(row.get(csv_col, ""))
        if value is not None:
            record[key] = value

    return record


def parse_symbol_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Parse a per-symbol CSV file and return list of enriched earnings records."""
    symbol = csv_path.stem.upper()

    records: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = _parse_csv_row(row, symbol)
            if record:
                records.append(record)

    # Sort by date ascending
    records.sort(key=lambda r: r["date"])

    return records


def load_enriched_json(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Load existing enriched earnings data."""
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, IOError) as exc:
        logger.warning(f"Could not load enriched JSON: {exc}")

    return {}


def save_enriched_json(data: dict[str, list[dict[str, Any]]], path: Path) -> None:
    """Save enriched earnings data."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Sort symbols alphabetically
    sorted_data = {k: data[k] for k in sorted(data.keys())}

    with path.open("w", encoding="utf-8") as handle:
        json.dump(sorted_data, handle, indent=2)

    logger.success(f"Enriched earnings saved: {path}")


def load_dates_json(path: Path) -> dict[str, list[str]]:
    """Load existing earnings_dates.json."""
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except (json.JSONDecodeError, IOError) as exc:
        logger.warning(f"Could not load dates JSON: {exc}")

    return {}


def save_dates_json(data: dict[str, list[str]], path: Path) -> None:
    """Save earnings_dates.json."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # Sort symbols alphabetically
    sorted_data = {k: data[k] for k in sorted(data.keys())}

    with path.open("w", encoding="utf-8") as handle:
        json.dump(sorted_data, handle, indent=2)

    logger.success(f"Earnings dates saved: {path}")


def merge_enriched_records(
    existing: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge new records into existing, avoiding duplicates by date."""
    existing_dates = {r["date"] for r in existing}

    merged = list(existing)
    for record in new_records:
        if record["date"] not in existing_dates:
            merged.append(record)
            existing_dates.add(record["date"])

    # Sort by date
    merged.sort(key=lambda r: r["date"])
    return merged


def merge_date_lists(existing: list[str], new_dates: list[str]) -> list[str]:
    """Merge new dates into existing list, maintaining sorted order."""
    all_dates = set(existing) | set(new_dates)
    return sorted(all_dates)


def import_backfill_folder(
    backfill_folder: Path,
    enriched_json_path: Path,
    dates_json_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import all CSV files from the backfill folder.

    Returns statistics about the import.
    """
    csv_files = list(backfill_folder.glob("*.csv"))

    if not csv_files:
        logger.warning(f"No CSV files found in {backfill_folder}")
        return {"symbols_processed": 0, "records_added": 0}

    # Load existing data
    enriched_data = load_enriched_json(enriched_json_path)
    dates_data = load_dates_json(dates_json_path)

    stats = {
        "symbols_processed": 0,
        "records_added": 0,
        "symbols_new": 0,
        "symbols_updated": 0,
    }

    for csv_path in sorted(csv_files):
        symbol = csv_path.stem.upper()

        try:
            new_records = parse_symbol_csv(csv_path)
        except Exception as exc:
            logger.error(f"Failed to parse {csv_path}: {exc}")
            continue

        if not new_records:
            logger.info(f"No valid records in {csv_path}")
            continue

        stats["symbols_processed"] += 1

        # Track if this is a new symbol
        is_new = symbol not in enriched_data
        if is_new:
            stats["symbols_new"] += 1
        else:
            stats["symbols_updated"] += 1

        # Merge enriched data
        existing_enriched = enriched_data.get(symbol, [])
        merged_enriched = merge_enriched_records(existing_enriched, new_records)
        records_added = len(merged_enriched) - len(existing_enriched)
        stats["records_added"] += records_added
        enriched_data[symbol] = merged_enriched

        # Extract reaction dates for dates_json
        new_reaction_dates = [r["reaction_date"] for r in new_records]
        existing_dates = dates_data.get(symbol, [])
        merged_dates = merge_date_lists(existing_dates, new_reaction_dates)
        dates_data[symbol] = merged_dates

        logger.info(
            f"{symbol}: {len(new_records)} records parsed, "
            f"{records_added} new records added"
        )

    if not dry_run:
        save_enriched_json(enriched_data, enriched_json_path)
        save_dates_json(dates_data, dates_json_path)
    else:
        logger.info("Dry run - no files saved")

    return stats


def run_backfill_import(
    backfill_folder: str | Path | None = None,
    enriched_json_path: str | Path | None = None,
    dates_json_path: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main entry point for backfill import.

    Uses default paths if not specified:
    - backfill_folder: tomic/data/MC_earningBackfill/
    - enriched_json_path: tomic/data/earnings_enriched.json
    - dates_json_path: tomic/data/earnings_dates.json
    """
    # Determine base path
    base_path = Path(__file__).parent.parent / "data"

    if backfill_folder is None:
        backfill_folder = base_path / "MC_earningBackfill"
    else:
        backfill_folder = Path(backfill_folder)

    if enriched_json_path is None:
        enriched_json_path = base_path / "earnings_enriched.json"
    else:
        enriched_json_path = Path(enriched_json_path)

    if dates_json_path is None:
        dates_json_path = base_path / "earnings_dates.json"
    else:
        dates_json_path = Path(dates_json_path)

    logger.info(f"Backfill folder: {backfill_folder}")
    logger.info(f"Enriched JSON: {enriched_json_path}")
    logger.info(f"Dates JSON: {dates_json_path}")

    return import_backfill_folder(
        backfill_folder,
        enriched_json_path,
        dates_json_path,
        dry_run=dry_run,
    )


__all__ = [
    "parse_symbol_csv",
    "import_backfill_folder",
    "run_backfill_import",
]
