"""Tests for tomic.backtest.signal_generator module."""

from __future__ import annotations

import pytest
from datetime import date, timedelta

from tomic.backtest.config import BacktestConfig, EntryRulesConfig
from tomic.backtest.data_loader import IVTimeSeries
from tomic.backtest.results import IVDataPoint, EntrySignal
from tomic.backtest.signal_generator import (
    SignalGenerator,
    SignalFilter,
    CalendarSignalGenerator,
)


def make_iv_datapoint(
    symbol: str = "SPY",
    dt: date = date(2024, 6, 15),
    atm_iv: float = 0.25,
    iv_rank: float = 70.0,
    iv_percentile: float = 75.0,
    hv30: float = 0.18,
    skew: float = 5.0,
    term_m1_m2: float = 2.0,
    spot_price: float = 450.0,
) -> IVDataPoint:
    """Helper to create IVDataPoint for tests."""
    return IVDataPoint(
        date=dt,
        symbol=symbol,
        atm_iv=atm_iv,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv30=hv30,
        skew=skew,
        term_m1_m2=term_m1_m2,
        spot_price=spot_price,
    )


def make_iv_timeseries(symbol: str, data_points: list[IVDataPoint]) -> IVTimeSeries:
    """Helper to create IVTimeSeries for tests."""
    ts = IVTimeSeries(symbol=symbol)
    for dp in data_points:
        ts.add(dp)
    return ts


class TestSignalGenerator:
    """Tests for SignalGenerator class."""

    def test_creates_with_config(self):
        """Should initialize with BacktestConfig."""
        config = BacktestConfig()
        generator = SignalGenerator(config)

        assert generator.config == config
        assert generator.entry_rules == config.entry_rules

    def test_generates_signal_when_iv_above_threshold(self):
        """Should generate signal when IV percentile meets threshold."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(iv_percentile_min=60.0)
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=75.0, symbol="SPY")
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 1
        assert signals[0].symbol == "SPY"
        assert signals[0].iv_percentile_at_entry == 75.0

    def test_no_signal_when_iv_below_threshold(self):
        """Should not generate signal when IV percentile is below threshold."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(iv_percentile_min=60.0)
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=50.0)
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 0

    def test_skips_symbol_with_open_position(self):
        """Should skip symbols that already have open positions."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(iv_percentile_min=60.0)
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=75.0)
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={"SPY": True},
        )

        assert len(signals) == 0

    def test_skips_invalid_data_points(self):
        """Should skip data points that are not valid."""
        config = BacktestConfig()
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = IVDataPoint(
            date=trading_date,
            symbol="SPY",
            atm_iv=None,  # Invalid - missing required field
            iv_percentile=None,
        )
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 0

    def test_checks_iv_rank_when_configured(self):
        """Should filter by IV rank when iv_rank_min is set."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                iv_rank_min=50.0,
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=75.0, iv_rank=40.0)
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 0

    def test_checks_skew_range(self):
        """Should filter by skew range when configured."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                skew_min=2.0,
                skew_max=10.0,
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)

        # Test skew too low
        dp_low = make_iv_datapoint(iv_percentile=75.0, skew=1.0)
        ts_low = make_iv_timeseries("SPY", [dp_low])
        signals_low = generator.scan_for_signals(
            iv_data={"SPY": ts_low},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_low) == 0

        # Test skew too high
        dp_high = make_iv_datapoint(iv_percentile=75.0, skew=15.0)
        ts_high = make_iv_timeseries("SPY", [dp_high])
        signals_high = generator.scan_for_signals(
            iv_data={"SPY": ts_high},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_high) == 0

        # Test skew within range
        dp_ok = make_iv_datapoint(iv_percentile=75.0, skew=5.0)
        ts_ok = make_iv_timeseries("SPY", [dp_ok])
        signals_ok = generator.scan_for_signals(
            iv_data={"SPY": ts_ok},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_ok) == 1

    def test_checks_term_structure_range(self):
        """Should filter by term structure range when configured."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                term_structure_min=-5.0,
                term_structure_max=5.0,
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)

        # Test term structure outside range
        dp_outside = make_iv_datapoint(iv_percentile=75.0, term_m1_m2=10.0)
        ts_outside = make_iv_timeseries("SPY", [dp_outside])
        signals = generator.scan_for_signals(
            iv_data={"SPY": ts_outside},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals) == 0

    def test_checks_iv_hv_spread(self):
        """Should filter by IV-HV spread when configured."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                iv_hv_spread_min=0.05,  # 5% spread required
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)

        # IV-HV spread too small (0.25 - 0.23 = 0.02)
        dp_small = make_iv_datapoint(
            iv_percentile=75.0, atm_iv=0.25, hv30=0.23
        )
        ts_small = make_iv_timeseries("SPY", [dp_small])
        signals_small = generator.scan_for_signals(
            iv_data={"SPY": ts_small},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_small) == 0

        # IV-HV spread sufficient (0.25 - 0.18 = 0.07)
        dp_ok = make_iv_datapoint(
            iv_percentile=75.0, atm_iv=0.25, hv30=0.18
        )
        ts_ok = make_iv_timeseries("SPY", [dp_ok])
        signals_ok = generator.scan_for_signals(
            iv_data={"SPY": ts_ok},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_ok) == 1

    def test_rejects_entry_too_close_to_earnings(self):
        """Should reject entry when too close to earnings."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                min_days_until_earnings=7,
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=75.0)
        ts = make_iv_timeseries("SPY", [dp])

        # Earnings in 3 days - should reject
        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
            earnings_data={"SPY": date(2024, 6, 18)},
        )
        assert len(signals) == 0

        # Earnings in 10 days - should accept
        signals_ok = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
            earnings_data={"SPY": date(2024, 6, 25)},
        )
        assert len(signals_ok) == 1

    def test_allows_entry_when_no_earnings_data(self):
        """Should allow entry when earnings data is not available."""
        config = BacktestConfig(
            entry_rules=EntryRulesConfig(
                iv_percentile_min=60.0,
                min_days_until_earnings=7,
            )
        )
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=75.0)
        ts = make_iv_timeseries("SPY", [dp])

        # No earnings data - should allow
        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
            earnings_data={},
        )
        assert len(signals) == 1

    def test_calculates_signal_strength(self):
        """Should calculate signal strength score."""
        config = BacktestConfig()
        generator = SignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(
            iv_percentile=80.0,
            iv_rank=75.0,
            atm_iv=0.30,
            hv30=0.20,
        )
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 1
        assert signals[0].signal_strength > 0
        assert signals[0].signal_strength <= 100

    def test_get_signal_summary(self):
        """Should provide summary of signals by symbol."""
        config = BacktestConfig()
        generator = SignalGenerator(config)

        signals = [
            EntrySignal(
                date=date(2024, 6, 15),
                symbol="SPY",
                iv_at_entry=0.25,
                iv_rank_at_entry=70.0,
                iv_percentile_at_entry=75.0,
                hv_at_entry=0.18,
                skew_at_entry=5.0,
                term_at_entry=2.0,
                spot_at_entry=450.0,
                signal_strength=50.0,
            ),
            EntrySignal(
                date=date(2024, 6, 16),
                symbol="SPY",
                iv_at_entry=0.26,
                iv_rank_at_entry=72.0,
                iv_percentile_at_entry=76.0,
                hv_at_entry=0.18,
                skew_at_entry=5.0,
                term_at_entry=2.0,
                spot_at_entry=451.0,
                signal_strength=52.0,
            ),
            EntrySignal(
                date=date(2024, 6, 15),
                symbol="QQQ",
                iv_at_entry=0.28,
                iv_rank_at_entry=65.0,
                iv_percentile_at_entry=70.0,
                hv_at_entry=0.20,
                skew_at_entry=4.0,
                term_at_entry=1.5,
                spot_at_entry=380.0,
                signal_strength=48.0,
            ),
        ]

        summary = generator.get_signal_summary(signals)

        assert summary["SPY"] == 2
        assert summary["QQQ"] == 1


class TestSignalFilter:
    """Tests for SignalFilter class."""

    def _make_signal(self, symbol: str, strength: float) -> EntrySignal:
        """Helper to create EntrySignal."""
        return EntrySignal(
            date=date(2024, 6, 15),
            symbol=symbol,
            iv_at_entry=0.25,
            iv_rank_at_entry=70.0,
            iv_percentile_at_entry=75.0,
            hv_at_entry=0.18,
            skew_at_entry=5.0,
            term_at_entry=2.0,
            spot_at_entry=450.0,
            signal_strength=strength,
        )

    def test_filter_by_strength(self):
        """Should filter signals by minimum strength."""
        signals = [
            self._make_signal("SPY", 60.0),
            self._make_signal("QQQ", 40.0),
            self._make_signal("IWM", 55.0),
        ]

        filtered = SignalFilter.filter_by_strength(signals, min_strength=50.0)

        assert len(filtered) == 2
        symbols = [s.symbol for s in filtered]
        assert "SPY" in symbols
        assert "IWM" in symbols
        assert "QQQ" not in symbols

    def test_filter_by_symbol(self):
        """Should filter signals to specific symbols."""
        signals = [
            self._make_signal("SPY", 60.0),
            self._make_signal("QQQ", 40.0),
            self._make_signal("IWM", 55.0),
        ]

        filtered = SignalFilter.filter_by_symbol(signals, ["SPY", "IWM"])

        assert len(filtered) == 2
        symbols = [s.symbol for s in filtered]
        assert "SPY" in symbols
        assert "IWM" in symbols

    def test_rank_signals(self):
        """Should rank signals by strength (highest first)."""
        signals = [
            self._make_signal("SPY", 60.0),
            self._make_signal("QQQ", 80.0),
            self._make_signal("IWM", 70.0),
        ]

        ranked = SignalFilter.rank_signals(signals)

        assert ranked[0].symbol == "QQQ"
        assert ranked[1].symbol == "IWM"
        assert ranked[2].symbol == "SPY"

    def test_limit_signals(self):
        """Should limit to top N signals by strength."""
        signals = [
            self._make_signal("SPY", 60.0),
            self._make_signal("QQQ", 80.0),
            self._make_signal("IWM", 70.0),
            self._make_signal("AAPL", 50.0),
        ]

        limited = SignalFilter.limit_signals(signals, max_signals=2)

        assert len(limited) == 2
        symbols = [s.symbol for s in limited]
        assert "QQQ" in symbols
        assert "IWM" in symbols


class TestCalendarSignalGenerator:
    """Tests for CalendarSignalGenerator class."""

    def test_creates_with_config(self):
        """Should initialize with BacktestConfig."""
        config = BacktestConfig(strategy_type="calendar")
        generator = CalendarSignalGenerator(config)

        assert generator.config == config
        assert generator.entry_rules == config.entry_rules

    def test_generates_signal_when_iv_low(self):
        """Should generate signal when IV percentile is LOW (calendar entry)."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(
                iv_percentile_max=40.0,
            )
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(
            iv_percentile=30.0,  # Low IV - good for calendar
            term_m1_m2=2.0,     # Front > back (mispricing)
        )
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 1
        assert signals[0].symbol == "SPY"

    def test_no_signal_when_iv_high(self):
        """Should not generate signal when IV percentile is HIGH."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(
                iv_percentile_max=40.0,
            )
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(
            iv_percentile=75.0,  # High IV - bad for calendar
        )
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 0

    def test_checks_iv_rank_max(self):
        """Should filter by IV rank max for calendar."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(
                iv_percentile_max=40.0,
                iv_rank_max=40.0,
            )
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(
            iv_percentile=30.0,  # Low IV percentile - OK
            iv_rank=50.0,       # IV rank too high - reject
        )
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals) == 0

    def test_checks_term_structure_for_mispricing(self):
        """Should filter by term structure for mispricing signal."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(
                iv_percentile_max=40.0,
                term_structure_min=0.0,  # Front >= back required
            )
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)

        # Term structure negative (normal contango) - reject
        dp_reject = make_iv_datapoint(
            iv_percentile=30.0,
            term_m1_m2=-2.0,  # Back > front (normal)
        )
        ts_reject = make_iv_timeseries("SPY", [dp_reject])
        signals_reject = generator.scan_for_signals(
            iv_data={"SPY": ts_reject},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_reject) == 0

        # Term structure positive (mispricing) - accept
        dp_accept = make_iv_datapoint(
            iv_percentile=30.0,
            term_m1_m2=2.0,  # Front > back (mispricing)
        )
        ts_accept = make_iv_timeseries("SPY", [dp_accept])
        signals_accept = generator.scan_for_signals(
            iv_data={"SPY": ts_accept},
            trading_date=trading_date,
            open_positions={},
        )
        assert len(signals_accept) == 1

    def test_skips_symbol_with_open_position(self):
        """Should skip symbols that already have open positions."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(iv_percentile_max=40.0)
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=30.0)
        ts = make_iv_timeseries("SPY", [dp])

        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={"SPY": True},
        )

        assert len(signals) == 0

    def test_checks_earnings_constraint(self):
        """Should reject entry when too close to earnings."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(
                iv_percentile_max=40.0,
                min_days_until_earnings=7,
            )
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)
        dp = make_iv_datapoint(iv_percentile=30.0)
        ts = make_iv_timeseries("SPY", [dp])

        # Earnings in 3 days - reject
        signals = generator.scan_for_signals(
            iv_data={"SPY": ts},
            trading_date=trading_date,
            open_positions={},
            earnings_data={"SPY": date(2024, 6, 18)},
        )
        assert len(signals) == 0

    def test_calculates_calendar_signal_strength(self):
        """Should calculate signal strength with inverted logic for calendar."""
        config = BacktestConfig(
            strategy_type="calendar",
            entry_rules=EntryRulesConfig(iv_percentile_max=40.0)
        )
        generator = CalendarSignalGenerator(config)

        trading_date = date(2024, 6, 15)

        # Very low IV and good term structure = high strength
        dp_strong = make_iv_datapoint(
            iv_percentile=10.0,  # Very low IV
            iv_rank=15.0,       # Very low rank
            term_m1_m2=3.0,     # Strong mispricing
        )
        ts_strong = make_iv_timeseries("SPY", [dp_strong])
        signals_strong = generator.scan_for_signals(
            iv_data={"SPY": ts_strong},
            trading_date=trading_date,
            open_positions={},
        )

        # Borderline IV = lower strength
        dp_weak = make_iv_datapoint(
            iv_percentile=38.0,  # Near threshold
            iv_rank=35.0,       # Near threshold
            term_m1_m2=0.5,     # Weak mispricing
        )
        ts_weak = make_iv_timeseries("QQQ", [dp_weak])
        signals_weak = generator.scan_for_signals(
            iv_data={"QQQ": ts_weak},
            trading_date=trading_date,
            open_positions={},
        )

        assert len(signals_strong) == 1
        assert len(signals_weak) == 1
        # Lower IV should have higher signal strength for calendar
        assert signals_strong[0].signal_strength > signals_weak[0].signal_strength
