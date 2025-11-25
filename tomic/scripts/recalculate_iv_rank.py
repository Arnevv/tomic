#!/usr/bin/env python3
"""Recalculate IV rank and percentile using historical IV instead of HV.

This script:
1. Iterates through all iv_daily_summary files
2. Recalculates iv_rank and iv_percentile based on historical IV series
3. Updates field names from (HV) to (IV)
4. Saves the updated data

Usage:
    python -m tomic.scripts.recalculate_iv_rank [--dry-run] [--symbols SYMBOL1,SYMBOL2,...]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from tomic.config import get as cfg_get
from tomic.cli.services.vol_helpers import (
    iv_rank,
    iv_percentile,
    MIN_IV_HISTORY_DAYS,
)
from tomic.logutils import logger, setup_logging


def load_iv_summary(path: Path) -> list[dict[str, Any]]:
    """Load IV summary data from JSON file."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        logger.warning(f"Failed to load {path}: {exc}")
        return []


def save_iv_summary(path: Path, data: list[dict[str, Any]]) -> None:
    """Save IV summary data to JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_historical_iv_values(records: list[dict[str, Any]], exclude_date: str | None = None) -> list[float]:
    """Extract ATM IV values from records, optionally excluding a specific date."""
    iv_values: list[float] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if exclude_date and rec.get("date") == exclude_date:
            continue
        atm_iv = rec.get("atm_iv")
        if atm_iv is None:
            continue
        try:
            iv_float = float(atm_iv)
            if iv_float < 1:  # Stored as decimal, convert to percentage
                iv_float *= 100
            iv_values.append(iv_float)
        except (TypeError, ValueError):
            continue
    return iv_values


def recalculate_record(
    record: dict[str, Any],
    all_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recalculate IV rank and percentile for a single record."""
    result = dict(record)
    date_str = record.get("date")
    atm_iv = record.get("atm_iv")

    # Remove old HV-based fields
    result.pop("iv_rank (HV)", None)
    result.pop("iv_percentile (HV)", None)

    # Calculate new IV-based values
    iv_rank_value = None
    iv_percentile_value = None

    if atm_iv is not None:
        # Get historical IV values excluding the current date
        iv_series = get_historical_iv_values(all_records, exclude_date=date_str)
        if iv_series:
            # Scale IV to percentage for comparison
            try:
                scaled_iv = float(atm_iv) * 100 if float(atm_iv) < 1 else float(atm_iv)
                iv_rank_value = iv_rank(scaled_iv, iv_series)
                iv_percentile_value = iv_percentile(scaled_iv, iv_series)

                # Convert to 0-100 scale
                if isinstance(iv_rank_value, (int, float)):
                    iv_rank_value *= 100
                if isinstance(iv_percentile_value, (int, float)):
                    iv_percentile_value *= 100
            except (TypeError, ValueError):
                pass

    result["iv_rank (IV)"] = iv_rank_value
    result["iv_percentile (IV)"] = iv_percentile_value

    return result


def process_symbol(
    symbol: str,
    iv_dir: Path,
    *,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Process a single symbol's IV summary file.

    Returns:
        (total_records, updated_records, skipped_records)
    """
    summary_file = iv_dir / f"{symbol}.json"
    if not summary_file.exists():
        logger.warning(f"No IV summary file for {symbol}")
        return 0, 0, 0

    records = load_iv_summary(summary_file)
    if not records:
        logger.warning(f"No records in IV summary for {symbol}")
        return 0, 0, 0

    # Sort records by date to ensure chronological order
    records.sort(key=lambda r: r.get("date", ""))

    total = len(records)
    updated = 0
    skipped = 0

    # Process each record
    new_records = []
    for record in records:
        new_record = recalculate_record(record, records)
        new_records.append(new_record)

        # Check if anything changed
        old_rank = record.get("iv_rank (HV)")
        new_rank = new_record.get("iv_rank (IV)")
        if old_rank != new_rank:
            updated += 1
        elif new_rank is None:
            skipped += 1

    if not dry_run:
        # Backup original file
        backup_file = summary_file.with_suffix(".json.bak")
        shutil.copy2(summary_file, backup_file)

        # Save updated records
        save_iv_summary(summary_file, new_records)
        logger.info(f"Updated {symbol}: {updated}/{total} records changed, {skipped} skipped (insufficient history)")
    else:
        logger.info(f"[DRY-RUN] {symbol}: {updated}/{total} records would change, {skipped} would be skipped")

    return total, updated, skipped


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Recalculate IV rank and percentile using historical IV"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated list of symbols to process (default: all)",
    )
    args = parser.parse_args(argv)

    iv_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    if not iv_dir.exists():
        logger.error(f"IV summary directory not found: {iv_dir}")
        return

    # Get list of symbols to process
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        # Process all symbols
        symbols = sorted([f.stem for f in iv_dir.glob("*.json") if not f.name.endswith(".bak")])

    if not symbols:
        logger.warning("No symbols to process")
        return

    logger.info(f"Processing {len(symbols)} symbols...")
    if args.dry_run:
        logger.info("DRY-RUN mode: no files will be modified")

    total_total = 0
    total_updated = 0
    total_skipped = 0

    for symbol in symbols:
        t, u, s = process_symbol(symbol, iv_dir, dry_run=args.dry_run)
        total_total += t
        total_updated += u
        total_skipped += s

    logger.info(f"\nSummary:")
    logger.info(f"  Total records: {total_total}")
    logger.info(f"  Updated: {total_updated}")
    logger.info(f"  Skipped (insufficient IV history): {total_skipped}")
    logger.info(f"  Minimum IV history required: {MIN_IV_HISTORY_DAYS} days")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
