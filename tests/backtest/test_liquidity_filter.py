"""Tests for liquidity filtering in backtesting."""

from datetime import date

import pytest

from tomic.backtest.config import LiquidityRulesConfig
from tomic.backtest.liquidity_filter import (
    LiquidityFilter,
    LiquidityMetrics,
    filter_by_liquidity,
    iron_condor_to_legs,
)
from tomic.backtest.option_chain_loader import OptionQuote, IronCondorQuotes
from tomic.strategy.reasons import ReasonCategory


def make_option_quote(
    strike: float,
    option_type: str,
    bid: float = 1.0,
    ask: float = 1.10,
    volume: int = 100,
    open_interest: int = 500,
) -> OptionQuote:
    """Helper to create a test OptionQuote."""
    mid = (bid + ask) / 2
    return OptionQuote(
        symbol="TEST",
        trade_date=date(2024, 1, 15),
        expiry=date(2024, 2, 16),
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        mid=mid,
        delta=0.20 if option_type == "C" else -0.20,
        iv=0.25,
        spot_price=100.0,
        volume=volume,
        open_interest=open_interest,
    )


def make_iron_condor(
    volume: int = 100,
    open_interest: int = 500,
    spread_pct: float = 10.0,
) -> IronCondorQuotes:
    """Helper to create a test IronCondorQuotes.

    Args:
        volume: Volume for all legs
        open_interest: Open interest for all legs
        spread_pct: Bid-ask spread percentage
    """
    # Calculate bid/ask from spread_pct
    mid = 1.00
    half_spread = (spread_pct / 100) * mid / 2
    bid = mid - half_spread
    ask = mid + half_spread

    return IronCondorQuotes(
        symbol="TEST",
        trade_date=date(2024, 1, 15),
        expiry=date(2024, 2, 16),
        spot_price=100.0,
        long_put=make_option_quote(90, "P", bid, ask, volume, open_interest),
        short_put=make_option_quote(95, "P", bid, ask, volume, open_interest),
        short_call=make_option_quote(105, "C", bid, ask, volume, open_interest),
        long_call=make_option_quote(110, "C", bid, ask, volume, open_interest),
    )


class TestOptionQuoteLiquidity:
    """Tests for OptionQuote liquidity properties."""

    def test_spread_calculation(self):
        """Test bid-ask spread calculation."""
        quote = make_option_quote(100, "C", bid=1.00, ask=1.20)
        assert quote.spread == pytest.approx(0.20)
        assert quote.spread_pct == pytest.approx(18.18, rel=0.01)  # 0.20 / 1.10 * 100

    def test_liquidity_score_high_liquidity(self):
        """Test liquidity score for highly liquid option."""
        quote = make_option_quote(
            100, "C",
            bid=1.00, ask=1.05,  # 5% spread
            volume=1000,
            open_interest=5000,
        )
        # Max score: 40 (volume) + 40 (OI) + 20 (spread) = 100
        assert quote.liquidity_score >= 90

    def test_liquidity_score_low_liquidity(self):
        """Test liquidity score for illiquid option."""
        quote = make_option_quote(
            100, "C",
            bid=0.80, ask=1.20,  # 40% spread
            volume=10,
            open_interest=50,
        )
        # Low score due to low volume/OI and wide spread
        assert quote.liquidity_score < 20

    def test_passes_liquidity_threshold_pass(self):
        """Test that liquid option passes threshold."""
        quote = make_option_quote(
            100, "C",
            bid=1.00, ask=1.10,
            volume=100,
            open_interest=500,
        )
        assert quote.passes_liquidity_threshold(
            min_volume=50,
            min_oi=200,
            max_spread_pct=15.0,
        )

    def test_passes_liquidity_threshold_fail_volume(self):
        """Test that low volume fails threshold."""
        quote = make_option_quote(100, "C", volume=5, open_interest=500)
        assert not quote.passes_liquidity_threshold(min_volume=10)

    def test_passes_liquidity_threshold_fail_oi(self):
        """Test that low OI fails threshold."""
        quote = make_option_quote(100, "C", volume=100, open_interest=50)
        assert not quote.passes_liquidity_threshold(min_oi=100)

    def test_passes_liquidity_threshold_fail_spread(self):
        """Test that wide spread fails threshold."""
        quote = make_option_quote(100, "C", bid=0.80, ask=1.20)  # 40% spread
        assert not quote.passes_liquidity_threshold(max_spread_pct=20.0)


class TestIronCondorQuotesLiquidity:
    """Tests for IronCondorQuotes liquidity methods."""

    def test_min_liquidity_score(self):
        """Test minimum liquidity score calculation."""
        ic = make_iron_condor(volume=100, open_interest=500)
        # All legs have same liquidity, so min = avg
        assert ic.min_liquidity_score > 0
        assert ic.min_liquidity_score == ic.avg_liquidity_score

    def test_min_volume(self):
        """Test minimum volume calculation."""
        ic = make_iron_condor(volume=100)
        assert ic.min_volume == 100

    def test_min_open_interest(self):
        """Test minimum open interest calculation."""
        ic = make_iron_condor(open_interest=500)
        assert ic.min_open_interest == 500

    def test_max_spread_pct(self):
        """Test maximum spread percentage calculation."""
        ic = make_iron_condor(spread_pct=10.0)
        assert ic.max_spread_pct == pytest.approx(10.0, rel=0.01)

    def test_passes_liquidity_check_pass(self):
        """Test that liquid iron condor passes check."""
        ic = make_iron_condor(volume=100, open_interest=500, spread_pct=10.0)
        passes, reasons = ic.passes_liquidity_check(
            min_volume=50,
            min_oi=200,
            max_spread_pct=15.0,
        )
        assert passes
        assert len(reasons) == 0

    def test_passes_liquidity_check_fail(self):
        """Test that illiquid iron condor fails check."""
        ic = make_iron_condor(volume=5, open_interest=50, spread_pct=25.0)
        passes, reasons = ic.passes_liquidity_check(
            min_volume=10,
            min_oi=100,
            max_spread_pct=20.0,
        )
        assert not passes
        assert len(reasons) > 0


class TestLiquidityFilter:
    """Tests for LiquidityFilter class."""

    def test_filter_mode_off(self):
        """Test that mode='off' always passes."""
        config = LiquidityRulesConfig(mode="off")
        filter_obj = LiquidityFilter(config)

        # Very illiquid iron condor
        ic = make_iron_condor(volume=0, open_interest=0, spread_pct=50.0)

        passes, reasons, metrics = filter_obj.filter_iron_condor(ic)
        assert passes
        assert len(reasons) == 0

    def test_filter_mode_hard_pass(self):
        """Test hard mode passes for liquid option."""
        config = LiquidityRulesConfig(
            mode="hard",
            min_option_volume=50,
            min_option_open_interest=200,
            max_spread_pct=15.0,
        )
        filter_obj = LiquidityFilter(config)

        ic = make_iron_condor(volume=100, open_interest=500, spread_pct=10.0)

        passes, reasons, metrics = filter_obj.filter_iron_condor(ic)
        assert passes
        assert len(reasons) == 0

    def test_filter_mode_hard_fail_volume(self):
        """Test hard mode rejects low volume."""
        config = LiquidityRulesConfig(
            mode="hard",
            min_option_volume=50,
        )
        filter_obj = LiquidityFilter(config)

        ic = make_iron_condor(volume=10)

        passes, reasons, metrics = filter_obj.filter_iron_condor(ic)
        assert not passes
        # Reasons are now ReasonDetail objects with LOW_LIQUIDITY category
        assert any(r.category == ReasonCategory.LOW_LIQUIDITY for r in reasons)

    def test_filter_mode_hard_fail_spread(self):
        """Test hard mode rejects wide spread."""
        config = LiquidityRulesConfig(
            mode="hard",
            max_spread_pct=15.0,
        )
        filter_obj = LiquidityFilter(config)

        ic = make_iron_condor(spread_pct=25.0)

        passes, reasons, metrics = filter_obj.filter_iron_condor(ic)
        assert not passes
        # Reasons are now ReasonDetail objects
        assert any("spread" in r.message.lower() for r in reasons)

    def test_filter_mode_soft(self):
        """Test soft mode passes but logs warnings."""
        config = LiquidityRulesConfig(
            mode="soft",
            min_option_volume=100,
        )
        filter_obj = LiquidityFilter(config)

        ic = make_iron_condor(volume=10)  # Below threshold

        passes, reasons, metrics = filter_obj.filter_iron_condor(ic)
        assert passes  # Soft mode always passes
        # Reasons are logged but trade is not rejected

    def test_calculate_signal_penalty_good_liquidity(self):
        """Test signal penalty for good liquidity."""
        config = LiquidityRulesConfig(
            min_option_volume=50,
            min_option_open_interest=200,
            max_spread_pct=15.0,
        )
        filter_obj = LiquidityFilter(config)

        metrics = LiquidityMetrics(
            min_volume=200,  # 2x threshold
            min_open_interest=800,  # 2x threshold
            max_spread_pct=5.0,  # Well below half threshold
            min_liquidity_score=80,
            avg_liquidity_score=85,
            total_spread_cost=10.0,
            realistic_entry_credit=100.0,
            mid_entry_credit=105.0,
            slippage_cost=5.0,
            low_volume_legs=[],
            high_spread_legs=[],
        )

        penalty = filter_obj.calculate_signal_penalty(metrics)
        assert penalty >= 0.9  # Good liquidity = minimal penalty

    def test_calculate_signal_penalty_poor_liquidity(self):
        """Test signal penalty for poor liquidity."""
        config = LiquidityRulesConfig(
            min_option_volume=50,
            min_option_open_interest=200,
            max_spread_pct=15.0,
        )
        filter_obj = LiquidityFilter(config)

        metrics = LiquidityMetrics(
            min_volume=10,  # Well below threshold
            min_open_interest=50,  # Well below threshold
            max_spread_pct=20.0,  # Above threshold
            min_liquidity_score=20,
            avg_liquidity_score=25,
            total_spread_cost=50.0,
            realistic_entry_credit=80.0,
            mid_entry_credit=100.0,
            slippage_cost=20.0,
            low_volume_legs=["all"],
            high_spread_legs=["all"],
        )

        penalty = filter_obj.calculate_signal_penalty(metrics)
        assert penalty < 0.5  # Poor liquidity = significant penalty


class TestFilterByLiquidity:
    """Tests for convenience function."""

    def test_filter_by_liquidity_pass(self):
        """Test convenience function passes."""
        config = LiquidityRulesConfig(
            mode="hard",
            min_option_volume=10,
        )
        ic = make_iron_condor(volume=100)

        passes, reasons = filter_by_liquidity(ic, config)
        assert passes

    def test_filter_by_liquidity_fail(self):
        """Test convenience function fails."""
        config = LiquidityRulesConfig(
            mode="hard",
            min_option_volume=100,
        )
        ic = make_iron_condor(volume=10)

        passes, reasons = filter_by_liquidity(ic, config)
        assert not passes
        assert len(reasons) > 0


class TestIronCondorToLegs:
    """Tests for iron_condor_to_legs conversion function."""

    def test_conversion(self):
        """Test conversion from IronCondorQuotes to leg dicts."""
        ic = make_iron_condor(volume=100, open_interest=500)
        legs = iron_condor_to_legs(ic)

        assert len(legs) == 4
        # Check that each leg has the expected fields
        for leg in legs:
            assert "strike" in leg
            assert "expiry" in leg
            assert "volume" in leg
            assert "open_interest" in leg
            assert leg["volume"] == 100
            assert leg["open_interest"] == 500


class TestLiquidityMetrics:
    """Tests for LiquidityMetrics dataclass."""

    def test_slippage_pct(self):
        """Test slippage percentage calculation."""
        metrics = LiquidityMetrics(
            min_volume=100,
            min_open_interest=500,
            max_spread_pct=10.0,
            min_liquidity_score=50,
            avg_liquidity_score=55,
            total_spread_cost=20.0,
            realistic_entry_credit=95.0,
            mid_entry_credit=100.0,
            slippage_cost=5.0,
            low_volume_legs=[],
            high_spread_legs=[],
        )

        assert metrics.slippage_pct == pytest.approx(5.0)

    def test_passes_basic_check_pass(self):
        """Test basic check passes."""
        metrics = LiquidityMetrics(
            min_volume=100,
            min_open_interest=500,
            max_spread_pct=10.0,
            min_liquidity_score=50,
            avg_liquidity_score=55,
            total_spread_cost=20.0,
            realistic_entry_credit=95.0,
            mid_entry_credit=100.0,
            slippage_cost=5.0,
            low_volume_legs=[],
            high_spread_legs=[],
        )

        assert metrics.passes_basic_check

    def test_passes_basic_check_fail(self):
        """Test basic check fails."""
        metrics = LiquidityMetrics(
            min_volume=0,
            min_open_interest=0,
            max_spread_pct=60.0,
            min_liquidity_score=0,
            avg_liquidity_score=0,
            total_spread_cost=100.0,
            realistic_entry_credit=None,
            mid_entry_credit=None,
            slippage_cost=None,
            low_volume_legs=["all"],
            high_spread_legs=["all"],
        )

        assert not metrics.passes_basic_check
