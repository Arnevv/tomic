"""Tests for symbol manager."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
from datetime import datetime

from tomic.services.symbol_manager import (
    SymbolManager,
    AddSymbolResult,
    RemoveSymbolResult,
    SIC_SECTOR_MAP,
    ETF_SECTORS,
)
from tomic.services.symbol_service import SymbolService, SymbolMetadata


@pytest.fixture
def mock_symbol_service():
    """Create mock symbol service."""
    service = MagicMock(spec=SymbolService)
    service.get_configured_symbols.return_value = ["AAPL", "MSFT"]
    service.add_to_config.return_value = []
    service.remove_from_config.return_value = []
    service.load_all_metadata.return_value = {}
    service.validate_symbol_data.return_value = MagicMock(
        status="complete",
        is_complete=True,
        has_spot_prices=True,
        has_iv_summary=True,
    )
    service.validate_all_symbols.return_value = {}
    return service


@pytest.fixture
def mock_liquidity_service():
    """Create mock liquidity service."""
    service = MagicMock()
    service.calculate_liquidity.return_value = MagicMock(
        avg_atm_call_volume=50000,
        avg_atm_call_oi=200000,
    )
    return service


@pytest.fixture
def symbol_manager(mock_symbol_service, mock_liquidity_service):
    """Create symbol manager with mocked services."""
    return SymbolManager(
        symbol_service=mock_symbol_service,
        liquidity_service=mock_liquidity_service,
    )


class TestSectorMapping:
    """Tests for SIC code to sector mapping."""

    def test_sic_sector_map_technology(self):
        """Test technology sector SIC codes."""
        assert SIC_SECTOR_MAP.get("73") == "Technology"
        assert SIC_SECTOR_MAP.get("35") == "Technology"
        assert SIC_SECTOR_MAP.get("36") == "Technology"

    def test_sic_sector_map_financials(self):
        """Test financials sector SIC codes."""
        assert SIC_SECTOR_MAP.get("60") == "Financials"
        assert SIC_SECTOR_MAP.get("62") == "Financials"

    def test_sic_sector_map_healthcare(self):
        """Test healthcare sector SIC codes."""
        assert SIC_SECTOR_MAP.get("28") == "Healthcare"
        assert SIC_SECTOR_MAP.get("80") == "Healthcare"

    def test_etf_sectors(self):
        """Test ETF sector mappings."""
        assert ETF_SECTORS.get("SPY") == "ETF - Index"
        assert ETF_SECTORS.get("QQQ") == "ETF - Index"
        assert ETF_SECTORS.get("XLF") == "ETF - Financials"
        assert ETF_SECTORS.get("XLK") == "ETF - Technology"


class TestSymbolManagerSectorClassification:
    """Tests for sector classification."""

    def test_map_sic_to_sector_known(self, symbol_manager):
        """Test mapping known SIC codes."""
        assert symbol_manager._map_sic_to_sector("7370") == "Technology"
        assert symbol_manager._map_sic_to_sector("6020") == "Financials"
        assert symbol_manager._map_sic_to_sector("2834") == "Healthcare"

    def test_map_sic_to_sector_unknown(self, symbol_manager):
        """Test mapping unknown SIC codes."""
        assert symbol_manager._map_sic_to_sector("9999") == "Unknown"
        assert symbol_manager._map_sic_to_sector(None) == "Unknown"
        assert symbol_manager._map_sic_to_sector("") == "Unknown"

    def test_get_sector_for_etf(self, symbol_manager):
        """Test sector classification for known ETFs."""
        assert symbol_manager._get_sector_for_symbol("SPY", {}) == "ETF - Index"
        assert symbol_manager._get_sector_for_symbol("XLF", {}) == "ETF - Financials"

    def test_get_sector_for_stock_with_sic(self, symbol_manager):
        """Test sector classification using SIC code."""
        details = {"sic_code": "7370"}
        assert symbol_manager._get_sector_for_symbol("AAPL", details) == "Technology"

    def test_get_sector_for_stock_no_sic(self, symbol_manager):
        """Test sector classification without SIC code."""
        details = {"sic_description": "software development services"}
        assert symbol_manager._get_sector_for_symbol("TEST", details) == "Technology"

    def test_get_sector_for_etf_type(self, symbol_manager):
        """Test sector classification for ETF type."""
        details = {"type": "ETF"}
        assert symbol_manager._get_sector_for_symbol("UNKNOWN", details) == "ETF - Other"


class TestSymbolManagerAddSymbols:
    """Tests for adding symbols."""

    def test_add_symbols_already_exists(self, symbol_manager, mock_symbol_service):
        """Test adding symbols that already exist."""
        mock_symbol_service.add_to_config.return_value = []

        results = symbol_manager.add_symbols(["AAPL"])

        assert len(results) == 1
        assert results[0].symbol == "AAPL"
        assert results[0].success is True
        assert results[0].message == "Already in basket"

    def test_add_symbols_new(self, symbol_manager, mock_symbol_service):
        """Test adding new symbols."""
        mock_symbol_service.add_to_config.return_value = ["GOOGL"]

        # Mock Polygon client
        with patch.object(symbol_manager, "_get_polygon_client") as mock_client:
            mock_polygon = MagicMock()
            mock_polygon.fetch_ticker_details.return_value = {
                "symbol": "GOOGL",
                "sic_code": "7370",
                "sic_description": "Computer programming services",
                "market_cap": 1500000000000,
            }
            mock_client.return_value = mock_polygon

            results = symbol_manager.add_symbols(
                ["GOOGL"],
                fetch_data=False,  # Skip data fetch in test
                fetch_sector=True,
                fetch_liquidity=True,
            )

        assert len(results) == 1
        assert results[0].symbol == "GOOGL"
        assert results[0].success is True
        assert results[0].metadata is not None
        assert results[0].metadata.sector == "Technology"

    def test_add_symbols_with_progress_callback(self, symbol_manager, mock_symbol_service):
        """Test add symbols with progress callback."""
        mock_symbol_service.add_to_config.return_value = ["TEST"]
        progress_calls = []

        def progress(symbol, status):
            progress_calls.append((symbol, status))

        with patch.object(symbol_manager, "_get_polygon_client") as mock_client:
            mock_polygon = MagicMock()
            mock_polygon.fetch_ticker_details.return_value = {"symbol": "TEST"}
            mock_client.return_value = mock_polygon

            symbol_manager.add_symbols(
                ["TEST"],
                fetch_data=False,
                fetch_sector=True,
                fetch_liquidity=True,
                progress_callback=progress,
            )

        assert len(progress_calls) > 0
        assert any("TEST" in call[0] for call in progress_calls)


class TestSymbolManagerRemoveSymbols:
    """Tests for removing symbols."""

    def test_remove_symbols_exists(self, symbol_manager, mock_symbol_service):
        """Test removing existing symbols."""
        mock_symbol_service.remove_from_config.return_value = ["AAPL"]
        mock_symbol_service.delete_symbol_data.return_value = ["/path/AAPL.json"]

        results = symbol_manager.remove_symbols(["AAPL"])

        assert len(results) == 1
        assert results[0].symbol == "AAPL"
        assert results[0].success is True
        assert len(results[0].files_deleted) == 1

    def test_remove_symbols_not_exists(self, symbol_manager, mock_symbol_service):
        """Test removing non-existing symbols."""
        mock_symbol_service.remove_from_config.return_value = []

        results = symbol_manager.remove_symbols(["NOTEXIST"])

        assert len(results) == 1
        assert results[0].symbol == "NOTEXIST"
        assert results[0].success is False
        assert results[0].message == "Not in basket"

    def test_remove_symbols_without_delete_data(self, symbol_manager, mock_symbol_service):
        """Test removing symbols without deleting data."""
        mock_symbol_service.remove_from_config.return_value = ["AAPL"]

        results = symbol_manager.remove_symbols(["AAPL"], delete_data=False)

        assert len(results) == 1
        assert results[0].success is True
        mock_symbol_service.delete_symbol_data.assert_not_called()


class TestSymbolManagerBasketAnalysis:
    """Tests for basket analysis."""

    def test_get_basket_overview(self, symbol_manager, mock_symbol_service):
        """Test getting basket overview."""
        mock_symbol_service.get_configured_symbols.return_value = ["AAPL", "MSFT"]
        mock_symbol_service.load_all_metadata.return_value = {
            "AAPL": SymbolMetadata(
                symbol="AAPL",
                sector="Technology",
                avg_atm_call_volume=100000,
                avg_atm_call_oi=500000,
            ),
            "MSFT": SymbolMetadata(
                symbol="MSFT",
                sector="Technology",
                avg_atm_call_volume=50000,
                avg_atm_call_oi=300000,
            ),
        }
        mock_symbol_service.validate_all_symbols.return_value = {
            "AAPL": MagicMock(status="complete", spot_price_days=100, iv_summary_days=100),
            "MSFT": MagicMock(status="complete", spot_price_days=100, iv_summary_days=100),
        }

        overview = symbol_manager.get_basket_overview()

        assert overview["total_symbols"] == 2
        assert len(overview["symbols"]) == 2
        assert "Technology" in overview["sectors"]
        assert overview["sectors"]["Technology"]["count"] == 2

    def test_get_sector_analysis(self, symbol_manager, mock_symbol_service):
        """Test sector analysis."""
        mock_symbol_service.get_configured_symbols.return_value = ["AAPL", "MSFT", "JPM"]
        mock_symbol_service.load_all_metadata.return_value = {
            "AAPL": SymbolMetadata(symbol="AAPL", sector="Technology"),
            "MSFT": SymbolMetadata(symbol="MSFT", sector="Technology"),
            "JPM": SymbolMetadata(symbol="JPM", sector="Financials"),
        }
        mock_symbol_service.validate_all_symbols.return_value = {
            "AAPL": MagicMock(status="complete"),
            "MSFT": MagicMock(status="complete"),
            "JPM": MagicMock(status="complete"),
        }

        analysis = symbol_manager.get_sector_analysis()

        assert "Technology" in analysis["sectors"]
        assert analysis["sectors"]["Technology"]["count"] == 2
        assert round(analysis["sectors"]["Technology"]["percentage"], 1) == 66.7

    def test_get_liquidity_warnings(self, symbol_manager, mock_symbol_service):
        """Test liquidity warnings."""
        mock_symbol_service.get_configured_symbols.return_value = ["AAPL", "LOW"]
        mock_symbol_service.load_all_metadata.return_value = {
            "AAPL": SymbolMetadata(symbol="AAPL", avg_atm_call_volume=100000),
            "LOW": SymbolMetadata(symbol="LOW", avg_atm_call_volume=5000),
        }
        mock_symbol_service.validate_all_symbols.return_value = {
            "AAPL": MagicMock(status="complete"),
            "LOW": MagicMock(status="complete"),
        }

        warnings = symbol_manager.get_liquidity_warnings(min_volume=10000)

        assert len(warnings) == 1
        assert warnings[0]["symbol"] == "LOW"
        assert warnings[0]["avg_volume"] == 5000


class TestSymbolManagerSync:
    """Tests for metadata sync."""

    def test_sync_metadata(self, symbol_manager, mock_symbol_service, monkeypatch):
        """Test syncing metadata."""
        mock_symbol_service.get_configured_symbols.return_value = ["AAPL"]
        mock_symbol_service.get_symbol_metadata.return_value = SymbolMetadata(symbol="AAPL")

        # Mock sleep to speed up test
        monkeypatch.setattr("tomic.services.symbol_manager.time.sleep", lambda x: None)
        monkeypatch.setattr(
            "tomic.services.symbol_manager.cfg_get",
            lambda key, default=None: 0 if key == "POLYGON_SLEEP_BETWEEN" else default,
        )

        with patch.object(symbol_manager, "_get_polygon_client") as mock_client:
            mock_polygon = MagicMock()
            mock_polygon.fetch_ticker_details.return_value = {
                "symbol": "AAPL",
                "sic_code": "7370",
            }
            mock_client.return_value = mock_polygon

            results = symbol_manager.sync_metadata(
                refresh_sector=True,
                refresh_liquidity=False,
            )

        assert "AAPL" in results
        assert results["AAPL"].sector == "Technology"
        mock_symbol_service.update_symbol_metadata.assert_called()


class TestAddRemoveSymbolResults:
    """Tests for result dataclasses."""

    def test_add_symbol_result(self):
        """Test AddSymbolResult dataclass."""
        result = AddSymbolResult(
            symbol="AAPL",
            success=True,
            message="Added",
            metadata=SymbolMetadata(symbol="AAPL"),
        )
        assert result.symbol == "AAPL"
        assert result.success is True

    def test_remove_symbol_result(self):
        """Test RemoveSymbolResult dataclass."""
        result = RemoveSymbolResult(
            symbol="AAPL",
            success=True,
            message="Removed",
            files_deleted=["/path/AAPL.json"],
        )
        assert result.symbol == "AAPL"
        assert len(result.files_deleted) == 1

    def test_remove_symbol_result_default_files(self):
        """Test RemoveSymbolResult with default files_deleted."""
        result = RemoveSymbolResult(
            symbol="AAPL",
            success=True,
            message="Removed",
        )
        assert result.files_deleted == []
