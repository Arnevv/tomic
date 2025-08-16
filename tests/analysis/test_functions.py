from tomic.analysis.entry_checks import check_entry_conditions
from tomic.analysis.strategy import determine_strategy_type
from tomic.analysis.strategy import collapse_legs
from tomic.analysis.performance_analyzer import compute_pnl


class TestComputePnl:
    def test_resultaat_key(self):
        trade = {"Resultaat": "12.5"}
        assert compute_pnl(trade) == 12.5

    def test_entry_exit(self):
        trade = {"EntryPrice": 5, "ExitPrice": 3}
        assert compute_pnl(trade) == 200

    def test_premium_exit(self):
        trade = {"Premium": 2.5, "ExitPrice": 1}
        assert compute_pnl(trade) == 150

    def test_invalid(self):
        trade = {"Resultaat": "abc"}
        assert compute_pnl(trade) is None


class TestDetermineStrategyType:
    def test_iron_condor(self):
        legs = [
            {"right": "C", "position": 1},
            {"right": "C", "position": -1},
            {"right": "P", "position": 1},
            {"right": "P", "position": -1},
        ]
        assert determine_strategy_type(legs) == "iron_condor"

    def test_straddle(self):
        legs = [
            {"right": "C", "strike": 100, "position": -1},
            {"right": "P", "strike": 100, "position": -1},
        ]
        assert determine_strategy_type(legs) == "Straddle"

    def test_long_call(self):
        legs = [{"right": "C", "position": 2}]
        assert determine_strategy_type(legs) == "Long Call"


class TestCheckEntryConditions:
    def test_iv_significant_above_hv(self):
        strat = {"avg_iv": 0.6, "HV30": 0.4}
        alerts = check_entry_conditions(strat)
        assert "✅ IV significant boven HV30" in alerts

    def test_iv_just_above_hv(self):
        strat = {"avg_iv": 0.52, "HV30": 0.5}
        alerts = check_entry_conditions(strat)
        assert any(alert.startswith("⚠️ IV ligt slechts") for alert in alerts)

    def test_iv_below_hv(self):
        strat = {"avg_iv": 0.45, "HV30": 0.5}
        alerts = check_entry_conditions(strat)
        assert any(alert.startswith("⏬ IV onder HV") for alert in alerts)

    def test_skew_warning(self):
        strat = {"avg_iv": 0.6, "HV30": 0.4, "skew": 0.1}
        alerts = check_entry_conditions(strat)
        assert "⚠️ Skew buiten range (+10.00%)" in alerts

    def test_iv_rank_warning(self):
        strat = {"avg_iv": 0.6, "HV30": 0.4, "IV_Rank": 20}
        alerts = check_entry_conditions(strat)
        assert any(alert.startswith("⚠️ IV Rank 20.0 lager dan") for alert in alerts)


class TestCollapseLegs:
    def test_calendar_spread_keeps_legs(self):
        legs = [
            {"conId": 1, "strike": 100, "right": "C", "position": -1},
            {"conId": 2, "strike": 100, "right": "C", "position": 1},
        ]
        collapsed = collapse_legs(legs)
        assert len(collapsed) == 2

    def test_same_expiry_collapses(self):
        legs = [
            {"conId": 3, "strike": 100, "right": "C", "position": -1},
            {"conId": 3, "strike": 100, "right": "C", "position": 1},
        ]
        assert collapse_legs(legs) == []
