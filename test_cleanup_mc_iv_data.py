#!/usr/bin/env python3
"""
Unit tests for cleanup_mc_iv_data.py

Run with: pytest test_cleanup_mc_iv_data.py -v
or: python -m pytest test_cleanup_mc_iv_data.py -v
"""

import json
import os
import tempfile
import shutil
from pathlib import Path
import pytest

from cleanup_mc_iv_data import IVDataCleanup


class TestIVDataCleanup:
    """Test suite for IVDataCleanup class."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory with test files."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def cleanup_instance(self, temp_data_dir):
        """Create a cleanup instance for testing."""
        return IVDataCleanup(str(temp_data_dir), dry_run=False, verbose=False)

    def test_classify_entry_mc(self, cleanup_instance):
        """Test classification of MarketChameleon entries."""
        # Pure MC entry: only date and atm_iv
        mc_entry = {
            "date": "2025-06-24",
            "atm_iv": 0.24109999999999998
        }

        assert cleanup_instance.classify_entry(mc_entry) == 'mc'

    def test_classify_entry_polygon(self, cleanup_instance):
        """Test classification of Polygon entries."""
        # Full Polygon entry with all fields
        polygon_entry = {
            "date": "2025-06-27",
            "atm_iv": 0.2525,
            "iv_rank (HV)": 22.262751238380364,
            "iv_percentile (HV)": 50.224215246636774,
            "term_m1_m2": -3.85,
            "term_m1_m3": -2.82,
            "skew": 4.07
        }

        assert cleanup_instance.classify_entry(polygon_entry) == 'polygon'

        # Polygon entry with only some fields
        partial_polygon_entry = {
            "date": "2025-06-28",
            "atm_iv": 0.26,
            "term_m1_m2": -2.5
        }

        assert cleanup_instance.classify_entry(partial_polygon_entry) == 'polygon'

    def test_classify_entry_unknown(self, cleanup_instance):
        """Test classification of unknown format entries."""
        # Unknown: has extra fields but not Polygon signature
        unknown_entry = {
            "date": "2025-06-29",
            "atm_iv": 0.27,
            "some_future_field": 123
        }

        assert cleanup_instance.classify_entry(unknown_entry) == 'unknown'

        # Entry missing date field (conservative: keep)
        no_date_entry = {
            "atm_iv": 0.28,
            "other_field": 456
        }

        # Should NOT be classified as MC (doesn't have date field)
        assert cleanup_instance.classify_entry(no_date_entry) == 'unknown'

    def test_filter_entries(self, cleanup_instance):
        """Test filtering of entries."""
        entries = [
            {"date": "2025-06-24", "atm_iv": 0.24},  # MC
            {"date": "2025-06-25", "atm_iv": 0.25},  # MC
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "term_m1_m2": -3.0,
                "skew": 2.0
            },  # Polygon
            {
                "date": "2025-06-27",
                "atm_iv": 0.27,
                "future_field": 999
            }  # Unknown
        ]

        filtered, stats = cleanup_instance.filter_entries(entries)

        # Check stats
        assert stats['total'] == 4
        assert stats['mc'] == 2
        assert stats['polygon'] == 1
        assert stats['unknown'] == 1

        # Check filtered result
        assert len(filtered) == 2  # Polygon + Unknown
        assert filtered[0]['date'] == "2025-06-26"  # Polygon
        assert filtered[1]['date'] == "2025-06-27"  # Unknown

    def test_process_file_success(self, temp_data_dir, cleanup_instance):
        """Test successful file processing."""
        # Create test file with mixed MC + Polygon data
        test_file = temp_data_dir / "TEST.json"
        test_data = [
            {"date": "2025-06-24", "atm_iv": 0.24},  # MC
            {"date": "2025-06-25", "atm_iv": 0.25},  # MC
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "iv_percentile (HV)": 50.0,
                "term_m1_m2": -3.0,
                "term_m1_m3": -2.0,
                "skew": 2.0
            },  # Polygon
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        # Process file
        result = cleanup_instance.process_file(test_file)

        assert result is True

        # Verify file was modified
        with open(test_file, 'r') as f:
            cleaned_data = json.load(f)

        # Should only have 1 entry (Polygon)
        assert len(cleaned_data) == 1
        assert cleaned_data[0]['date'] == "2025-06-26"
        assert 'iv_rank (HV)' in cleaned_data[0]

        # Check stats
        assert cleanup_instance.stats['mc_entries_removed'] == 2
        assert cleanup_instance.stats['polygon_entries_kept'] == 1
        assert cleanup_instance.stats['files_processed'] == 1

    def test_process_file_all_mc(self, temp_data_dir, cleanup_instance):
        """Test file with only MC data (should be skipped)."""
        test_file = temp_data_dir / "ALL_MC.json"
        test_data = [
            {"date": "2025-06-24", "atm_iv": 0.24},
            {"date": "2025-06-25", "atm_iv": 0.25},
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        # Process file
        result = cleanup_instance.process_file(test_file)

        # Should return False (skipped)
        assert result is False

        # File should be unchanged
        with open(test_file, 'r') as f:
            data = json.load(f)

        assert len(data) == 2  # Original data preserved

        # Check stats
        assert cleanup_instance.stats['files_skipped'] == 1

    def test_process_file_already_clean(self, temp_data_dir, cleanup_instance):
        """Test file with no MC data (should be skipped)."""
        test_file = temp_data_dir / "CLEAN.json"
        test_data = [
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "term_m1_m2": -3.0,
                "skew": 2.0
            },
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        # Process file
        result = cleanup_instance.process_file(test_file)

        # Should return False (skipped, already clean)
        assert result is False

        # Check stats
        assert cleanup_instance.stats['files_skipped'] == 1

    def test_process_file_invalid_json(self, temp_data_dir, cleanup_instance):
        """Test file with invalid JSON."""
        test_file = temp_data_dir / "INVALID.json"

        with open(test_file, 'w') as f:
            f.write("{invalid json content")

        # Process file
        result = cleanup_instance.process_file(test_file)

        # Should return False (error)
        assert result is False

        # Check stats
        assert cleanup_instance.stats['files_errors'] == 1
        assert len(cleanup_instance.stats['errors']) > 0

    def test_dry_run_mode(self, temp_data_dir):
        """Test dry run mode (no file modifications)."""
        # Create test file
        test_file = temp_data_dir / "DRYRUN.json"
        test_data = [
            {"date": "2025-06-24", "atm_iv": 0.24},  # MC
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "term_m1_m2": -3.0,
                "skew": 2.0
            },  # Polygon
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        # Create cleanup instance in dry run mode
        cleanup = IVDataCleanup(str(temp_data_dir), dry_run=True, verbose=False)

        # Process file
        result = cleanup.process_file(test_file)

        assert result is True

        # File should be UNCHANGED
        with open(test_file, 'r') as f:
            data = json.load(f)

        assert len(data) == 2  # Original data preserved

        # But stats should be updated
        assert cleanup.stats['mc_entries_removed'] == 1
        assert cleanup.stats['polygon_entries_kept'] == 1

    def test_create_backup(self, temp_data_dir):
        """Test backup creation and verification."""
        # Create some test files
        for symbol in ['AAPL', 'MSFT', 'TSLA']:
            test_file = temp_data_dir / f"{symbol}.json"
            test_data = [
                {"date": "2025-06-24", "atm_iv": 0.24},
                {
                    "date": "2025-06-26",
                    "atm_iv": 0.26,
                    "iv_rank (HV)": 20.0,
                    "term_m1_m2": -3.0,
                    "skew": 2.0
                },
            ]

            with open(test_file, 'w') as f:
                json.dump(test_data, f, indent=2)

        # Create cleanup instance
        cleanup = IVDataCleanup(str(temp_data_dir), dry_run=False, verbose=False)

        # Create backup
        result = cleanup.create_backup()

        assert result is True
        assert cleanup.backup_dir is not None
        assert cleanup.backup_dir.exists()

        # Verify backup files exist
        backup_files = list(cleanup.backup_dir.glob("*.json"))
        assert len(backup_files) == 4  # 3 symbol files + manifest

        # Verify manifest exists
        manifest_path = cleanup.backup_dir / "backup_manifest.json"
        assert manifest_path.exists()

        with open(manifest_path, 'r') as f:
            manifest = json.load(f)

        assert 'timestamp' in manifest
        assert 'files' in manifest
        assert len(manifest['files']) == 3  # 3 symbol files

    def test_process_all_files(self, temp_data_dir):
        """Test processing all files in directory."""
        # Create multiple test files
        symbols = ['AAPL', 'MSFT', 'TSLA', 'GOOGL']

        for symbol in symbols:
            test_file = temp_data_dir / f"{symbol}.json"
            test_data = [
                {"date": "2025-06-24", "atm_iv": 0.24},  # MC
                {"date": "2025-06-25", "atm_iv": 0.25},  # MC
                {
                    "date": "2025-06-26",
                    "atm_iv": 0.26,
                    "iv_rank (HV)": 20.0,
                    "term_m1_m2": -3.0,
                    "skew": 2.0
                },  # Polygon
            ]

            with open(test_file, 'w') as f:
                json.dump(test_data, f, indent=2)

        # Create cleanup instance
        cleanup = IVDataCleanup(str(temp_data_dir), dry_run=False, verbose=False)

        # Process all files
        cleanup.process_all_files()

        # Check stats
        assert cleanup.stats['files_processed'] == 4
        assert cleanup.stats['mc_entries_removed'] == 8  # 2 per file × 4 files
        assert cleanup.stats['polygon_entries_kept'] == 4  # 1 per file × 4 files

        # Verify all files were cleaned
        for symbol in symbols:
            test_file = temp_data_dir / f"{symbol}.json"

            with open(test_file, 'r') as f:
                data = json.load(f)

            assert len(data) == 1  # Only Polygon entry
            assert 'iv_rank (HV)' in data[0]

    def test_generate_report(self, temp_data_dir):
        """Test report generation."""
        # Create and process a test file
        test_file = temp_data_dir / "REPORT_TEST.json"
        test_data = [
            {"date": "2025-06-24", "atm_iv": 0.24},
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "term_m1_m2": -3.0,
                "skew": 2.0
            },
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        cleanup = IVDataCleanup(str(temp_data_dir), dry_run=True, verbose=False)
        cleanup.process_file(test_file)

        # Generate report
        report = cleanup.generate_report()

        # Check report content
        assert "MarketChameleon IV Data Cleanup Report" in report
        assert "SUMMARY" in report
        assert "Files processed:" in report
        assert "Total MC entries removed:" in report
        assert "Total Polygon kept:" in report

    def test_edge_case_null_values(self, cleanup_instance):
        """Test entries with null values."""
        # Polygon entry with null values (should still be kept)
        polygon_entry_with_nulls = {
            "date": "2025-06-26",
            "atm_iv": None,
            "iv_rank (HV)": None,
            "iv_percentile (HV)": None,
            "term_m1_m2": None,
            "term_m1_m3": None,
            "skew": None
        }

        # Should be classified as Polygon (has the fields)
        assert cleanup_instance.classify_entry(polygon_entry_with_nulls) == 'polygon'

    def test_edge_case_date_sorting(self, temp_data_dir, cleanup_instance):
        """Test that entries are sorted by date after filtering."""
        test_file = temp_data_dir / "SORT_TEST.json"
        test_data = [
            {
                "date": "2025-06-28",
                "atm_iv": 0.28,
                "iv_rank (HV)": 22.0,
                "term_m1_m2": -2.0,
                "skew": 3.0
            },
            {"date": "2025-06-24", "atm_iv": 0.24},  # MC (will be removed)
            {
                "date": "2025-06-26",
                "atm_iv": 0.26,
                "iv_rank (HV)": 20.0,
                "term_m1_m2": -3.0,
                "skew": 2.0
            },
        ]

        with open(test_file, 'w') as f:
            json.dump(test_data, f, indent=2)

        cleanup_instance.process_file(test_file)

        # Verify sorted order
        with open(test_file, 'r') as f:
            data = json.load(f)

        assert len(data) == 2
        assert data[0]['date'] == "2025-06-26"
        assert data[1]['date'] == "2025-06-28"


def test_main_dry_run(temp_data_dir):
    """Integration test: full dry run."""
    # Create test files
    test_file = temp_data_dir / "INTEGRATION.json"
    test_data = [
        {"date": "2025-06-24", "atm_iv": 0.24},
        {
            "date": "2025-06-26",
            "atm_iv": 0.26,
            "iv_rank (HV)": 20.0,
            "term_m1_m2": -3.0,
            "skew": 2.0
        },
    ]

    with open(test_file, 'w') as f:
        json.dump(test_data, f, indent=2)

    # Run cleanup in dry run mode
    cleanup = IVDataCleanup(str(temp_data_dir), dry_run=True, verbose=False)
    result = cleanup.run()

    # Should succeed
    assert result is True

    # File should be unchanged
    with open(test_file, 'r') as f:
        data = json.load(f)

    assert len(data) == 2  # Original data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
