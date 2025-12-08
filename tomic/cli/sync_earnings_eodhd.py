"""CLI for syncing earnings data from EODHD API.

Usage:
    # Sync all configured symbols (from config.yaml DEFAULT_SYMBOLS)
    python -m tomic.cli.sync_earnings_eodhd

    # Sync specific symbols
    python -m tomic.cli.sync_earnings_eodhd --symbols AAPL MSFT GOOGL

    # Full backfill from 2018
    python -m tomic.cli.sync_earnings_eodhd --backfill

    # Dry run (show what would change)
    python -m tomic.cli.sync_earnings_eodhd --dry-run

    # Custom date range
    python -m tomic.cli.sync_earnings_eodhd --from-date 2020-01-01 --to-date 2025-12-31
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from tomic import config as app_config
from tomic.config import load_env_file
from tomic.integrations.eodhd import EODHDClient
from tomic.logutils import logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync earnings dates from EODHD API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Symbols to sync (default: all from config.yaml DEFAULT_SYMBOLS)",
    )
    parser.add_argument(
        "--json",
        help="Path to earnings_dates.json (default from config)",
    )
    parser.add_argument(
        "--from-date",
        help="Start date for earnings lookup (YYYY-MM-DD, default: 1 year ago)",
    )
    parser.add_argument(
        "--to-date",
        help="End date for earnings lookup (YYYY-MM-DD, default: 1 year ahead)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Full historical backfill from 2018-01-01",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without applying them",
    )
    parser.add_argument(
        "--api-key",
        help="EODHD API key (default: from EODHD_API_KEY env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Symbols per API request (default: 50)",
    )
    return parser


def load_existing_earnings(path: Path) -> Dict[str, List[str]]:
    """Load existing earnings_dates.json."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_earnings(data: Dict[str, List[str]], path: Path, backup: bool = True) -> None:
    """Save earnings data to JSON with optional backup."""
    if backup and path.exists():
        backup_path = path.with_suffix(".json.bak")
        shutil.copy(path, backup_path)
        logger.info(f"Backup created: {backup_path}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def merge_earnings(
    existing: Dict[str, List[str]],
    new_data: Dict[str, List[str]],
) -> tuple[Dict[str, List[str]], Dict[str, Dict[str, int]]]:
    """Merge new earnings data into existing data.

    Returns:
        Tuple of (merged_data, change_stats)
        change_stats: {symbol: {"added": N, "total": M}}
    """
    merged = {}
    stats: Dict[str, Dict[str, int]] = {}

    # Get all symbols from both sources
    all_symbols = set(existing.keys()) | set(new_data.keys())

    for symbol in all_symbols:
        old_dates = set(existing.get(symbol, []))
        new_dates = set(new_data.get(symbol, []))

        # Merge: keep all unique dates
        combined = sorted(old_dates | new_dates)
        merged[symbol] = combined

        added = len(new_dates - old_dates)
        if added > 0 or symbol in new_data:
            stats[symbol] = {
                "added": added,
                "total": len(combined),
                "old_count": len(old_dates),
            }

    return merged, stats


def run(args: argparse.Namespace) -> int:
    """Run the earnings sync."""
    # Determine symbols to sync
    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        from tomic.services.symbol_service import get_symbol_service
        symbol_service = get_symbol_service()
        # Use active symbols (excludes disqualified) when no specific symbols provided
        symbols = symbol_service.get_active_symbols()
        if not symbols:
            logger.error("No symbols configured. Use --symbols or set DEFAULT_SYMBOLS in config.yaml")
            return 1

    logger.info(f"Syncing earnings for {len(symbols)} symbols")

    # Determine date range
    if args.backfill:
        from_date = "2018-01-01"
        to_date = (date.today() + timedelta(days=365)).isoformat()
    else:
        if args.from_date:
            from_date = args.from_date
        else:
            from_date = (date.today() - timedelta(days=365)).isoformat()

        if args.to_date:
            to_date = args.to_date
        else:
            to_date = (date.today() + timedelta(days=365)).isoformat()

    logger.info(f"Date range: {from_date} to {to_date}")

    # Determine JSON path
    json_path_value = args.json or app_config.get(
        "EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"
    )
    json_path = Path(json_path_value)

    # Load existing data
    existing_data = load_existing_earnings(json_path)
    logger.info(f"Loaded {len(existing_data)} symbols from {json_path}")

    # Fetch from EODHD
    client = EODHDClient(api_key=args.api_key)
    client.connect()

    try:
        new_data = client.fetch_all_symbols_earnings(
            symbols=symbols,
            from_date=from_date,
            to_date=to_date,
            batch_size=args.batch_size,
        )
    finally:
        client.disconnect()

    logger.info(f"Fetched earnings for {len(new_data)} symbols from EODHD")

    # Check for symbols not found
    not_found = set(symbols) - set(new_data.keys())
    if not_found:
        logger.warning(f"No earnings found for: {', '.join(sorted(not_found))}")

    # Merge data
    merged_data, change_stats = merge_earnings(existing_data, new_data)

    # Display changes
    print("\n" + "=" * 60)
    print("EARNINGS SYNC SUMMARY")
    print("=" * 60)

    total_added = 0
    changed_symbols = []

    for symbol in sorted(change_stats.keys()):
        stat = change_stats[symbol]
        added = stat["added"]
        total_added += added
        if added > 0:
            changed_symbols.append(symbol)
            print(f"  {symbol}: +{added} dates (now {stat['total']} total)")

    print("-" * 60)
    print(f"Symbols with new dates: {len(changed_symbols)}")
    print(f"Total new earnings dates: {total_added}")
    print(f"Total symbols in file: {len(merged_data)}")

    if args.dry_run:
        print("\n[DRY RUN] No changes saved.")
        return 0

    if total_added == 0:
        print("\nNo new earnings dates to add.")
        return 0

    # Save merged data
    save_earnings(merged_data, json_path)
    print(f"\nSaved to {json_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    # Load .env file for EODHD_API_KEY
    load_env_file()

    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(stdout=True)

    try:
        return run(args)
    except ValueError as e:
        logger.error(str(e))
        print(f"\n❌ Configuration error: {e}")
        print("Set EODHD_API_KEY environment variable or use --api-key")
        return 1
    except Exception as e:
        logger.exception(f"Sync failed: {e}")
        print(f"\n❌ Sync failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
