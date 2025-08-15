"""Risk and entry alert helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from ..criteria import RULES
from .rules import evaluate_rules


def check_entry_conditions(
    strategy: Dict[str, Any],
    skew_threshold: float = 0.05,
    iv_hv_min_spread: float = 0.03,
    iv_rank_threshold: float = 30,
) -> List[str]:
    """Return a list of entry warnings for ``strategy`` using declarative rules."""

    context: Dict[str, Any] = {
        **strategy,
        "skew_threshold": skew_threshold,
        "iv_hv_min_spread": iv_hv_min_spread,
        "iv_rank_threshold": iv_rank_threshold,
    }
    if context.get("avg_iv") is not None and context.get("HV30") is not None:
        context["diff"] = context["avg_iv"] - context["HV30"]
    rules = [getattr(r, "model_dump", r.dict)() for r in RULES.alerts.entry_checks]
    return evaluate_rules(rules, context)


def generate_risk_alerts(strategy: Dict[str, Any]) -> List[str]:
    """Return general risk alerts for ``strategy``."""
    alerts: List[str] = []
    delta = strategy.get("delta")
    if delta is not None:
        if delta >= 0.30:
            alerts.append("📈 Sterk bullish (≥ +0.30)")
        elif delta >= 0.15:
            alerts.append("📈 Licht bullish")
        elif delta <= -0.30:
            alerts.append("📉 Sterk bearish (≤ –0.30)")
        elif delta <= -0.15:
            alerts.append("📉 Licht bearish")
        else:
            alerts.append("⚖️ Neutraal")

    spot = strategy.get("spot")
    legs = strategy.get("legs", [])
    if spot and legs:
        delta_dollar = sum(
            (leg.get("delta") or 0)
            * float(leg.get("position", 0) or 0)
            * float(leg.get("multiplier") or 1)
            * spot
            for leg in legs
        )
        if abs(delta_dollar) > 15000:
            alerts.append(f"🚨 Delta-dollar blootstelling {delta_dollar:,.0f} > $15k")
        elif abs(delta_dollar) < 3000:
            alerts.append("ℹ️ Beperkte exposure")

    vega = strategy.get("vega")
    ivr = strategy.get("IV_Rank")
    if vega is not None:
        if abs(vega) > 50:
            alerts.append("🚨 Vega-exposure > 50: gevoelig voor volbeweging")
    if vega is not None and ivr is not None:
        if vega < -30 and ivr > 60:
            alerts.append("⚠️ Short Vega in hoog vol klimaat — risico op squeeze")
        elif vega < -30 and ivr < 30:
            alerts.append("✅ Short Vega in lage IV — condorvriendelijk klimaat")
        elif vega > 30 and ivr < 30:
            alerts.append("⚠️ Long Vega in lage IV — kan dodelijk zijn bij crush")

    if delta is not None and vega is not None and ivr is not None:
        if delta >= 0.15 and vega > 30 and ivr < 30:
            alerts.append(
                "📈 Bullish + Long Vega in lage IV - time spread overwegen i.p.v. long call"
            )
        if delta <= -0.15 and vega < -30 and ivr > 60:
            alerts.append(
                "📉 Bearish + Short Vega in hoog vol klimaat - oppassen voor squeeze"
            )

    iv_hv = strategy.get("iv_hv_spread")
    if iv_hv is not None:
        if iv_hv > 0.05:
            alerts.append("⏫ IV boven HV – premie relatief hoog")
        elif iv_hv < -0.05:
            alerts.append("⏬ IV onder HV – premie relatief laag")
    skew = strategy.get("skew")
    if skew is not None:
        if skew > 0.05:
            alerts.append("⚠️ Calls relatief duur vs puts (skew)")
        elif skew < -0.05:
            alerts.append("⚠️ Puts relatief duur vs calls (skew)")

    if strategy.get("unrealizedPnL") is not None:
        cost_basis = abs(strategy.get("cost_basis", 0))
        if cost_basis and strategy.get("theta") is not None:
            if strategy["unrealizedPnL"] > 0.7 * cost_basis and strategy["theta"] > 0:
                alerts.append("✅ Overweeg winstnemen (>70% premie afgebouwd)")
    pnl = strategy.get("unrealizedPnL")
    theta = strategy.get("theta")
    if pnl is not None and pnl < -100 and theta is not None and theta > 0:
        alerts.append("🔻 Negatieve PnL bij positieve theta – heroverweeg positie")

    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    rom = strategy.get("rom")
    if rom is not None:
        if rom >= 20:
            alerts.append("🟢 ROM > 20% – hoge kapitaalefficiëntie")
        elif rom >= 10:
            alerts.append("✅ ROM tussen 10–20% – acceptabel rendement")
        elif rom < 5:
            alerts.append("⚠️ ROM < 5% – lage kapitaalefficiëntie")
    if theta is not None and margin:
        theta_efficiency = abs(theta / margin) * 100
        if theta_efficiency < 0.5:
            alerts.append("⚠️ Lage theta-efficiëntie (<0.5%)")
        elif theta_efficiency < 1.5:
            alerts.append("🟡 Theta-efficiëntie acceptabel (0.5–1.5%)")
        elif theta_efficiency < 2.5:
            alerts.append("✅ Goede theta-efficiëntie (1.5–2.5%)")
        else:
            alerts.append("🟢 Ideale theta-efficiëntie (>=2.5%)")

    dte = strategy.get("days_to_expiry")
    if dte is not None and dte < 10:
        alerts.append("⏳ Minder dan 10 dagen tot expiratie – overweeg sluiten of doorrollen")
    return alerts


__all__ = ["check_entry_conditions", "generate_risk_alerts"]
