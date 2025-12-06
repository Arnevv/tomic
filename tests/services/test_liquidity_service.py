"""Tests for liquidity service."""

import pytest
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, patch

from tomic.services.liquidity_service import (
    LiquidityService,
    LiquidityMetrics,
)


class TestLiquidityMetrics:
    """Tests for LiquidityMetrics dataclass."""

    def test_total_avg_volume(self):
        """Test total average volume calculation."""
        metrics = LiquidityMetrics(
            symbol="AAPL",
            avg_atm_call_volume=100000,
            avg_atm_put_volume=80000,
        )
        assert metrics.total_avg_volume == 180000

    def test_total_avg_volume_none(self):
        """Test total average volume when no data."""
        metrics = LiquidityMetrics(symbol="AAPL")
        assert metrics.total_avg_volume is None

    def test_total_avg_volume_partial(self):
        """Test total average volume with partial data."""
        metrics = LiquidityMetrics(
            symbol="AAPL",
            avg_atm_call_volume=100000,
            avg_atm_put_volume=None,
        )
        assert metrics.total_avg_volume == 100000

    def test_total_avg_oi(self):
        """Test total average open interest calculation."""
        metrics = LiquidityMetrics(
            symbol="AAPL",
            avg_atm_call_oi=500000,
            avg_atm_put_oi=400000,
        )
        assert metrics.total_avg_oi == 900000

    def test_to_dict(self):
        """Test conversion to dictionary."""
        metrics = LiquidityMetrics(
            symbol="AAPL",
            avg_atm_call_volume=100000,
            avg_atm_call_oi=500000,
            days_analyzed=20,
            data_start=date(2024, 1, 1),
            data_end=date(2024, 1, 20),
        )
        result = metrics.to_dict()

        assert result["symbol"] == "AAPL"
        assert result["avg_atm_call_volume"] == 100000
        assert result["avg_atm_call_oi"] == 500000
        assert result["days_analyzed"] == 20
        assert result["data_start"] == "2024-01-01"
        assert result["data_end"] == "2024-01-20"


class TestLiquidityServiceInit:
    """Tests for LiquidityService initialization."""

    def test_init_default_cache_dir(self):
        """Test initialization with default cache directory."""
        service = LiquidityService()
        assert service.cache_dir is not None
        assert "orats_cache" in str(service.cache_dir)

    def test_init_custom_cache_dir(self, tmp_path):
        """Test initialization with custom cache directory."""
        service = LiquidityService(cache_dir=tmp_path)
        assert service.cache_dir == tmp_path


class TestLiquidityServiceAvailableDates:
    """Tests for available dates detection."""

    def test_get_available_dates_empty(self, tmp_path):
        """Test getting available dates with empty cache."""
        service = LiquidityService(cache_dir=tmp_path)
        dates = service._get_available_dates()
        assert dates == []

    def test_get_available_dates_with_files(self, tmp_path):
        """Test getting available dates with cache files."""
        # Create test directory structure
        year_dir = tmp_path / "2024"
        year_dir.mkdir()

        # Create test ZIP files
        (year_dir / "ORATS_SMV_Strikes_20240115.zip").touch()
        (year_dir / "ORATS_SMV_Strikes_20240116.zip").touch()

        service = LiquidityService(cache_dir=tmp_path)

        # Mock today's date to make test deterministic
        with patch("tomic.services.liquidity_service.date") as mock_date:
            mock_date.today.return_value = date(2024, 1, 20)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            dates = service._get_available_dates(lookback_days=30)

        assert len(dates) == 2
        assert date(2024, 1, 16) in dates
        assert date(2024, 1, 15) in dates


class TestLiquidityServiceFindATM:
    """Tests for ATM option finding."""

    def test_find_atm_options_with_valid_chain(self):
        """Test finding ATM options in valid chain."""
        service = LiquidityService()

        # Create mock chain with options
        mock_chain = MagicMock()
        mock_chain.spot_price = 150.0
        mock_chain.filter_by_dte_range.return_value = [
            MagicMock(option_type="C", strike=150.0, volume=1000, open_interest=5000),
            MagicMock(option_type="C", strike=155.0, volume=800, open_interest=4000),
            MagicMock(option_type="P", strike=150.0, volume=900, open_interest=4500),
            MagicMock(option_type="P", strike=145.0, volume=700, open_interest=3500),
        ]

        calls, puts = service._find_atm_options(mock_chain, (20, 60))

        assert len(calls) == 1
        assert len(puts) == 1
        assert calls[0].strike == 150.0
        assert puts[0].strike == 150.0

    def test_find_atm_options_no_spot(self):
        """Test finding ATM options with no spot price."""
        service = LiquidityService()

        mock_chain = MagicMock()
        mock_chain.spot_price = None

        calls, puts = service._find_atm_options(mock_chain, (20, 60))

        assert calls == []
        assert puts == []

    def test_find_atm_options_empty_chain(self):
        """Test finding ATM options in empty chain."""
        service = LiquidityService()

        mock_chain = MagicMock()
        mock_chain.spot_price = 150.0
        mock_chain.filter_by_dte_range.return_value = []

        calls, puts = service._find_atm_options(mock_chain, (20, 60))

        assert calls == []
        assert puts == []


class TestLiquidityServiceCalculation:
    """Tests for liquidity calculation."""

    def test_calculate_liquidity_no_data(self, tmp_path):
        """Test liquidity calculation with no data."""
        service = LiquidityService(cache_dir=tmp_path)

        metrics = service.calculate_liquidity("AAPL")

        assert metrics.symbol == "AAPL"
        assert metrics.days_analyzed == 0
        assert metrics.avg_atm_call_volume is None

    def test_calculate_liquidity_with_data(self, tmp_path):
        """Test liquidity calculation with mock data."""
        service = LiquidityService(cache_dir=tmp_path)

        # Create mock chain
        mock_chain = MagicMock()
        mock_chain.spot_price = 150.0
        mock_chain.options = [MagicMock()]
        mock_chain.filter_by_dte_range.return_value = [
            MagicMock(option_type="C", strike=150.0, volume=1000, open_interest=5000),
            MagicMock(option_type="P", strike=150.0, volume=900, open_interest=4500),
        ]

        # Mock the chain loader at the import location
        with patch("tomic.backtest.option_chain_loader.OptionChainLoader") as MockLoader:
            mock_loader = MagicMock()
            mock_loader.load_chain.return_value = mock_chain
            MockLoader.return_value = mock_loader

            # Mock available dates
            with patch.object(service, "_get_available_dates") as mock_dates:
                mock_dates.return_value = [date(2024, 1, 15), date(2024, 1, 16)]

                metrics = service.calculate_liquidity("AAPL")

        assert metrics.symbol == "AAPL"
        assert metrics.days_analyzed == 2
        assert metrics.avg_atm_call_volume == 1000
        assert metrics.avg_atm_put_volume == 900

    def test_calculate_liquidity_batch(self, tmp_path):
        """Test batch liquidity calculation."""
        service = LiquidityService(cache_dir=tmp_path)

        # Mock calculate_liquidity
        with patch.object(service, "calculate_liquidity") as mock_calc:
            mock_calc.return_value = LiquidityMetrics(
                symbol="TEST",
                avg_atm_call_volume=50000,
            )

            results = service.calculate_liquidity_batch(["AAPL", "MSFT"])

        assert len(results) == 2
        assert "AAPL" in results
        assert "MSFT" in results
        assert mock_calc.call_count == 2
