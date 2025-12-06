"""Tests for liquidity service."""

import pytest
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, patch
import zipfile
import io

from tomic.services.liquidity_service import (
    LiquidityService,
    LiquidityMetrics,
    _process_date_for_atm,
    _safe_float,
    _safe_int,
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


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_safe_float_valid(self):
        """Test safe_float with valid input."""
        assert _safe_float("123.45") == 123.45
        assert _safe_float("0") == 0.0

    def test_safe_float_invalid(self):
        """Test safe_float with invalid input."""
        assert _safe_float(None) is None
        assert _safe_float("") is None
        assert _safe_float("null") is None
        assert _safe_float("invalid") is None

    def test_safe_int_valid(self):
        """Test safe_int with valid input."""
        assert _safe_int("123") == 123
        assert _safe_int("123.7") == 123  # Truncates

    def test_safe_int_invalid(self):
        """Test safe_int with invalid input."""
        assert _safe_int(None) is None
        assert _safe_int("") is None
        assert _safe_int("null") is None
        assert _safe_int("invalid") is None


class TestProcessDateForATM:
    """Tests for _process_date_for_atm function."""

    def _create_mock_orats_zip(self, tmp_path, trade_date, rows):
        """Create a mock ORATS ZIP file with test data."""
        year = trade_date.strftime("%Y")
        date_str = trade_date.strftime("%Y%m%d")

        year_dir = tmp_path / year
        year_dir.mkdir(exist_ok=True)

        zip_path = year_dir / f"ORATS_SMV_Strikes_{date_str}.zip"

        # Create CSV content
        header = "ticker,stkPx,expirDate,strike,cVolu,cOi,pVolu,pOi,cMidIv,pMidIv"
        csv_lines = [header] + rows

        csv_content = "\n".join(csv_lines)

        # Create ZIP with CSV
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(f"ORATS_SMV_Strikes_{date_str}.csv", csv_content)

        return zip_path

    def test_process_date_empty_cache(self, tmp_path):
        """Test processing with no data file."""
        result = _process_date_for_atm(tmp_path, date(2024, 1, 15))
        assert result == {}

    def test_process_date_single_symbol(self, tmp_path):
        """Test processing a single symbol from ORATS data."""
        trade_date = date(2024, 1, 15)
        expiry_date = date(2024, 2, 15)  # 31 DTE, within range

        # AAPL at $150, ATM strike at $150 (within 2%)
        rows = [
            f"AAPL,150.0,{expiry_date},150,1000,5000,900,4500,0.25,0.26",
        ]

        self._create_mock_orats_zip(tmp_path, trade_date, rows)

        result = _process_date_for_atm(tmp_path, trade_date)

        assert "AAPL" in result
        assert result["AAPL"]["call_volume"] == 1000
        assert result["AAPL"]["call_oi"] == 5000
        assert result["AAPL"]["put_volume"] == 900
        assert result["AAPL"]["put_oi"] == 4500

    def test_process_date_multiple_symbols(self, tmp_path):
        """Test processing multiple symbols from ORATS data."""
        trade_date = date(2024, 1, 15)
        expiry_date = date(2024, 2, 15)

        rows = [
            f"AAPL,150.0,{expiry_date},150,1000,5000,900,4500,0.25,0.26",
            f"MSFT,400.0,{expiry_date},400,800,4000,700,3500,0.22,0.23",
            f"GOOGL,140.0,{expiry_date},140,600,3000,500,2500,0.28,0.29",
        ]

        self._create_mock_orats_zip(tmp_path, trade_date, rows)

        result = _process_date_for_atm(tmp_path, trade_date)

        assert len(result) == 3
        assert "AAPL" in result
        assert "MSFT" in result
        assert "GOOGL" in result

    def test_process_date_filters_out_of_dte_range(self, tmp_path):
        """Test that options outside DTE range are filtered."""
        trade_date = date(2024, 1, 15)
        near_expiry = date(2024, 1, 20)  # 5 DTE, below min range (20)
        far_expiry = date(2024, 6, 15)  # ~150 DTE, above max range (60)

        rows = [
            f"AAPL,150.0,{near_expiry},150,1000,5000,900,4500,0.25,0.26",
            f"MSFT,400.0,{far_expiry},400,800,4000,700,3500,0.22,0.23",
        ]

        self._create_mock_orats_zip(tmp_path, trade_date, rows)

        result = _process_date_for_atm(tmp_path, trade_date)

        # Both should be filtered out
        assert len(result) == 0

    def test_process_date_filters_non_atm(self, tmp_path):
        """Test that non-ATM options are filtered out."""
        trade_date = date(2024, 1, 15)
        expiry_date = date(2024, 2, 15)

        # AAPL at $150, but strike at $200 (>2% from spot)
        rows = [
            f"AAPL,150.0,{expiry_date},200,1000,5000,900,4500,0.25,0.26",
        ]

        self._create_mock_orats_zip(tmp_path, trade_date, rows)

        result = _process_date_for_atm(tmp_path, trade_date)

        # Should be filtered out as non-ATM
        assert len(result) == 0

    def test_process_date_aggregates_multiple_strikes(self, tmp_path):
        """Test that multiple ATM strikes for same symbol are aggregated."""
        trade_date = date(2024, 1, 15)
        expiry_date = date(2024, 2, 15)

        # AAPL at $150 with two ATM strikes (both within 2%)
        rows = [
            f"AAPL,150.0,{expiry_date},149,500,2500,450,2000,0.25,0.26",
            f"AAPL,150.0,{expiry_date},150,600,3000,500,2500,0.25,0.26",
            f"AAPL,150.0,{expiry_date},151,400,2000,350,1500,0.25,0.26",
        ]

        self._create_mock_orats_zip(tmp_path, trade_date, rows)

        result = _process_date_for_atm(tmp_path, trade_date)

        assert "AAPL" in result
        # Should aggregate all three strikes
        assert result["AAPL"]["call_volume"] == 500 + 600 + 400
        assert result["AAPL"]["put_volume"] == 450 + 500 + 350


class TestOptimizedOverview:
    """Tests for the optimized symbol overview method."""

    def test_get_all_symbols_overview_optimized_empty(self, tmp_path):
        """Test optimized overview with empty cache."""
        service = LiquidityService(cache_dir=tmp_path)
        results = service.get_all_symbols_overview_optimized(lookback_days=30)
        assert results == []

    def test_get_all_symbols_overview_optimized_with_data(self, tmp_path):
        """Test optimized overview with mock data."""
        service = LiquidityService(cache_dir=tmp_path)

        # Mock _get_available_dates and _process_date_for_atm
        with patch.object(service, "_get_available_dates") as mock_dates:
            mock_dates.return_value = [date(2024, 1, 15), date(2024, 1, 16)]

            with patch(
                "tomic.services.liquidity_service._process_date_for_atm"
            ) as mock_process:
                # Return mock data for each date
                mock_process.side_effect = [
                    # Day 1
                    {
                        "AAPL": {"call_volume": 1000, "call_oi": 5000, "put_volume": 900, "put_oi": 4500},
                        "MSFT": {"call_volume": 800, "call_oi": 4000, "put_volume": 700, "put_oi": 3500},
                    },
                    # Day 2
                    {
                        "AAPL": {"call_volume": 1200, "call_oi": 5500, "put_volume": 1100, "put_oi": 5000},
                        "MSFT": {"call_volume": 900, "call_oi": 4200, "put_volume": 800, "put_oi": 3700},
                    },
                ]

                results = service.get_all_symbols_overview_optimized(
                    lookback_days=30, max_workers=1, use_threads=True
                )

        assert len(results) == 2

        # Results should be sorted by volume descending
        # AAPL avg: (1000+900+1200+1100)/2 = 2100 total
        # MSFT avg: (800+700+900+800)/2 = 1600 total
        assert results[0]["symbol"] == "AAPL"
        assert results[1]["symbol"] == "MSFT"

        # Check averaging
        assert results[0]["days_analyzed"] == 2
        assert results[1]["days_analyzed"] == 2
