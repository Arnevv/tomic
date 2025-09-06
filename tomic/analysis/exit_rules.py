"""Utilities for extracting exit rules and generating related alerts."""

from __future__ import annotations

from typing import Dict, Tuple

from tomic.journal.utils import load_journal
from tomic.models import ExitRules
from tomic.cli.strategy_data import ALERT_PROFILE

SEVERITY_MAP = {
    "🚨": 3,
    "⚠️": 2,
    "🔻": 2,
    "⏳": 2,
    "🟡": 1,
    "✅": 1,
    "🟢": 1,
}


def extract_exit_rules(path: str) -> Dict[Tuple[str, str], dict]:
    """Return exit rule thresholds per trade from ``journal.json``.

    The journal records are expected to contain an ``ExitRules`` object with
    structured exit criteria.
    """

    journal = load_journal(path)
    rules: Dict[Tuple[str, str], dict] = {}
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        raw_rules = trade.get("ExitRules")
        if not sym or not expiry or not isinstance(raw_rules, dict):
            continue
        er = ExitRules.from_dict(raw_rules)
        rule = {"premium_entry": trade.get("Premium")}
        rule.update(er.to_dict())
        rules[(sym, expiry)] = rule
    return rules


def alert_category(alert: str) -> str:
    """Return rough category tag for an alert string."""

    lower = alert.lower()
    if "delta" in lower:
        return "delta"
    if "vega" in lower:
        return "vega"
    if "theta" in lower:
        return "theta"
    if "iv" in lower:
        return "iv"
    if "skew" in lower:
        return "skew"
    if "rom" in lower:
        return "rom"
    if "pnl" in lower or "winst" in lower or "verlies" in lower:
        return "pnl"
    if "dagen" in lower or "exp" in lower:
        return "dte"
    return "other"


def alert_severity(alert: str) -> int:
    """Return numeric severity for sorting."""

    for key, val in SEVERITY_MAP.items():
        if key in alert:
            return val
    return 0


def generate_exit_alerts(strategy: dict, rule: dict | None) -> None:
    """Enrich ``strategy['alerts']`` with entry- and exit-alerts."""

    alerts = list(strategy.get("entry_alerts", [])) + list(strategy.get("alerts", []))
    if rule:
        spot = strategy.get("spot")
        pnl_val = strategy.get("unrealizedPnL")
        if spot is not None:
            if rule.get("spot_below") is not None and spot < rule["spot_below"]:
                alerts.append(
                    f"🚨 Spot {spot:.2f} onder exitniveau {rule['spot_below']}"
                )
            if rule.get("spot_above") is not None and spot > rule["spot_above"]:
                alerts.append(
                    f"🚨 Spot {spot:.2f} boven exitniveau {rule['spot_above']}"
                )
        if (
            pnl_val is not None
            and rule.get("target_profit_pct") is not None
            and rule.get("premium_entry")
        ):
            profit_pct = (pnl_val / (rule["premium_entry"] * 100)) * 100
            if profit_pct >= rule["target_profit_pct"]:
                alerts.append(
                    f"🚨 PnL {profit_pct:.1f}% >= target {rule['target_profit_pct']:.1f}%"
                )
        dte = strategy.get("days_to_expiry")
        dte_limit = rule.get("days_before_expiry")
        if dte_limit and dte is not None and dte <= dte_limit:
            alerts.append(f"⚠️ {dte} DTE ≤ exitdrempel {dte_limit}")
        dit = strategy.get("days_in_trade")
        dit_limit = rule.get("max_days_in_trade")
        if dit_limit and dit is not None and dit >= dit_limit:
            alerts.append(f"⚠️ {dit} dagen in trade ≥ max {dit_limit}")
    profile = ALERT_PROFILE.get(strategy.get("type"))
    if profile is not None:
        alerts = [a for a in alerts if alert_category(a) in profile]
    alerts = list(dict.fromkeys(alerts))
    alerts.sort(key=alert_severity, reverse=True)
    strategy["alerts"] = alerts


__all__ = ["extract_exit_rules", "generate_exit_alerts", "alert_severity"]
