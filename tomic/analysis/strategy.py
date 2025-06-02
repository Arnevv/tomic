"""Strategy grouping and metrics utilities."""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import mean
from datetime import datetime
from typing import Any, Dict, List, Optional

from tomic.utils import today
from tomic.analysis.entry_checks import check_entry_conditions


def parse_date(date_str: str) -> Optional[datetime.date]:
    """Parse ``date_str`` in ``YYYYMMDD`` or ``YYYY-MM-DD`` format."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def determine_strategy_type(legs: List[Dict[str, Any]]) -> str:
    """Return basic strategy type derived from legs."""
    calls = [leg for leg in legs if (leg.get("right") or leg.get("type")) == "C"]
    puts = [leg for leg in legs if (leg.get("right") or leg.get("type")) == "P"]
    n = len(legs)

    if (
        n == 4
        and len(calls) == 2
        and len(puts) == 2
        and all(abs(leg.get("position", 0)) == 1 for leg in legs)
    ):
        long_calls = [leg for leg in calls if leg.get("position", 0) > 0]
        short_calls = [leg for leg in calls if leg.get("position", 0) < 0]
        long_puts = [leg for leg in puts if leg.get("position", 0) > 0]
        short_puts = [leg for leg in puts if leg.get("position", 0) < 0]
        if (
            len(long_calls)
            == len(short_calls)
            == len(long_puts)
            == len(short_puts)
            == 1
        ):
            return "Iron Condor"

    if n == 3 and len(puts) == 3:
        long_puts = [leg for leg in puts if leg.get("position", 0) > 0]
        short_puts = [leg for leg in puts if leg.get("position", 0) < 0]
        if len(long_puts) == 1 and len(short_puts) == 2:
            return "Put Ratio Spread"

    if n == 2 and len(calls) == 1 and len(puts) == 1:
        call = calls[0]
        put = puts[0]
        if call.get("strike") == put.get("strike"):
            return "Straddle"

    if n == 2 and (len(calls) == 2 or len(puts) == 2):
        long_legs = [leg for leg in legs if leg.get("position", 0) > 0]
        short_legs = [leg for leg in legs if leg.get("position", 0) < 0]
        if len(long_legs) == 1 and len(short_legs) == 1:
            return "Vertical"

    if n == 1:
        leg = legs[0]
        qty = leg.get("position", 0)
        right = leg.get("right") or leg.get("type")
        if right == "C":
            return "Long Call" if qty > 0 else "Short Call"
        if right == "P":
            return "Naked Put" if qty < 0 else "Long Put"

    return "Other"


def aggregate_metrics(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate Greeks and volatility metrics for ``legs``."""
    metrics: Dict[str, Any] = {
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealizedPnL": 0.0,
        "cost_basis": 0.0,
    }
    iv_ranks: List[float] = []
    hv_values: List[float] = []
    atr_values: List[float] = []
    iv_values: List[float] = []
    iv_percentiles: List[float] = []
    call_iv: List[float] = []
    put_iv: List[float] = []
    iv_hv_spread_vals: List[float] = []
    for leg in legs:
        qty = leg.get("position", 0)
        mult = float(leg.get("multiplier") or 1)
        for g in ["delta", "gamma", "vega", "theta"]:
            val = leg.get(g)
            if val is not None:
                if g == "delta":
                    metrics["delta"] += val * qty
                else:
                    metrics[g] += val * qty * mult
        if leg.get("unrealizedPnL") is not None:
            metrics["unrealizedPnL"] += leg["unrealizedPnL"]
        if leg.get("avgCost") is not None:
            metrics["cost_basis"] += leg["avgCost"] * qty
        if leg.get("IV_Rank") is not None:
            iv_ranks.append(leg["IV_Rank"])
        if leg.get("IV_Percentile") is not None:
            iv_percentiles.append(leg["IV_Percentile"])
        if leg.get("HV30") is not None:
            hv_values.append(leg["HV30"])
        if leg.get("ATR14") is not None:
            atr_values.append(leg["ATR14"])
        if leg.get("iv") is not None:
            iv = leg.get("iv")
            iv_values.append(iv)
            right = leg.get("right") or leg.get("type")
            if right == "C":
                call_iv.append(iv)
            elif right == "P":
                put_iv.append(iv)
            hv = leg.get("HV30")
            if hv is not None:
                hv_dec = hv / 100 if hv > 1 else hv
                iv_hv_spread_vals.append(iv - hv_dec)
    metrics["IV_Rank"] = mean(iv_ranks) if iv_ranks else None
    metrics["IV_Percentile"] = mean(iv_percentiles) if iv_percentiles else None
    metrics["HV30"] = max(hv_values) if hv_values else None
    metrics["ATR14"] = max(atr_values) if atr_values else None
    metrics["avg_iv"] = mean(iv_values) if iv_values else None
    metrics["call_iv_avg"] = mean(call_iv) if call_iv else None
    metrics["put_iv_avg"] = mean(put_iv) if put_iv else None
    if metrics.get("call_iv_avg") is not None and metrics.get("put_iv_avg") is not None:
        metrics["skew"] = metrics["call_iv_avg"] - metrics["put_iv_avg"]
    else:
        metrics["skew"] = None
    metrics["iv_hv_spread"] = mean(iv_hv_spread_vals) if iv_hv_spread_vals else None
    return metrics


def generate_alerts(strategy: Dict[str, Any]) -> List[str]:
    """Return basic risk alerts for a strategy."""
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
            * leg.get("position", 0)
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

    theta = strategy.get("theta")
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
        alerts.append(
            "⏳ Minder dan 10 dagen tot expiratie – overweeg sluiten of doorrollen"
        )
    return alerts


def parse_plan_metrics(plan_text: str) -> Dict[str, float]:
    """Extract max win/loss information from a trading plan string."""
    if not plan_text:
        return {}
    metrics: Dict[str, float] = {}
    m = re.search(r"Max verlies\s*\|\s*([^|\n]+)", plan_text)
    if m:
        val = m.group(1).strip().replace("$", "").replace(",", "")
        val = val.replace("\u2013", "-")
        try:
            metrics["max_loss"] = float(val)
        except ValueError:
            pass
    m = re.search(r"Netto premie\s*\|\s*\$?([0-9.,]+)", plan_text)
    if m:
        val = m.group(1).replace(",", "")
        try:
            metrics["max_profit"] = float(val)
        except ValueError:
            pass
    if "max_profit" in metrics and "max_loss" in metrics and metrics["max_loss"]:
        rr = metrics["max_profit"] / abs(metrics["max_loss"])
        if abs(abs(metrics["max_profit"]) - abs(metrics["max_loss"])) < 1e-2:
            rr = None
        metrics["risk_reward"] = rr
    return metrics


def heuristic_risk_metrics(
    legs: List[Dict[str, Any]], cost_basis: float
) -> Dict[str, Any]:
    """Rough estimation of max win/loss for simple strategies."""
    if len(legs) == 2:
        rights = {leg.get("right") or leg.get("type") for leg in legs}
        if len(rights) == 1:
            strikes = [leg.get("strike", 0) for leg in legs]
            width = abs(strikes[0] - strikes[1]) * 100
            credit = -cost_basis if cost_basis < 0 else 0
            debit = cost_basis if cost_basis > 0 else 0
            if credit:
                max_profit = credit
                max_loss = width - credit
            else:
                max_profit = width - debit
                max_loss = debit
            rr = max_profit / abs(max_loss) if max_loss else None
            if abs(abs(max_profit) - abs(max_loss)) < 1e-2:
                rr = None
            return {
                "max_profit": max_profit,
                "max_loss": -abs(max_loss),
                "risk_reward": rr,
            }
    if len(legs) == 4:
        rights = [leg.get("right") or leg.get("type") for leg in legs]
        if rights.count("P") == 2 and rights.count("C") == 2:
            put_short = [
                leg
                for leg in legs
                if (leg.get("right") or leg.get("type")) == "P"
                and leg.get("position", 0) < 0
            ][0]
            put_long = [
                leg
                for leg in legs
                if (leg.get("right") or leg.get("type")) == "P"
                and leg.get("position", 0) > 0
            ][0]
            call_short = [
                leg
                for leg in legs
                if (leg.get("right") or leg.get("type")) == "C"
                and leg.get("position", 0) < 0
            ][0]
            call_long = [
                leg
                for leg in legs
                if (leg.get("right") or leg.get("type")) == "C"
                and leg.get("position", 0) > 0
            ][0]
            width_put = abs(put_short.get("strike", 0) - put_long.get("strike", 0))
            width_call = abs(call_short.get("strike", 0) - call_long.get("strike", 0))
            width = max(width_put, width_call) * 100
            credit = -cost_basis if cost_basis < 0 else 0
            max_profit = credit
            max_loss = width - credit
            rr = max_profit / abs(max_loss) if max_loss else None
            if abs(abs(max_profit) - abs(max_loss)) < 1e-2:
                rr = None
            return {
                "max_profit": max_profit,
                "max_loss": -abs(max_loss),
                "risk_reward": rr,
            }
    return {}


def collapse_legs(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge legs representing the same contract."""
    merged: Dict[Any, Dict[str, Any]] = {}
    for leg in legs:
        cid = leg.get("conId")
        if cid is None:
            expiry = (
                leg.get("lastTradeDate") or leg.get("expiry") or leg.get("expiration")
            )
            key = (leg.get("strike"), leg.get("right") or leg.get("type"), expiry)
        else:
            key = cid
        if key not in merged:
            merged[key] = leg.copy()
        else:
            merged[key]["position"] += leg.get("position", 0)
    return [leg for leg in merged.values() if leg.get("position")]


def group_strategies(
    positions: List[Dict[str, Any]], journal: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Group positions into strategies and enrich with metrics."""
    trade_by_id: Dict[Any, Dict[str, Any]] = {}
    conid_to_trade: Dict[Any, Any] = {}
    symbol_expiry_lookup: Dict[tuple, Dict[str, Any]] = {}
    if journal:
        for trade in journal:
            tid = trade.get("TradeID") or id(trade)
            trade_by_id[tid] = trade
            symbol_expiry_lookup[(trade.get("Symbool"), trade.get("Expiry"))] = trade
            for leg in trade.get("Legs", []):
                cid = leg.get("conId")
                if cid is not None:
                    conid_to_trade[cid] = tid

    trade_groups: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    fallback_groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)

    for pos in positions:
        cid = pos.get("conId")
        tid = conid_to_trade.get(cid)
        if tid is not None:
            trade_groups[tid].append(pos)
            continue
        symbol = pos.get("symbol")
        expiry = pos.get("lastTradeDate") or pos.get("expiry") or pos.get("expiration")
        if symbol and expiry:
            fallback_groups[(symbol, expiry)].append(pos)

    strategies: List[Dict[str, Any]] = []

    def build_strategy(
        symbol: str,
        expiry: str,
        legs: List[Dict[str, Any]],
        trade_data: Optional[Dict[str, Any]] = None,
        trade_id: Any = None,
    ) -> Dict[str, Any]:
        legs = collapse_legs(legs)
        strat: Dict[str, Any] = {
            "symbol": symbol,
            "expiry": expiry,
            "type": (
                trade_data.get("Type") if trade_data else determine_strategy_type(legs)
            ),
            "legs": legs,
            "trade_id": trade_id,
        }

        spot_current = None
        for leg in legs:
            for key in ["spot", "spot_price", "underlyingPrice", "Spot"]:
                if leg.get(key) is not None:
                    spot_current = leg.get(key)
                    break
            if spot_current is not None:
                break

        spot_open = None
        if trade_data:
            spot_open = trade_data.get("Spot")
            if not spot_open:
                snaps = trade_data.get("Snapshots", [])
                if snaps:
                    spot_open = snaps[0].get("spot")

        strat.update(aggregate_metrics(legs))
        strat["spot"] = spot_current if spot_current is not None else spot_open
        strat["spot_current"] = spot_current
        strat["spot_open"] = spot_open
        strat["margin_used"] = abs(strat.get("cost_basis", 0))

        exp_date = parse_date(expiry)
        if exp_date:
            strat["days_to_expiry"] = (exp_date - today()).days
        else:
            strat["days_to_expiry"] = None

        days_in_trade = None
        if trade_data:
            if trade_data.get("DaysInTrade") is not None:
                days_in_trade = trade_data.get("DaysInTrade")
            else:
                d_in = parse_date(trade_data.get("DatumIn"))
                if d_in:
                    days_in_trade = (today() - d_in).days
            exp_d = exp_date or parse_date(trade_data.get("Expiry"))
            d_in = parse_date(trade_data.get("DatumIn"))
            if d_in and exp_d:
                strat["dte_entry"] = (exp_d - d_in).days
            else:
                strat["dte_entry"] = None

            strat.update(parse_plan_metrics(trade_data.get("Plan", "")))

            ge = trade_data.get("Greeks_Entry")
            if isinstance(ge, dict):
                strat["delta_entry"] = ge.get("Delta")
                strat["gamma_entry"] = ge.get("Gamma")
                strat["vega_entry"] = ge.get("Vega")
                strat["theta_entry"] = ge.get("Theta")

            for key, new_key in [
                ("IV_Entry", "iv_entry"),
                ("HV_Entry", "hv_entry"),
                ("IV_Rank", "ivrank_entry"),
                ("IV_Percentile", "ivpct_entry"),
                ("Skew", "skew_entry"),
                ("ATR_14", "atr_entry"),
            ]:
                if trade_data.get(key) is not None:
                    try:
                        strat[new_key] = float(trade_data.get(key))
                    except (TypeError, ValueError):
                        strat[new_key] = None

            if trade_data.get("InitMargin") is not None:
                try:
                    strat["init_margin"] = float(trade_data.get("InitMargin"))
                except (TypeError, ValueError):
                    strat["init_margin"] = None
        strat["days_in_trade"] = days_in_trade

        if strat.get("spot") is None and trade_data:
            if spot_open is not None:
                strat["spot"] = spot_open
            else:
                snaps = trade_data.get("Snapshots", [])
                for snap in reversed(snaps):
                    if snap.get("spot") is not None:
                        strat["spot"] = snap["spot"]
                        break

        if strat.get("spot") and strat.get("legs"):
            strat["delta_dollar"] = sum(
                (leg.get("delta") or 0)
                * leg.get("position", 0)
                * float(leg.get("multiplier") or 1)
                * strat["spot"]
                for leg in legs
            )
        else:
            strat["delta_dollar"] = None

        risk = heuristic_risk_metrics(legs, strat.get("cost_basis", 0))
        strat.update(risk)

        margin_ref = strat.get("init_margin") or strat.get("margin_used") or 1000
        pnl_val = strat.get("unrealizedPnL")
        if pnl_val is not None and margin_ref:
            strat["rom"] = (pnl_val / margin_ref) * 100
        else:
            strat["rom"] = None

        strat["alerts"] = generate_alerts(strat)
        strat["entry_alerts"] = check_entry_conditions(strat)

        return strat

    for tid, legs in trade_groups.items():
        trade = trade_by_id.get(tid)
        symbol = trade.get("Symbool") if trade else legs[0].get("symbol")
        expiry = (
            trade.get("Expiry")
            if trade
            else (
                legs[0].get("lastTradeDate")
                or legs[0].get("expiry")
                or legs[0].get("expiration")
            )
        )
        strategies.append(build_strategy(symbol, expiry, legs, trade, trade_id=tid))

    for (symbol, expiry), legs in fallback_groups.items():
        trade = symbol_expiry_lookup.get((symbol, expiry))
        tid = trade.get("TradeID") if trade else None
        strategies.append(build_strategy(symbol, expiry, legs, trade, trade_id=tid))

    return strategies
