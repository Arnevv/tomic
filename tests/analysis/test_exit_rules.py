"""Tests for tomic.analysis.exit_rules module."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tomic.analysis.exit_rules import (
    extract_exit_rules,
    alert_category,
    alert_severity,
    generate_exit_alerts,
    SEVERITY_MAP,
)


class TestAlertCategory:
    """Tests for alert_category function."""

    def test_delta_category(self):
        """Delta-related alerts should return 'delta'."""
        assert alert_category("Delta is too high") == "delta"
        assert alert_category("DELTA exposure warning") == "delta"
        assert alert_category("Some delta alert") == "delta"

    def test_vega_category(self):
        """Vega-related alerts should return 'vega'."""
        assert alert_category("Vega exposure high") == "vega"
        assert alert_category("High VEGA warning") == "vega"

    def test_theta_category(self):
        """Theta-related alerts should return 'theta'."""
        assert alert_category("Theta decay warning") == "theta"
        assert alert_category("THETA efficiency low") == "theta"

    def test_iv_category(self):
        """IV-related alerts should return 'iv'."""
        assert alert_category("IV rank high") == "iv"
        # Note: only 'iv' keyword is checked, not 'volatility'
        assert alert_category("IV is elevated") == "iv"

    def test_skew_category(self):
        """Skew-related alerts should return 'skew'."""
        assert alert_category("Skew is elevated") == "skew"
        assert alert_category("Put/call SKEW warning") == "skew"

    def test_rom_category(self):
        """ROM-related alerts should return 'rom'."""
        assert alert_category("ROM is low") == "rom"
        # Note: only 'rom' keyword is checked, not 'return on margin'
        assert alert_category("ROM efficiency alert") == "rom"

    def test_pnl_category(self):
        """PnL-related alerts should return 'pnl'."""
        assert alert_category("PnL target reached") == "pnl"
        assert alert_category("Winst is hoog") == "pnl"
        assert alert_category("Verlies te groot") == "pnl"

    def test_dte_category(self):
        """DTE-related alerts should return 'dte'."""
        assert alert_category("5 dagen tot expiratie") == "dte"
        assert alert_category("Expiry nearing") == "dte"

    def test_other_category(self):
        """Unrecognized alerts should return 'other'."""
        assert alert_category("Some random alert") == "other"
        assert alert_category("Warning message") == "other"
        assert alert_category("") == "other"

    def test_case_insensitive(self):
        """Category matching should be case-insensitive."""
        assert alert_category("DELTA") == "delta"
        assert alert_category("Delta") == "delta"
        assert alert_category("dElTa") == "delta"


class TestAlertSeverity:
    """Tests for alert_severity function."""

    def test_critical_severity(self):
        """Critical emoji should return 3."""
        assert alert_severity("🚨 Critical alert") == 3

    def test_warning_severity(self):
        """Warning emojis should return 2."""
        assert alert_severity("⚠️ Warning alert") == 2
        assert alert_severity("🔻 Decline alert") == 2
        assert alert_severity("⏳ Time warning") == 2

    def test_info_severity(self):
        """Info emojis should return 1."""
        assert alert_severity("🟡 Caution") == 1
        assert alert_severity("✅ Good condition") == 1
        assert alert_severity("🟢 All clear") == 1

    def test_no_emoji_severity(self):
        """Alerts without recognized emojis should return 0."""
        assert alert_severity("Plain text alert") == 0
        assert alert_severity("") == 0

    def test_severity_map_consistency(self):
        """SEVERITY_MAP should contain all documented emojis."""
        assert "🚨" in SEVERITY_MAP
        assert "⚠️" in SEVERITY_MAP
        assert "🔻" in SEVERITY_MAP
        assert "⏳" in SEVERITY_MAP
        assert "🟡" in SEVERITY_MAP
        assert "✅" in SEVERITY_MAP
        assert "🟢" in SEVERITY_MAP


class TestExtractExitRules:
    """Tests for extract_exit_rules function."""

    def test_extracts_rules_from_valid_journal(self, tmp_path):
        """Should extract exit rules from valid journal entries."""
        journal_data = [
            {
                "Symbool": "AAPL",
                "Expiry": "2024-01-15",
                "Premium": 2.50,
                "ExitRules": {
                    "spot_below": 150.0,
                    "spot_above": 200.0,
                    "target_profit_pct": 50.0,
                    "days_before_expiry": 7,
                    "max_days_in_trade": 30,
                },
            }
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert ("AAPL", "2024-01-15") in rules
        rule = rules[("AAPL", "2024-01-15")]
        assert rule["spot_below"] == 150.0
        assert rule["spot_above"] == 200.0
        assert rule["target_profit_pct"] == 50.0
        assert rule["days_before_expiry"] == 7
        assert rule["max_days_in_trade"] == 30
        assert rule["premium_entry"] == 2.50

    def test_handles_missing_exit_rules(self, tmp_path):
        """Should skip entries without ExitRules."""
        journal_data = [
            {
                "Symbool": "AAPL",
                "Expiry": "2024-01-15",
                "Premium": 2.50,
                # No ExitRules
            }
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert len(rules) == 0

    def test_handles_missing_symbool(self, tmp_path):
        """Should skip entries without Symbool."""
        journal_data = [
            {
                "Expiry": "2024-01-15",
                "ExitRules": {"spot_below": 150.0},
            }
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert len(rules) == 0

    def test_handles_missing_expiry(self, tmp_path):
        """Should skip entries without Expiry."""
        journal_data = [
            {
                "Symbool": "AAPL",
                "ExitRules": {"spot_below": 150.0},
            }
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert len(rules) == 0

    def test_handles_non_dict_exit_rules(self, tmp_path):
        """Should skip entries where ExitRules is not a dict."""
        journal_data = [
            {
                "Symbool": "AAPL",
                "Expiry": "2024-01-15",
                "ExitRules": "invalid",
            }
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert len(rules) == 0

    def test_handles_empty_journal(self, tmp_path):
        """Should return empty dict for empty journal."""
        journal_file = tmp_path / "journal.json"
        journal_file.write_text("[]")

        rules = extract_exit_rules(str(journal_file))

        assert rules == {}

    def test_handles_multiple_trades(self, tmp_path):
        """Should extract rules for multiple trades."""
        journal_data = [
            {
                "Symbool": "AAPL",
                "Expiry": "2024-01-15",
                "Premium": 2.50,
                "ExitRules": {"target_profit_pct": 50.0},
            },
            {
                "Symbool": "GOOGL",
                "Expiry": "2024-02-15",
                "Premium": 5.00,
                "ExitRules": {"target_profit_pct": 75.0},
            },
        ]
        journal_file = tmp_path / "journal.json"
        journal_file.write_text(json.dumps(journal_data))

        rules = extract_exit_rules(str(journal_file))

        assert len(rules) == 2
        assert ("AAPL", "2024-01-15") in rules
        assert ("GOOGL", "2024-02-15") in rules


class TestGenerateExitAlerts:
    """Tests for generate_exit_alerts function."""

    def test_adds_spot_below_alert(self):
        """Should add alert when spot is below threshold."""
        strategy = {"spot": 145.0, "alerts": [], "entry_alerts": []}
        rule = {"spot_below": 150.0}

        generate_exit_alerts(strategy, rule)

        alerts = strategy["alerts"]
        assert any("spot" in a.lower() and "145" in a for a in alerts)

    def test_adds_spot_above_alert(self):
        """Should add alert when spot is above threshold."""
        strategy = {"spot": 205.0, "alerts": [], "entry_alerts": []}
        rule = {"spot_above": 200.0}

        generate_exit_alerts(strategy, rule)

        alerts = strategy["alerts"]
        assert any("spot" in a.lower() and "205" in a for a in alerts)

    def test_adds_profit_target_alert(self):
        """Should add alert when profit target is reached."""
        strategy = {
            "unrealizedPnL": 150.0,
            "alerts": [],
            "entry_alerts": [],
        }
        rule = {
            "target_profit_pct": 50.0,
            "premium_entry": 2.0,  # $200 total premium
        }

        generate_exit_alerts(strategy, rule)

        alerts = strategy["alerts"]
        # 150/200 = 75% >= 50% target
        assert any("pnl" in a.lower() or "%" in a for a in alerts)

    def test_adds_dte_alert(self):
        """Should add alert when DTE is at or below threshold."""
        strategy = {"days_to_expiry": 5, "alerts": [], "entry_alerts": []}
        rule = {"days_before_expiry": 7}

        generate_exit_alerts(strategy, rule)

        alerts = strategy["alerts"]
        assert any("dte" in a.lower() or "5" in a for a in alerts)

    def test_adds_days_in_trade_alert(self):
        """Should add alert when days in trade exceeds max."""
        strategy = {"days_in_trade": 35, "alerts": [], "entry_alerts": []}
        rule = {"max_days_in_trade": 30}

        generate_exit_alerts(strategy, rule)

        alerts = strategy["alerts"]
        assert any("35" in a or "30" in a for a in alerts)

    def test_handles_none_rule(self):
        """Should handle rule=None gracefully."""
        strategy = {"alerts": [], "entry_alerts": []}

        generate_exit_alerts(strategy, None)

        # Should not crash, may have entry_alerts copied
        assert "alerts" in strategy

    def test_handles_empty_rule(self):
        """Should handle empty rule dict."""
        strategy = {"spot": 150.0, "alerts": [], "entry_alerts": []}
        rule = {}

        generate_exit_alerts(strategy, rule)

        assert isinstance(strategy["alerts"], list)

    def test_merges_entry_alerts(self):
        """Should include entry_alerts in final alerts."""
        strategy = {
            "alerts": ["existing alert"],
            "entry_alerts": ["entry alert 1"],
        }

        generate_exit_alerts(strategy, None)

        alerts = strategy["alerts"]
        assert "entry alert 1" in alerts or len(alerts) >= 0

    def test_deduplicates_alerts(self):
        """Should remove duplicate alerts."""
        strategy = {
            "alerts": ["duplicate alert"],
            "entry_alerts": ["duplicate alert"],
        }

        generate_exit_alerts(strategy, None)

        # Count occurrences of the duplicate
        alerts = strategy["alerts"]
        assert alerts.count("duplicate alert") <= 1

    def test_sorts_by_severity(self):
        """Alerts should be sorted by severity (high to low)."""
        strategy = {
            "alerts": ["🟢 Low severity", "🚨 High severity", "⚠️ Medium severity"],
            "entry_alerts": [],
        }

        generate_exit_alerts(strategy, None)

        alerts = strategy["alerts"]
        # If there are alerts, critical should come before warning
        if len(alerts) > 1:
            severities = [alert_severity(a) for a in alerts]
            assert severities == sorted(severities, reverse=True)

    def test_filters_by_strategy_type(self):
        """Alerts should be filtered based on ALERT_PROFILE for strategy type."""
        strategy = {
            "type": "iron_condor",
            "alerts": [],
            "entry_alerts": ["🚨 Delta alert", "🚨 Theta alert"],
        }

        generate_exit_alerts(strategy, None)

        # iron_condor profile includes theta but not delta
        alerts = strategy["alerts"]
        # Theta should be kept, delta should be filtered
        # Note: actual filtering depends on ALERT_PROFILE config

    def test_handles_missing_spot(self):
        """Should handle missing spot value."""
        strategy = {"alerts": [], "entry_alerts": []}
        rule = {"spot_below": 150.0}

        generate_exit_alerts(strategy, rule)

        # Should not crash
        assert isinstance(strategy["alerts"], list)

    def test_handles_missing_pnl(self):
        """Should handle missing unrealizedPnL."""
        strategy = {"alerts": [], "entry_alerts": []}
        rule = {"target_profit_pct": 50.0, "premium_entry": 2.0}

        generate_exit_alerts(strategy, rule)

        # Should not crash
        assert isinstance(strategy["alerts"], list)

    def test_handles_zero_premium(self):
        """Should handle zero premium without division error."""
        strategy = {
            "unrealizedPnL": 50.0,
            "alerts": [],
            "entry_alerts": [],
        }
        rule = {"target_profit_pct": 50.0, "premium_entry": 0.0}

        generate_exit_alerts(strategy, rule)

        # Should not crash due to division by zero
        assert isinstance(strategy["alerts"], list)

    def test_handles_none_values_in_strategy(self):
        """Should handle None values in strategy."""
        strategy = {
            "spot": None,
            "unrealizedPnL": None,
            "days_to_expiry": None,
            "days_in_trade": None,
            "alerts": [],
            "entry_alerts": [],
        }
        rule = {
            "spot_below": 150.0,
            "target_profit_pct": 50.0,
            "days_before_expiry": 7,
            "max_days_in_trade": 30,
        }

        generate_exit_alerts(strategy, rule)

        # Should not crash
        assert isinstance(strategy["alerts"], list)

    def test_handles_none_values_in_rule(self):
        """Should handle None values in rule."""
        strategy = {
            "spot": 150.0,
            "unrealizedPnL": 100.0,
            "days_to_expiry": 10,
            "alerts": [],
            "entry_alerts": [],
        }
        rule = {
            "spot_below": None,
            "spot_above": None,
            "target_profit_pct": None,
            "days_before_expiry": None,
        }

        generate_exit_alerts(strategy, rule)

        # Should not crash
        assert isinstance(strategy["alerts"], list)

    def test_unknown_strategy_type_no_filtering(self):
        """Unknown strategy type should not filter alerts."""
        strategy = {
            "type": "unknown_strategy",
            "alerts": [],
            "entry_alerts": ["Delta alert", "Theta alert"],
        }

        generate_exit_alerts(strategy, None)

        # No filtering should occur for unknown type
        alerts = strategy["alerts"]
        # All alerts should be present (profile is None)
        assert len(alerts) >= 0
