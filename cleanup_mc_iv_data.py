#!/usr/bin/env python3
"""
MarketChameleon IV Data Cleanup Script

This script removes legacy MarketChameleon entries from IV daily summary files,
keeping only Polygon.io data with full metrics (iv_rank, term_m1_m2, skew, etc.).

Usage:
    python cleanup_mc_iv_data.py [--dry-run] [--data-dir PATH] [--rollback BACKUP_DIR] [--verbose]

Features:
    - Automatic backup with MD5 verification
    - Atomic file writes (no partial corruptions)
    - Per-file error handling (one failure doesn't stop the process)
    - Comprehensive reporting with statistics
    - Rollback capability for safety

Author: Arne van Veen
Created: 2025-11-23
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


class IVDataCleanup:
    """Main cleanup orchestrator for MarketChameleon IV data removal."""

    def __init__(self, data_dir: str, dry_run: bool = False, verbose: bool = False):
        self.data_dir = Path(data_dir)
        self.dry_run = dry_run
        self.verbose = verbose
        self.backup_dir = None
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Statistics tracking
        self.stats = {
            'files_total': 0,
            'files_processed': 0,
            'files_skipped': 0,
            'files_errors': 0,
            'mc_entries_removed': 0,
            'polygon_entries_kept': 0,
            'bytes_before': 0,
            'bytes_after': 0,
            'errors': []
        }

        # Per-symbol detailed stats
        self.symbol_stats = []

    def log(self, message: str, level: str = "INFO"):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"[{timestamp}] [{level}]"
        print(f"{prefix} {message}")

        if level == "ERROR":
            self.stats['errors'].append(message)

    def verbose_log(self, message: str):
        """Log only if verbose mode is enabled."""
        if self.verbose:
            self.log(message, "DEBUG")

    def classify_entry(self, entry: dict) -> str:
        """
        Classify an IV data entry as MC, Polygon, or Unknown.

        Returns:
            'mc': MarketChameleon legacy entry (DELETE)
            'polygon': Polygon entry with full metrics (KEEP)
            'unknown': Unknown format (KEEP, conservative)
        """
        keys = set(entry.keys())

        # MC signature: exactly date + atm_iv, nothing else
        if keys == {'date', 'atm_iv'}:
            return 'mc'

        # Polygon signature: has ANY of the extended fields
        polygon_fields = {
            'iv_rank (HV)',
            'iv_percentile (HV)',
            'term_m1_m2',
            'term_m1_m3',
            'skew'
        }

        if any(field in keys for field in polygon_fields):
            return 'polygon'

        # Unknown format: has other fields, but not MC or Polygon signature
        # Conservative: KEEP (might be future data format)
        return 'unknown'

    def filter_entries(self, entries: List[dict]) -> Tuple[List[dict], Dict[str, int]]:
        """
        Filter out MC entries, keep Polygon and Unknown.

        Returns:
            (filtered_entries, stats_dict)
        """
        stats = {
            'total': len(entries),
            'mc': 0,
            'polygon': 0,
            'unknown': 0
        }

        filtered = []
        for entry in entries:
            classification = self.classify_entry(entry)
            stats[classification] += 1

            if classification != 'mc':
                filtered.append(entry)

        return filtered, stats

    def calculate_md5(self, file_path: Path) -> str:
        """Calculate MD5 checksum of a file."""
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def create_backup(self) -> bool:
        """
        Create timestamped backup of all JSON files.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create backup directory
            self.backup_dir = self.data_dir / f"backup_{self.timestamp}"
            self.backup_dir.mkdir(exist_ok=True)

            self.log(f"Creating backup in: {self.backup_dir}")

            # Copy all JSON files
            json_files = list(self.data_dir.glob("*.json"))
            self.stats['files_total'] = len(json_files)

            manifest = {
                'timestamp': self.timestamp,
                'files': []
            }

            for json_file in json_files:
                if json_file.name.startswith('backup_'):
                    continue  # Skip backup directories

                dest = self.backup_dir / json_file.name
                shutil.copy2(json_file, dest)

                # Store metadata
                manifest['files'].append({
                    'name': json_file.name,
                    'size': json_file.stat().st_size,
                    'md5': self.calculate_md5(json_file)
                })

            # Save manifest
            manifest_path = self.backup_dir / "backup_manifest.json"
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)

            # Verify backup integrity (random sample of 10 files)
            import random
            sample_size = min(10, len(json_files))
            sample_files = random.sample(json_files, sample_size)

            self.log(f"Verifying backup integrity ({sample_size} random samples)...")
            for json_file in sample_files:
                original_md5 = self.calculate_md5(json_file)
                backup_md5 = self.calculate_md5(self.backup_dir / json_file.name)

                if original_md5 != backup_md5:
                    self.log(f"Backup verification FAILED for {json_file.name}", "ERROR")
                    return False

            self.log(f"✓ Backup verified: {len(json_files)} files backed up")
            return True

        except Exception as e:
            self.log(f"Backup creation failed: {e}", "ERROR")
            return False

    def process_file(self, json_file: Path) -> bool:
        """
        Process a single JSON file: load, filter, validate, write.

        Returns:
            True if successful, False otherwise
        """
        symbol = json_file.stem

        try:
            # Get original file size
            size_before = json_file.stat().st_size

            # Load JSON
            with open(json_file, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                self.log(f"{symbol}: Not a list, skipping", "WARNING")
                return False

            original_count = len(data)

            # Filter entries
            filtered_data, entry_stats = self.filter_entries(data)

            # Check if filtering removed everything
            if len(filtered_data) == 0:
                self.log(f"{symbol}: All entries would be removed! Skipping (keeping original)", "WARNING")
                self.stats['files_skipped'] += 1
                return False

            # Check if no cleanup needed
            if entry_stats['mc'] == 0:
                self.verbose_log(f"{symbol}: Already clean (100% Polygon), skipping")
                self.stats['files_skipped'] += 1
                return False

            # Sort by date
            filtered_data.sort(key=lambda x: x.get('date', ''))

            # Validate filtered result
            for entry in filtered_data:
                if 'date' not in entry:
                    self.log(f"{symbol}: Entry without 'date' field found", "WARNING")
                if 'atm_iv' not in entry:
                    self.log(f"{symbol}: Entry without 'atm_iv' field found", "WARNING")

            if self.dry_run:
                # Dry run: just calculate what would happen
                mc_removed = entry_stats['mc']
                polygon_kept = entry_stats['polygon'] + entry_stats['unknown']

                self.log(f"{symbol}: Would remove {mc_removed} MC entries, keep {polygon_kept} Polygon entries")

                # Update stats
                self.stats['mc_entries_removed'] += mc_removed
                self.stats['polygon_entries_kept'] += polygon_kept
                self.stats['files_processed'] += 1
                self.stats['bytes_before'] += size_before

                # Add to symbol stats
                self.symbol_stats.append({
                    'symbol': symbol,
                    'original': original_count,
                    'mc_removed': mc_removed,
                    'polygon_kept': polygon_kept,
                    'percent_reduced': (mc_removed / original_count * 100) if original_count > 0 else 0,
                    'size_before': size_before,
                    'size_after': size_before  # No actual change in dry run
                })

                return True

            # Write to temp file first (atomic write)
            temp_fd, temp_path = tempfile.mkstemp(suffix='.json', dir=json_file.parent)

            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(filtered_data, f, indent=2, ensure_ascii=False)

                # Verify write success by re-loading
                with open(temp_path, 'r') as f:
                    verified_data = json.load(f)

                if len(verified_data) != len(filtered_data):
                    raise ValueError("Verification failed: entry count mismatch")

                # Atomic replace
                shutil.move(temp_path, json_file)

                # Get new file size
                size_after = json_file.stat().st_size

                mc_removed = entry_stats['mc']
                polygon_kept = entry_stats['polygon'] + entry_stats['unknown']

                self.log(f"{symbol}: Removed {mc_removed} MC entries, kept {polygon_kept} Polygon entries")

                # Update stats
                self.stats['mc_entries_removed'] += mc_removed
                self.stats['polygon_entries_kept'] += polygon_kept
                self.stats['files_processed'] += 1
                self.stats['bytes_before'] += size_before
                self.stats['bytes_after'] += size_after

                # Add to symbol stats
                self.symbol_stats.append({
                    'symbol': symbol,
                    'original': original_count,
                    'mc_removed': mc_removed,
                    'polygon_kept': polygon_kept,
                    'percent_reduced': (mc_removed / original_count * 100) if original_count > 0 else 0,
                    'size_before': size_before,
                    'size_after': size_after
                })

                return True

            except Exception as e:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

        except json.JSONDecodeError as e:
            self.log(f"{symbol}: JSONDecodeError at line {e.lineno}: {e.msg}", "ERROR")
            self.stats['files_errors'] += 1
            return False

        except Exception as e:
            self.log(f"{symbol}: Error processing file: {e}", "ERROR")
            self.stats['files_errors'] += 1
            return False

    def process_all_files(self):
        """Process all JSON files in the data directory."""
        json_files = sorted([f for f in self.data_dir.glob("*.json")
                           if not f.name.startswith('backup_')])

        self.log(f"Found {len(json_files)} JSON files to process")

        for i, json_file in enumerate(json_files, 1):
            self.verbose_log(f"Processing {i}/{len(json_files)}: {json_file.name}")
            self.process_file(json_file)

    def generate_report(self) -> str:
        """Generate comprehensive cleanup report."""
        lines = []
        lines.append("=" * 80)
        lines.append("MarketChameleon IV Data Cleanup Report")
        lines.append("=" * 80)
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Mode: {'DRY RUN (no changes made)' if self.dry_run else 'PRODUCTION'}")
        lines.append("")

        # Summary table
        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Total files found:          {self.stats['files_total']}")
        lines.append(f"Files processed:            {self.stats['files_processed']}")
        lines.append(f"Files skipped:              {self.stats['files_skipped']}")
        lines.append(f"Files with errors:          {self.stats['files_errors']}")
        lines.append(f"Total MC entries removed:   {self.stats['mc_entries_removed']}")
        lines.append(f"Total Polygon kept:         {self.stats['polygon_entries_kept']}")

        if not self.dry_run:
            bytes_saved = self.stats['bytes_before'] - self.stats['bytes_after']
            mb_saved = bytes_saved / (1024 * 1024)
            mb_before = self.stats['bytes_before'] / (1024 * 1024)
            mb_after = self.stats['bytes_after'] / (1024 * 1024)

            lines.append(f"Disk space before:          {mb_before:.2f} MB")
            lines.append(f"Disk space after:           {mb_after:.2f} MB")
            lines.append(f"Disk space saved:           {mb_saved:.2f} MB ({bytes_saved/self.stats['bytes_before']*100:.1f}%)")

        lines.append("")

        # Per-symbol stats (top 20 by MC removal)
        if self.symbol_stats:
            lines.append("TOP 20 SYMBOLS BY MC ENTRIES REMOVED")
            lines.append("-" * 80)
            lines.append(f"{'Symbol':<10} {'Original':>8} {'MC Removed':>11} {'Polygon':>8} {'% Reduced':>10} {'Size Before':>12} {'Size After':>11}")
            lines.append("-" * 80)

            sorted_stats = sorted(self.symbol_stats, key=lambda x: x['mc_removed'], reverse=True)[:20]

            for stat in sorted_stats:
                size_before_kb = stat['size_before'] / 1024
                size_after_kb = stat['size_after'] / 1024

                lines.append(
                    f"{stat['symbol']:<10} "
                    f"{stat['original']:>8} "
                    f"{stat['mc_removed']:>11} "
                    f"{stat['polygon_kept']:>8} "
                    f"{stat['percent_reduced']:>9.1f}% "
                    f"{size_before_kb:>10.1f} KB "
                    f"{size_after_kb:>10.1f} KB"
                )

        lines.append("")

        # Errors
        if self.stats['errors']:
            lines.append("ERRORS")
            lines.append("-" * 80)
            for error in self.stats['errors']:
                lines.append(f"  - {error}")
            lines.append("")

        # Backup info
        if self.backup_dir and not self.dry_run:
            lines.append("BACKUP INFORMATION")
            lines.append("-" * 80)
            lines.append(f"Backup location: {self.backup_dir}")
            lines.append(f"Backup verified: ✓ MD5 checksums match for random samples")
            lines.append(f"")
            lines.append(f"Rollback command:")
            lines.append(f"  python {sys.argv[0]} --rollback {self.backup_dir.name}")
            lines.append("")

        lines.append("=" * 80)

        return "\n".join(lines)

    def save_report(self, report: str):
        """Save report to file."""
        # Create reports directory if it doesn't exist
        reports_dir = Path("tomic/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_file = reports_dir / f"cleanup_report_{self.timestamp}.txt"

        with open(report_file, 'w') as f:
            f.write(report)

        self.log(f"Report saved to: {report_file}")

    def run(self):
        """Main execution flow."""
        start_time = time.time()

        self.log("Starting MarketChameleon IV data cleanup...")

        if self.dry_run:
            self.log("DRY RUN MODE - No files will be modified")

        # Verify data directory exists
        if not self.data_dir.exists():
            self.log(f"Data directory not found: {self.data_dir}", "ERROR")
            return False

        # Create backup (skip in dry run)
        if not self.dry_run:
            if not self.create_backup():
                self.log("Backup creation failed - aborting", "ERROR")
                return False

        # Process all files
        self.process_all_files()

        # Generate and save report
        elapsed_time = time.time() - start_time
        self.log(f"Cleanup completed in {elapsed_time:.1f} seconds")

        report = self.generate_report()
        print("\n" + report)

        if not self.dry_run:
            self.save_report(report)

        return True


def rollback_backup(backup_dir: str, data_dir: str) -> bool:
    """
    Restore files from a backup directory.

    Args:
        backup_dir: Path to backup directory (e.g., 'backup_20251123_143022')
        data_dir: Path to data directory to restore to

    Returns:
        True if successful, False otherwise
    """
    backup_path = Path(data_dir) / backup_dir

    if not backup_path.exists():
        print(f"ERROR: Backup directory not found: {backup_path}")
        return False

    print(f"Restoring files from: {backup_path}")

    # Load manifest
    manifest_path = backup_path / "backup_manifest.json"
    if not manifest_path.exists():
        print("WARNING: No manifest found, proceeding with basic restore")
        manifest_data = None
    else:
        with open(manifest_path, 'r') as f:
            manifest_data = json.load(f)
        print(f"Backup timestamp: {manifest_data['timestamp']}")

    # Restore all JSON files
    json_files = list(backup_path.glob("*.json"))

    for backup_file in json_files:
        if backup_file.name == 'backup_manifest.json':
            continue

        dest = Path(data_dir) / backup_file.name
        shutil.copy2(backup_file, dest)
        print(f"  Restored: {backup_file.name}")

    # Verify restoration
    if manifest_data:
        print("\nVerifying restoration...")
        for file_info in manifest_data['files']:
            restored_path = Path(data_dir) / file_info['name']

            if not restored_path.exists():
                print(f"  ERROR: {file_info['name']} not restored")
                continue

            # Check MD5 (compare with backup MD5, not original)
            backup_file_path = backup_path / file_info['name']
            backup_md5 = hashlib.md5()
            with open(backup_file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    backup_md5.update(chunk)

            restored_md5 = hashlib.md5()
            with open(restored_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    restored_md5.update(chunk)

            if backup_md5.hexdigest() != restored_md5.hexdigest():
                print(f"  ERROR: MD5 mismatch for {file_info['name']}")
            else:
                print(f"  ✓ {file_info['name']}")

    print(f"\n✓ Rollback completed: {len(json_files)} files restored")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Clean up legacy MarketChameleon entries from IV daily summary files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes without modifying files
  python cleanup_mc_iv_data.py --dry-run

  # Run cleanup on default directory
  python cleanup_mc_iv_data.py

  # Run cleanup on custom directory with verbose logging
  python cleanup_mc_iv_data.py --data-dir /path/to/data --verbose

  # Rollback changes from a backup
  python cleanup_mc_iv_data.py --rollback backup_20251123_143022
        """
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview mode: analyze files without making changes'
    )

    parser.add_argument(
        '--data-dir',
        default='tomic/data/iv_daily_summary',
        help='Path to IV daily summary data directory (default: tomic/data/iv_daily_summary)'
    )

    parser.add_argument(
        '--rollback',
        metavar='BACKUP_DIR',
        help='Restore files from specified backup directory (e.g., backup_20251123_143022)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging for debugging'
    )

    args = parser.parse_args()

    # Handle rollback
    if args.rollback:
        success = rollback_backup(args.rollback, args.data_dir)
        sys.exit(0 if success else 1)

    # Run cleanup
    cleanup = IVDataCleanup(
        data_dir=args.data_dir,
        dry_run=args.dry_run,
        verbose=args.verbose
    )

    success = cleanup.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
