"""CLI for importing MarketChameleon earnings backfill data.

Usage:
    python -m tomic.cli.import_earnings_backfill [--dry-run]

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
import sys

from tomic.api.earnings_backfill_importer import run_backfill_import
from tomic.logutils import logger


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import MarketChameleon earnings backfill CSVs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without saving",
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Path to backfill folder (default: tomic/data/MC_earningBackfill/)",
    )
    args = parser.parse_args()

    try:
        stats = run_backfill_import(
            backfill_folder=args.folder,
            dry_run=args.dry_run,
        )

        print("\n" + "=" * 50)
        print("IMPORT SUMMARY")
        print("=" * 50)
        print(f"Symbols processed: {stats['symbols_processed']}")
        print(f"  - New symbols:   {stats.get('symbols_new', 0)}")
        print(f"  - Updated:       {stats.get('symbols_updated', 0)}")
        print(f"Records added:     {stats['records_added']}")

        if args.dry_run:
            print("\n[DRY RUN - no files were saved]")

        return 0

    except Exception as exc:
        logger.error(f"Import failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
