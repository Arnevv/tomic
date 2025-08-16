"""Risk and entry alert helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from ..criteria import RULES
from .rules import evaluate_rules

rt = RULES.alerts.risk_thresholds


def check_entry_conditions(strategy: Dict[str, Any]) -> List[str]:
    """Return a list of entry warnings for ``strategy`` using declarative rules."""

    context: Dict[str, Any] = {
        **strategy,
        "skew_threshold": RULES.alerts.skew_threshold,
        "iv_hv_min_spread": RULES.alerts.iv_hv_min_spread,
        "iv_rank_threshold": RULES.alerts.iv_rank_threshold,
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
        if abs(delta_dollar) > rt.delta_dollar_max_abs:
            alerts.append(
                f"🚨 Delta-dollar blootstelling {delta_dollar:,.0f} > ${rt.delta_dollar_max_abs:,.0f}"
            )
        elif abs(delta_dollar) < rt.delta_dollar_min_abs:
            alerts.append("ℹ️ Beperkte exposure")

    vega = strategy.get("vega")
    ivr = strategy.get("IV_Rank")
    if vega is not None:
        if abs(vega) > rt.vega_abs_alert:
            alerts.append(
                f"🚨 Vega-exposure > {rt.vega_abs_alert}: gevoelig voor volbeweging"
            )
    if vega is not None and ivr is not None:
        if (
            vega < rt.vega_short_high_ivr.vega
            and ivr > rt.vega_short_high_ivr.iv_rank_min
        ):
            alerts.append(rt.vega_short_high_ivr.message)
        elif (
            vega > rt.vega_long_low_ivr.vega
            and ivr < rt.vega_long_low_ivr.iv_rank_max
        ):
            alerts.append(rt.vega_long_low_ivr.message)

    if delta is not None and vega is not None and ivr is not None:
        if delta >= 0.15 and vega > 30 and ivr < 0.30:
            alerts.append(
                "📈 Bullish + Long Vega in lage IV - time spread overwegen i.p.v. long call"
            )
        if delta <= -0.15 and vega < -30 and ivr > 0.60:
            alerts.append(
                "📉 Bearish + Short Vega in hoog vol klimaat - oppassen voor squeeze"
            )

    iv_hv = strategy.get("iv_hv_spread")
    if iv_hv is not None:
        if iv_hv > rt.iv_hv_bands.high:
            alerts.append("⏫ IV boven HV – premie relatief hoog")
        elif iv_hv < rt.iv_hv_bands.low:
            alerts.append("⏬ IV onder HV – premie relatief laag")
    skew = strategy.get("skew")
    if skew is not None:
        thr = RULES.alerts.skew_threshold
        if skew > thr:
            alerts.append("⚠️ Calls relatief duur vs puts (skew)")
        elif skew < -thr:
            alerts.append("⚠️ Puts relatief duur vs calls (skew)")

    if strategy.get("unrealizedPnL") is not None:
        cost_basis = abs(strategy.get("cost_basis", 0))
        if cost_basis and strategy.get("theta") is not None:
            if (
                strategy["unrealizedPnL"]
                > rt.pnl_theta.take_profit_pct_of_premium * cost_basis
                and strategy["theta"] > 0
            ):
                alerts.append("✅ Overweeg winstnemen (>70% premie afgebouwd)")
    pnl = strategy.get("unrealizedPnL")
    theta = strategy.get("theta")
    if (
        pnl is not None
        and pnl < -rt.pnl_theta.reconsider_loss_abs
        and theta is not None
        and theta > 0
    ):
        alerts.append("🔻 Negatieve PnL bij positieve theta – heroverweeg positie")

    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    rom = strategy.get("rom")
    if rom is not None:
        if rom >= rt.rom_bands.high_min * 100:
            alerts.append("🟢 ROM > 20% – hoge kapitaalefficiëntie")
        elif rom >= rt.rom_bands.mid_min * 100:
            alerts.append("✅ ROM tussen 10–20% – acceptabel rendement")
        elif rom < rt.rom_bands.low_max * 100:
            alerts.append("⚠️ ROM < 5% – lage kapitaalefficiëntie")
    if theta is not None and margin:
        theta_efficiency = abs(theta / margin) * 100
        bands = rt.theta_efficiency_bands
        if theta_efficiency < bands[0]:
            alerts.append(f"⚠️ Lage theta-efficiëntie (<{bands[0]}%)")
        elif theta_efficiency < bands[1]:
            alerts.append(
                f"🟡 Theta-efficiëntie acceptabel ({bands[0]}–{bands[1]}%)"
            )
        elif theta_efficiency < bands[2]:
            alerts.append(
                f"✅ Goede theta-efficiëntie ({bands[1]}–{bands[2]}%)"
            )
        else:
            alerts.append(f"🟢 Ideale theta-efficiëntie (>={bands[2]}%)")

    dte = strategy.get("days_to_expiry")
    if dte is not None and dte < rt.dte_close_threshold:
        alerts.append("⏳ Minder dan 10 dagen tot expiratie – overweeg sluiten of doorrollen")
    return alerts


__all__ = ["check_entry_conditions", "generate_risk_alerts"]
