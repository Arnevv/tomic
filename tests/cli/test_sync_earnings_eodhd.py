"""Tests for EODHD earnings sync CLI."""

import json
from pathlib import Path

import pytest


def test_merge_earnings_adds_new_dates():
    """Test that new dates are merged correctly."""
    from tomic.cli.sync_earnings_eodhd import merge_earnings

    existing = {
        "AAPL": ["2024-01-25", "2024-05-02"],
        "MSFT": ["2024-01-30"],
    }
    new_data = {
        "AAPL": ["2024-05-02", "2024-07-25"],  # One overlap, one new
        "GOOGL": ["2024-04-25"],  # New symbol
    }

    merged, stats = merge_earnings(existing, new_data)

    # Check merged data
    assert merged["AAPL"] == ["2024-01-25", "2024-05-02", "2024-07-25"]
    assert merged["MSFT"] == ["2024-01-30"]  # Unchanged
    assert merged["GOOGL"] == ["2024-04-25"]  # New

    # Check stats
    assert stats["AAPL"]["added"] == 1
    assert stats["GOOGL"]["added"] == 1


def test_merge_earnings_handles_empty_existing():
    """Test merge with empty existing data."""
    from tomic.cli.sync_earnings_eodhd import merge_earnings

    existing = {}
    new_data = {
        "AAPL": ["2024-01-25", "2024-05-02"],
    }

    merged, stats = merge_earnings(existing, new_data)

    assert merged["AAPL"] == ["2024-01-25", "2024-05-02"]
    assert stats["AAPL"]["added"] == 2


def test_merge_earnings_sorts_dates():
    """Test that dates are sorted after merge."""
    from tomic.cli.sync_earnings_eodhd import merge_earnings

    existing = {
        "AAPL": ["2024-05-02"],
    }
    new_data = {
        "AAPL": ["2024-01-25", "2024-07-25"],
    }

    merged, _ = merge_earnings(existing, new_data)

    assert merged["AAPL"] == ["2024-01-25", "2024-05-02", "2024-07-25"]


def test_load_existing_earnings_returns_empty_for_missing_file(tmp_path):
    """Test that missing file returns empty dict."""
    from tomic.cli.sync_earnings_eodhd import load_existing_earnings

    result = load_existing_earnings(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_existing_earnings_reads_file(tmp_path):
    """Test that existing file is read correctly."""
    from tomic.cli.sync_earnings_eodhd import load_existing_earnings

    data = {"AAPL": ["2024-01-25"]}
    path = tmp_path / "earnings.json"
    path.write_text(json.dumps(data))

    result = load_existing_earnings(path)
    assert result == data


def test_save_earnings_creates_backup(tmp_path):
    """Test that backup is created when saving."""
    from tomic.cli.sync_earnings_eodhd import save_earnings

    original_data = {"AAPL": ["2024-01-25"]}
    new_data = {"AAPL": ["2024-01-25", "2024-05-02"]}

    path = tmp_path / "earnings.json"
    path.write_text(json.dumps(original_data))

    save_earnings(new_data, path, backup=True)

    # Check backup exists
    backup_path = path.with_suffix(".json.bak")
    assert backup_path.exists()
    assert json.loads(backup_path.read_text()) == original_data

    # Check new data saved
    assert json.loads(path.read_text()) == new_data


def test_cli_dry_run_does_not_save(monkeypatch, tmp_path):
    """Test that --dry-run doesn't modify files."""
    from tomic.cli import sync_earnings_eodhd

    original_data = {"AAPL": ["2024-01-25"]}
    path = tmp_path / "earnings.json"
    path.write_text(json.dumps(original_data))

    # Mock EODHD client
    class MockClient:
        def connect(self):
            pass

        def disconnect(self):
            pass

        def fetch_all_symbols_earnings(self, **kwargs):
            return {"AAPL": ["2024-01-25", "2024-05-02"]}

    monkeypatch.setattr(sync_earnings_eodhd, "EODHDClient", lambda **kw: MockClient())
    monkeypatch.setattr(sync_earnings_eodhd.app_config, "get", lambda k, d=None: ["AAPL"])

    # Run with dry-run
    from argparse import Namespace

    args = Namespace(
        symbols=["AAPL"],
        json=str(path),
        from_date=None,
        to_date=None,
        backfill=False,
        dry_run=True,
        api_key="test",
        batch_size=50,
    )

    sync_earnings_eodhd.run(args)

    # Check file unchanged
    assert json.loads(path.read_text()) == original_data


def test_cli_saves_merged_data(monkeypatch, tmp_path):
    """Test that merged data is saved correctly."""
    from tomic.cli import sync_earnings_eodhd

    original_data = {"AAPL": ["2024-01-25"]}
    path = tmp_path / "earnings.json"
    path.write_text(json.dumps(original_data))

    # Mock EODHD client
    class MockClient:
        def connect(self):
            pass

        def disconnect(self):
            pass

        def fetch_all_symbols_earnings(self, **kwargs):
            return {"AAPL": ["2024-01-25", "2024-05-02"]}

    monkeypatch.setattr(sync_earnings_eodhd, "EODHDClient", lambda **kw: MockClient())
    monkeypatch.setattr(sync_earnings_eodhd.app_config, "get", lambda k, d=None: ["AAPL"])

    from argparse import Namespace

    args = Namespace(
        symbols=["AAPL"],
        json=str(path),
        from_date=None,
        to_date=None,
        backfill=False,
        dry_run=False,
        api_key="test",
        batch_size=50,
    )

    sync_earnings_eodhd.run(args)

    # Check merged data saved
    saved = json.loads(path.read_text())
    assert saved["AAPL"] == ["2024-01-25", "2024-05-02"]
