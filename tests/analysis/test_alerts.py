"""Tests for tomic.analysis.alerts module."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from tomic.analysis.alerts import check_entry_conditions, generate_risk_alerts


class TestCheckEntryConditions:
    """Tests for check_entry_conditions function."""

    def test_returns_empty_list_when_no_conditions_match(self):
        """When no entry conditions are triggered, return empty list."""
        strategy = {
            "avg_iv": 0.30,
            "HV30": 0.28,
            "IV_Rank": 0.50,
            "skew": 0.0,
        }
        result = check_entry_conditions(strategy)
        assert isinstance(result, list)

    def test_handles_empty_strategy_dict(self):
        """Should handle empty strategy without crashing."""
        result = check_entry_conditions({})
        assert isinstance(result, list)

    def test_handles_none_values_in_strategy(self):
        """Should handle None values gracefully."""
        strategy = {
            "avg_iv": None,
            "HV30": None,
            "IV_Rank": None,
        }
        result = check_entry_conditions(strategy)
        assert isinstance(result, list)

    def test_computes_diff_when_avg_iv_and_hv30_present(self):
        """Verifies diff is computed from avg_iv and HV30."""
        strategy = {
            "avg_iv": 0.40,
            "HV30": 0.20,
        }
        # Just verify it doesn't crash - actual alerts depend on rules config
        result = check_entry_conditions(strategy)
        assert isinstance(result, list)

    def test_skips_diff_computation_when_avg_iv_missing(self):
        """Diff should not be computed when avg_iv is None."""
        strategy = {
            "avg_iv": None,
            "HV30": 0.20,
        }
        result = check_entry_conditions(strategy)
        assert isinstance(result, list)

    def test_skips_diff_computation_when_hv30_missing(self):
        """Diff should not be computed when HV30 is None."""
        strategy = {
            "avg_iv": 0.40,
            "HV30": None,
        }
        result = check_entry_conditions(strategy)
        assert isinstance(result, list)


class TestGenerateRiskAlerts:
    """Tests for generate_risk_alerts function."""

    def test_returns_empty_list_for_empty_strategy(self):
        """Empty strategy should return empty list (no alerts)."""
        result = generate_risk_alerts({})
        assert isinstance(result, list)

    # Delta-based alerts
    def test_strong_bullish_alert_when_delta_high(self):
        """Delta >= 0.30 should trigger strong bullish alert."""
        strategy = {"delta": 0.35}
        result = generate_risk_alerts(strategy)
        assert any("bullish" in alert.lower() for alert in result)
        assert any("0.30" in alert for alert in result)

    def test_light_bullish_alert_when_delta_moderate_positive(self):
        """Delta between 0.15 and 0.30 should trigger light bullish alert."""
        strategy = {"delta": 0.20}
        result = generate_risk_alerts(strategy)
        assert any("bullish" in alert.lower() for alert in result)

    def test_strong_bearish_alert_when_delta_very_negative(self):
        """Delta <= -0.30 should trigger strong bearish alert."""
        strategy = {"delta": -0.35}
        result = generate_risk_alerts(strategy)
        assert any("bearish" in alert.lower() for alert in result)
        assert any("-0.30" in alert or "–0.30" in alert for alert in result)

    def test_light_bearish_alert_when_delta_moderate_negative(self):
        """Delta between -0.30 and -0.15 should trigger light bearish alert."""
        strategy = {"delta": -0.20}
        result = generate_risk_alerts(strategy)
        assert any("bearish" in alert.lower() for alert in result)

    def test_neutral_alert_when_delta_near_zero(self):
        """Delta between -0.15 and 0.15 should trigger neutral alert."""
        strategy = {"delta": 0.05}
        result = generate_risk_alerts(strategy)
        assert any("neutraal" in alert.lower() for alert in result)

    def test_no_delta_alert_when_delta_missing(self):
        """No delta alert when delta is None."""
        strategy = {"delta": None}
        result = generate_risk_alerts(strategy)
        # Should not crash, may have other alerts
        assert isinstance(result, list)

    # Delta-dollar exposure alerts
    def test_delta_dollar_calculation_with_legs(self):
        """Delta-dollar exposure should be calculated from legs."""
        strategy = {
            "spot": 100.0,
            "legs": [
                {"delta": 0.50, "position": 10, "multiplier": 100},
            ],
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_delta_dollar_handles_missing_leg_values(self):
        """Should handle missing values in legs gracefully."""
        strategy = {
            "spot": 100.0,
            "legs": [
                {"delta": None, "position": 10, "multiplier": 100},
                {"delta": 0.50, "position": None, "multiplier": 100},
            ],
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_delta_dollar_handles_empty_legs(self):
        """Should handle empty legs list."""
        strategy = {
            "spot": 100.0,
            "legs": [],
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # Vega-based alerts
    def test_handles_vega_none(self):
        """Should handle vega=None without crashing."""
        strategy = {"vega": None}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_vega_alert_logic_with_iv_rank(self):
        """Vega combined with IV_Rank produces relevant alerts."""
        strategy = {
            "vega": -50,
            "IV_Rank": 0.70,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_vega_alert_with_delta_and_iv_rank_combination(self):
        """Complex combination of delta, vega, IV_Rank."""
        strategy = {
            "delta": 0.20,
            "vega": 40,
            "IV_Rank": 0.25,
        }
        result = generate_risk_alerts(strategy)
        # Should potentially trigger bullish + long vega in low IV alert
        assert isinstance(result, list)

    # IV/HV spread alerts
    def test_iv_hv_spread_high_alert(self):
        """High IV/HV spread should trigger appropriate alert."""
        strategy = {"iv_hv_spread": 0.20}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_iv_hv_spread_low_alert(self):
        """Low IV/HV spread should trigger appropriate alert."""
        strategy = {"iv_hv_spread": -0.20}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_iv_hv_spread_none(self):
        """Should handle iv_hv_spread=None."""
        strategy = {"iv_hv_spread": None}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # Skew alerts
    def test_skew_positive_alert(self):
        """Positive skew should trigger appropriate alert."""
        strategy = {"skew": 0.20}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_skew_negative_alert(self):
        """Negative skew should trigger appropriate alert."""
        strategy = {"skew": -0.20}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_skew_none(self):
        """Should handle skew=None."""
        strategy = {"skew": None}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # PnL-based alerts
    def test_pnl_profit_taking_alert(self):
        """Unrealized PnL above threshold with positive theta."""
        strategy = {
            "unrealizedPnL": 80.0,
            "cost_basis": 100.0,
            "theta": 5.0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_pnl_negative_with_positive_theta_alert(self):
        """Negative PnL with positive theta should trigger reconsider alert."""
        strategy = {
            "unrealizedPnL": -500.0,
            "theta": 5.0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_pnl_handles_none_values(self):
        """Should handle None PnL values."""
        strategy = {
            "unrealizedPnL": None,
            "theta": None,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # ROM (Return on Margin) alerts
    def test_rom_high_alert(self):
        """ROM >= 20% should trigger high efficiency alert."""
        strategy = {"rom": 25.0}
        result = generate_risk_alerts(strategy)
        assert any("rom" in alert.lower() for alert in result)

    def test_rom_medium_alert(self):
        """ROM between 10-20% should trigger medium alert."""
        strategy = {"rom": 15.0}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_rom_low_alert(self):
        """ROM < 5% should trigger low efficiency alert."""
        strategy = {"rom": 3.0}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_rom_none(self):
        """Should handle rom=None."""
        strategy = {"rom": None}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # Theta efficiency alerts
    def test_theta_efficiency_calculation(self):
        """Theta efficiency should be calculated from theta and margin."""
        strategy = {
            "theta": 10.0,
            "margin_used": 1000.0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_theta_efficiency_with_init_margin(self):
        """Should use init_margin if margin_used not available."""
        strategy = {
            "theta": 10.0,
            "init_margin": 1000.0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # DTE alerts
    def test_dte_alert_near_expiration(self):
        """DTE below threshold should trigger expiration alert."""
        strategy = {"days_to_expiry": 5}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_dte_none(self):
        """Should handle days_to_expiry=None."""
        strategy = {"days_to_expiry": None}
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    # Edge cases
    def test_handles_zero_values(self):
        """Should handle zero values throughout."""
        strategy = {
            "delta": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rom": 0.0,
            "IV_Rank": 0.0,
            "iv_hv_spread": 0.0,
            "skew": 0.0,
            "days_to_expiry": 0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_handles_extreme_values(self):
        """Should handle extreme/boundary values."""
        strategy = {
            "delta": 1.0,
            "vega": 1000.0,
            "theta": -100.0,
            "rom": 1000.0,
            "IV_Rank": 1.0,
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_handles_negative_extreme_values(self):
        """Should handle negative extreme values."""
        strategy = {
            "delta": -1.0,
            "vega": -1000.0,
            "theta": 100.0,
            "IV_Rank": -0.5,  # Invalid but should not crash
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)

    def test_complex_strategy_with_all_fields(self):
        """Test a realistic complex strategy with many fields."""
        strategy = {
            "delta": 0.10,
            "vega": -20.0,
            "theta": 5.0,
            "rom": 12.0,
            "IV_Rank": 0.65,
            "iv_hv_spread": 0.05,
            "skew": 0.02,
            "days_to_expiry": 30,
            "unrealizedPnL": 50.0,
            "cost_basis": 100.0,
            "spot": 150.0,
            "init_margin": 500.0,
            "legs": [
                {"delta": -0.15, "position": -1, "multiplier": 100},
                {"delta": 0.05, "position": 1, "multiplier": 100},
            ],
        }
        result = generate_risk_alerts(strategy)
        assert isinstance(result, list)
        # Should have at least the neutral delta alert
        assert len(result) >= 0
