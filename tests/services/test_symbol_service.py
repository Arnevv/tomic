"""Tests for symbol service."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tomic.services.symbol_service import (
    SymbolService,
    SymbolMetadata,
    DataValidationResult,
)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory structure."""
    data_dir = tmp_path / "tomic" / "data"
    data_dir.mkdir(parents=True)

    # Create subdirectories
    (data_dir / "spot_prices").mkdir()
    (data_dir / "iv_daily_summary").mkdir()

    return tmp_path


@pytest.fixture
def symbol_service(temp_data_dir):
    """Create symbol service with temp directory."""
    return SymbolService(base_dir=temp_data_dir)


class TestSymbolMetadata:
    """Tests for SymbolMetadata dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        meta = SymbolMetadata(
            symbol="AAPL",
            sector="Technology",
            avg_atm_call_volume=100000,
        )
        result = meta.to_dict()

        assert result["symbol"] == "AAPL"
        assert result["sector"] == "Technology"
        assert result["avg_atm_call_volume"] == 100000
        # None values should be excluded
        assert "industry" not in result or result["industry"] is None

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "symbol": "MSFT",
            "sector": "Technology",
            "industry": "Software",
            "avg_atm_call_volume": 50000,
        }
        meta = SymbolMetadata.from_dict(data)

        assert meta.symbol == "MSFT"
        assert meta.sector == "Technology"
        assert meta.industry == "Software"
        assert meta.avg_atm_call_volume == 50000

    def test_from_dict_missing_fields(self):
        """Test creation from dictionary with missing fields."""
        data = {"symbol": "TEST"}
        meta = SymbolMetadata.from_dict(data)

        assert meta.symbol == "TEST"
        assert meta.sector is None
        assert meta.data_status == "unknown"


class TestDataValidationResult:
    """Tests for DataValidationResult dataclass."""

    def test_is_complete_true(self):
        """Test is_complete when all data present."""
        result = DataValidationResult(
            symbol="AAPL",
            has_spot_prices=True,
            has_iv_summary=True,
        )
        assert result.is_complete is True
        assert result.status == "complete"

    def test_is_complete_false_partial(self):
        """Test is_complete when partial data present."""
        result = DataValidationResult(
            symbol="AAPL",
            has_spot_prices=True,
            has_iv_summary=False,
        )
        assert result.is_complete is False
        assert result.status == "incomplete"

    def test_is_complete_false_missing(self):
        """Test is_complete when no data present."""
        result = DataValidationResult(
            symbol="AAPL",
            has_spot_prices=False,
            has_iv_summary=False,
        )
        assert result.is_complete is False
        assert result.status == "missing"


class TestSymbolServiceConfig:
    """Tests for symbol configuration management."""

    def test_get_configured_symbols(self, symbol_service, monkeypatch):
        """Test getting configured symbols."""
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: ["AAPL", "MSFT"] if key == "DEFAULT_SYMBOLS" else default,
        )

        symbols = symbol_service.get_configured_symbols()
        assert symbols == ["AAPL", "MSFT"]

    def test_add_to_config(self, symbol_service, monkeypatch):
        """Test adding symbols to config."""
        current_symbols = ["AAPL"]
        updated_symbols = []

        def mock_get(key, default=None):
            if key == "DEFAULT_SYMBOLS":
                return current_symbols
            return default

        def mock_update(values):
            nonlocal updated_symbols
            updated_symbols = values.get("DEFAULT_SYMBOLS", [])

        monkeypatch.setattr("tomic.services.symbol_service.cfg_get", mock_get)
        monkeypatch.setattr("tomic.services.symbol_service.cfg_update", mock_update)

        added = symbol_service.add_to_config(["MSFT", "GOOGL"])

        assert sorted(added) == ["GOOGL", "MSFT"]
        assert sorted(updated_symbols) == ["AAPL", "GOOGL", "MSFT"]

    def test_add_to_config_already_exists(self, symbol_service, monkeypatch):
        """Test adding symbol that already exists."""
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: ["AAPL", "MSFT"] if key == "DEFAULT_SYMBOLS" else default,
        )
        monkeypatch.setattr("tomic.services.symbol_service.cfg_update", lambda x: None)

        added = symbol_service.add_to_config(["AAPL"])

        assert added == []

    def test_remove_from_config(self, symbol_service, monkeypatch):
        """Test removing symbols from config."""
        current_symbols = ["AAPL", "MSFT", "GOOGL"]
        updated_symbols = []

        def mock_get(key, default=None):
            if key == "DEFAULT_SYMBOLS":
                return current_symbols
            return default

        def mock_update(values):
            nonlocal updated_symbols
            updated_symbols = values.get("DEFAULT_SYMBOLS", [])

        monkeypatch.setattr("tomic.services.symbol_service.cfg_get", mock_get)
        monkeypatch.setattr("tomic.services.symbol_service.cfg_update", mock_update)

        removed = symbol_service.remove_from_config(["MSFT"])

        assert removed == ["MSFT"]
        assert sorted(updated_symbols) == ["AAPL", "GOOGL"]

    def test_remove_from_config_not_exists(self, symbol_service, monkeypatch):
        """Test removing symbol that doesn't exist."""
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: ["AAPL"] if key == "DEFAULT_SYMBOLS" else default,
        )
        monkeypatch.setattr("tomic.services.symbol_service.cfg_update", lambda x: None)

        removed = symbol_service.remove_from_config(["XYZ"])

        assert removed == []


class TestSymbolServiceDataFiles:
    """Tests for data file management."""

    def test_get_symbol_data_files(self, symbol_service, temp_data_dir):
        """Test getting data file paths."""
        files = symbol_service.get_symbol_data_files("aapl")

        assert "spot_prices" in files
        assert "iv_summary" in files
        assert files["spot_prices"].name == "AAPL.json"
        assert files["iv_summary"].name == "AAPL.json"

    def test_delete_symbol_data(self, symbol_service, temp_data_dir, monkeypatch):
        """Test deleting symbol data files."""
        # Create test files
        spot_dir = temp_data_dir / "tomic" / "data" / "spot_prices"
        iv_dir = temp_data_dir / "tomic" / "data" / "iv_daily_summary"

        spot_file = spot_dir / "TEST.json"
        iv_file = iv_dir / "TEST.json"

        spot_file.write_text("[]")
        iv_file.write_text("[]")

        # Mock config paths
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(iv_dir),
                "PRICE_META_FILE": str(temp_data_dir / "price_meta.json"),
                "EARNINGS_DATES_FILE": str(temp_data_dir / "tomic" / "data" / "earnings_dates.json"),
            }.get(key, default),
        )

        deleted = symbol_service.delete_symbol_data("TEST")

        assert len(deleted) == 2
        assert not spot_file.exists()
        assert not iv_file.exists()


class TestSymbolServiceValidation:
    """Tests for data validation."""

    def test_validate_symbol_data_complete(self, symbol_service, temp_data_dir, monkeypatch):
        """Test validation with complete data."""
        spot_dir = temp_data_dir / "tomic" / "data" / "spot_prices"
        iv_dir = temp_data_dir / "tomic" / "data" / "iv_daily_summary"

        # Create test data files
        spot_file = spot_dir / "AAPL.json"
        iv_file = iv_dir / "AAPL.json"

        spot_file.write_text(json.dumps([{"date": "2024-01-01", "close": 100}]))
        iv_file.write_text(json.dumps([{"date": "2024-01-01", "atm_iv": 0.25}]))

        # Mock config paths
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(iv_dir),
                "EARNINGS_DATES_FILE": str(temp_data_dir / "tomic" / "data" / "earnings_dates.json"),
            }.get(key, default),
        )

        result = symbol_service.validate_symbol_data("AAPL")

        assert result.has_spot_prices is True
        assert result.has_iv_summary is True
        assert result.spot_price_days == 1
        assert result.iv_summary_days == 1
        assert result.is_complete is True

    def test_validate_symbol_data_incomplete(self, symbol_service, temp_data_dir, monkeypatch):
        """Test validation with incomplete data."""
        spot_dir = temp_data_dir / "tomic" / "data" / "spot_prices"
        iv_dir = temp_data_dir / "tomic" / "data" / "iv_daily_summary"

        # Only create spot prices file
        spot_file = spot_dir / "AAPL.json"
        spot_file.write_text(json.dumps([{"date": "2024-01-01", "close": 100}]))

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(iv_dir),
                "EARNINGS_DATES_FILE": str(temp_data_dir / "tomic" / "data" / "earnings_dates.json"),
            }.get(key, default),
        )

        result = symbol_service.validate_symbol_data("AAPL")

        assert result.has_spot_prices is True
        assert result.has_iv_summary is False
        assert result.is_complete is False
        assert "iv_summary" in result.missing_files


class TestSymbolServiceOrphanedData:
    """Tests for orphaned data detection."""

    def test_find_orphaned_data(self, symbol_service, temp_data_dir, monkeypatch):
        """Test finding orphaned data files."""
        spot_dir = temp_data_dir / "tomic" / "data" / "spot_prices"
        iv_dir = temp_data_dir / "tomic" / "data" / "iv_daily_summary"

        # Create files for configured and non-configured symbols
        (spot_dir / "AAPL.json").write_text("[]")
        (spot_dir / "ORPHAN1.json").write_text("[]")
        (iv_dir / "AAPL.json").write_text("[]")
        (iv_dir / "ORPHAN2.json").write_text("[]")

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "DEFAULT_SYMBOLS": ["AAPL"],
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(iv_dir),
            }.get(key, default),
        )

        orphaned = symbol_service.find_orphaned_data()

        assert "ORPHAN1" in orphaned
        assert "ORPHAN2" in orphaned
        assert "AAPL" not in orphaned

    def test_cleanup_orphaned_data(self, symbol_service, temp_data_dir, monkeypatch):
        """Test cleaning up orphaned data."""
        spot_dir = temp_data_dir / "tomic" / "data" / "spot_prices"

        orphan_file = spot_dir / "ORPHAN.json"
        orphan_file.write_text("[]")

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "DEFAULT_SYMBOLS": [],
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(temp_data_dir / "tomic" / "data" / "iv_daily_summary"),
            }.get(key, default),
        )

        deleted = symbol_service.cleanup_orphaned_data()

        assert "ORPHAN" in deleted
        assert not orphan_file.exists()


class TestSymbolServiceMetadata:
    """Tests for metadata management."""

    def test_load_save_metadata(self, symbol_service, temp_data_dir, monkeypatch):
        """Test loading and saving metadata."""
        data_dir = temp_data_dir / "tomic" / "data"
        meta_path = data_dir / "symbol_metadata.json"

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: default,
        )

        # Save metadata
        meta = SymbolMetadata(
            symbol="AAPL",
            sector="Technology",
            avg_atm_call_volume=100000,
        )
        symbol_service.update_symbol_metadata(meta)

        # Load and verify
        loaded = symbol_service.load_all_metadata()
        assert "AAPL" in loaded
        assert loaded["AAPL"].sector == "Technology"
        assert loaded["AAPL"].avg_atm_call_volume == 100000

    def test_get_symbol_metadata(self, symbol_service, temp_data_dir, monkeypatch):
        """Test getting metadata for single symbol."""
        data_dir = temp_data_dir / "tomic" / "data"
        meta_path = data_dir / "symbol_metadata.json"

        # Create test metadata file
        meta_path.write_text(json.dumps({
            "AAPL": {"sector": "Technology", "avg_atm_call_volume": 100000},
            "MSFT": {"sector": "Technology", "avg_atm_call_volume": 50000},
        }))

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: default,
        )

        meta = symbol_service.get_symbol_metadata("AAPL")

        assert meta is not None
        assert meta.symbol == "AAPL"
        assert meta.sector == "Technology"

    def test_get_symbol_metadata_not_found(self, symbol_service, temp_data_dir, monkeypatch):
        """Test getting metadata for non-existent symbol."""
        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: default,
        )

        meta = symbol_service.get_symbol_metadata("NOTFOUND")
        assert meta is None


class TestSymbolServiceBasketSummary:
    """Tests for basket summary."""

    def test_get_basket_summary(self, symbol_service, temp_data_dir, monkeypatch):
        """Test getting basket summary."""
        data_dir = temp_data_dir / "tomic" / "data"
        spot_dir = data_dir / "spot_prices"
        iv_dir = data_dir / "iv_daily_summary"
        meta_path = data_dir / "symbol_metadata.json"

        # Create data files
        (spot_dir / "AAPL.json").write_text(json.dumps([{"date": "2024-01-01", "close": 100}]))
        (iv_dir / "AAPL.json").write_text(json.dumps([{"date": "2024-01-01", "atm_iv": 0.25}]))
        (spot_dir / "MSFT.json").write_text(json.dumps([{"date": "2024-01-01", "close": 200}]))
        (iv_dir / "MSFT.json").write_text(json.dumps([{"date": "2024-01-01", "atm_iv": 0.20}]))

        # Create metadata
        meta_path.write_text(json.dumps({
            "AAPL": {"sector": "Technology", "avg_atm_call_volume": 100000, "avg_atm_call_oi": 500000},
            "MSFT": {"sector": "Technology", "avg_atm_call_volume": 50000, "avg_atm_call_oi": 300000},
        }))

        monkeypatch.setattr(
            "tomic.services.symbol_service.cfg_get",
            lambda key, default=None: {
                "DEFAULT_SYMBOLS": ["AAPL", "MSFT"],
                "PRICE_HISTORY_DIR": str(spot_dir),
                "IV_DAILY_SUMMARY_DIR": str(iv_dir),
                "EARNINGS_DATES_FILE": str(data_dir / "earnings_dates.json"),
            }.get(key, default),
        )

        summary = symbol_service.get_basket_summary()

        assert summary["total_symbols"] == 2
        assert summary["data_complete"] == 2
        assert "Technology" in summary["sectors"]
        assert summary["avg_volume"] == 75000  # (100000 + 50000) / 2
