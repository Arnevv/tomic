#!/usr/bin/env python3
"""Standalone script to import MarketChameleon earnings backfill data.

Usage:
    python scripts/run_earnings_backfill.py [--dry-run]

Place your per-symbol CSV files (e.g., AAPL.csv, MSFT.csv) in:
    tomic/data/MC_earningBackfill/

The script will:
1. Parse all CSV files (symbol derived from filename)
2. Create/update earnings_enriched.json with full metadata
3. Update earnings_dates.json with reaction dates (backward compatible)

Reaction date logic:
- Before market: same day (investors react at market open)
- After market: next day (investors react next trading day)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def _parse_date(raw: str) -> date | None:
    """Parse date from MM/DD/YYYY format."""
    raw = raw.strip()
    if not raw:
        return None

    # Handle date ranges like "10/29/2026 - 11/3/2026" (projected)
    if " - " in raw:
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
    """Calculate the date when investors can first react."""
    if earnings_time == "before_market":
        return earnings_date
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


def _parse_csv_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Parse a single CSV row into an enriched earnings record."""
    earnings_date_raw = row.get("Earnings Date", "").strip()
    earnings_date = _parse_date(earnings_date_raw)

    if earnings_date is None:
        return None

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

    period = row.get("Period", "").strip()
    if period:
        record["period"] = period

    special_case = row.get("Special Case", "").strip()
    if special_case:
        record["special_case"] = special_case

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
    """Parse a per-symbol CSV file."""
    records: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = _parse_csv_row(row)
            if record:
                records.append(record)

    records.sort(key=lambda r: r["date"])
    return records


def load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}


def save_json(data: dict, path: Path) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_data = {k: data[k] for k in sorted(data.keys())}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(sorted_data, handle, indent=2)


def merge_enriched_records(
    existing: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge new records into existing."""
    existing_dates = {r["date"] for r in existing}
    merged = list(existing)
    for record in new_records:
        if record["date"] not in existing_dates:
            merged.append(record)
            existing_dates.add(record["date"])
    merged.sort(key=lambda r: r["date"])
    return merged


def merge_date_lists(existing: list[str], new_dates: list[str]) -> list[str]:
    """Merge new dates into existing list."""
    all_dates = set(existing) | set(new_dates)
    return sorted(all_dates)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import MarketChameleon earnings backfill CSVs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without saving",
    )
    args = parser.parse_args()

    # Paths
    base_path = Path(__file__).parent.parent / "tomic" / "data"
    backfill_folder = base_path / "MC_earningBackfill"
    enriched_json_path = base_path / "earnings_enriched.json"
    dates_json_path = base_path / "earnings_dates.json"

    print(f"Backfill folder: {backfill_folder}")
    print(f"Enriched JSON:   {enriched_json_path}")
    print(f"Dates JSON:      {dates_json_path}")
    print()

    csv_files = list(backfill_folder.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {backfill_folder}")
        return 1

    print(f"Found {len(csv_files)} CSV file(s)")
    print()

    # Load existing data
    enriched_data = load_json(enriched_json_path)
    dates_data = load_json(dates_json_path)

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
            print(f"ERROR: Failed to parse {csv_path}: {exc}")
            continue

        if not new_records:
            print(f"{symbol}: No valid records")
            continue

        stats["symbols_processed"] += 1

        is_new = symbol not in enriched_data
        if is_new:
            stats["symbols_new"] += 1
        else:
            stats["symbols_updated"] += 1

        existing_enriched = enriched_data.get(symbol, [])
        merged_enriched = merge_enriched_records(existing_enriched, new_records)
        records_added = len(merged_enriched) - len(existing_enriched)
        stats["records_added"] += records_added
        enriched_data[symbol] = merged_enriched

        new_reaction_dates = [r["reaction_date"] for r in new_records]
        existing_dates = dates_data.get(symbol, [])
        merged_dates = merge_date_lists(existing_dates, new_reaction_dates)
        dates_data[symbol] = merged_dates

        print(f"{symbol}: {len(new_records)} records parsed, {records_added} new")

    print()
    print("=" * 50)
    print("IMPORT SUMMARY")
    print("=" * 50)
    print(f"Symbols processed: {stats['symbols_processed']}")
    print(f"  - New symbols:   {stats['symbols_new']}")
    print(f"  - Updated:       {stats['symbols_updated']}")
    print(f"Records added:     {stats['records_added']}")

    if args.dry_run:
        print("\n[DRY RUN - no files were saved]")
    else:
        save_json(enriched_data, enriched_json_path)
        save_json(dates_data, dates_json_path)
        print(f"\nSaved: {enriched_json_path}")
        print(f"Saved: {dates_json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
