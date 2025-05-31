import json
import os
import sys
from collections import defaultdict
from statistics import mean
from datetime import datetime
import re

from tomic.config import get as cfg_get
from tomic.utils import today
from tomic.logging import setup_logging
from tomic.helpers.account import _fmt_money, print_account_overview
from tomic.journal.utils import load_journal

setup_logging()


def compute_portfolio_greeks(positions):
    totals = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for pos in positions:
        mult = float(pos.get("multiplier") or 1)
        qty = pos.get("position", 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is not None:
                if greek == "delta":
                    totals["Delta"] += val * qty
                else:
                    totals[greek.capitalize()] += val * qty * mult
    return totals


def load_positions(path: str):
    """Load positions JSON file and return list of open positions."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [p for p in data if p.get("position")]


def load_account_info(path: str):
    """Load account info JSON file and return as dict."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"\u26a0\ufe0f Kan accountinfo niet laden uit {path}: {e}")
        return {}


def extract_exit_rules(path: str):
    """Parse journal.json and return exit thresholds per trade."""
    journal = load_journal(path)
    rules = {}
    for trade in journal:
        sym = trade.get("Symbool")
        expiry = trade.get("Expiry")
        text = trade.get("Exitstrategie", "")
        if not sym or not expiry or not text:
            continue
        rule = {"premium_entry": trade.get("Premium")}
        txt = text.replace(",", ".")
        m = re.search(r"onder\s*~?([0-9]+(?:\.[0-9]+)?)", txt, re.I)
        if m:
            rule["spot_below"] = float(m.group(1))
        m = re.search(r"boven\s*~?([0-9]+(?:\.[0-9]+)?)", txt, re.I)
        if m:
            rule["spot_above"] = float(m.group(1))
        m = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", txt)
        if m:
            rule["premium_target"] = float(m.group(1))
            if (
                isinstance(rule.get("premium_entry"), (int, float))
                and rule["premium_entry"]
            ):
                rule["target_profit_pct"] = (
                    (rule["premium_entry"] - rule["premium_target"])
                    / rule["premium_entry"]
                ) * 100
        m = re.search(r"(\d+)\s*dagen", txt, re.I)
        if m:
            rule["days_before_expiry"] = int(m.group(1))
        rules[(sym, expiry)] = rule
    return rules


def parse_date(date_str: str):
    """Parse a date in YYYYMMDD or YYYY-MM-DD format to a date object."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def determine_strategy_type(legs):
    calls = [l for l in legs if (l.get("right") or l.get("type")) == "C"]
    puts = [l for l in legs if (l.get("right") or l.get("type")) == "P"]
    n = len(legs)

    # Iron Condor: 4 legs (2 calls, 2 puts) with one long and one short
    if (
        n == 4
        and len(calls) == 2
        and len(puts) == 2
        and all(abs(l.get("position", 0)) == 1 for l in legs)
    ):
        long_calls = [l for l in calls if l.get("position", 0) > 0]
        short_calls = [l for l in calls if l.get("position", 0) < 0]
        long_puts = [l for l in puts if l.get("position", 0) > 0]
        short_puts = [l for l in puts if l.get("position", 0) < 0]
        if (
            len(long_calls)
            == len(short_calls)
            == len(long_puts)
            == len(short_puts)
            == 1
        ):
            return "Iron Condor"

    # Put Ratio Spread: 3 puts, 2 short + 1 long
    if n == 3 and len(puts) == 3:
        long_puts = [l for l in puts if l.get("position", 0) > 0]
        short_puts = [l for l in puts if l.get("position", 0) < 0]
        if len(long_puts) == 1 and len(short_puts) == 2:
            return "Put Ratio Spread"

    # Straddle: 1 put + 1 call on same strike
    if n == 2 and len(calls) == 1 and len(puts) == 1:
        call = calls[0]
        put = puts[0]
        if call.get("strike") == put.get("strike"):
            return "Straddle"

    # Vertical spread: two calls or two puts with opposite direction
    if n == 2 and (len(calls) == 2 or len(puts) == 2):
        long_legs = [l for l in legs if l.get("position", 0) > 0]
        short_legs = [l for l in legs if l.get("position", 0) < 0]
        if len(long_legs) == 1 and len(short_legs) == 1:
            return "Vertical"

    # Single-leg strategies
    if n == 1:
        leg = legs[0]
        qty = leg.get("position", 0)
        right = leg.get("right") or leg.get("type")
        if right == "C":
            return "Long Call" if qty > 0 else "Short Call"
        if right == "P":
            return "Naked Put" if qty < 0 else "Long Put"

    return "Other"


def aggregate_metrics(legs):
    metrics = {
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealizedPnL": 0.0,
        "cost_basis": 0.0,
    }
    iv_ranks = []
    hv_values = []
    atr_values = []
    iv_values = []
    iv_percentiles = []
    call_iv = []
    put_iv = []
    iv_hv_spread_vals = []
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


def generate_alerts(strategy):
    alerts = []
    # 🔹 Delta-analyse
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

    # Delta-dollar analyse
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

    # 🔹 Vega en IV Rank-analyse
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

    # 🔹 Gecombineerde richting + vega alerts
    if delta is not None and vega is not None and ivr is not None:
        if delta >= 0.15 and vega > 30 and ivr < 30:
            alerts.append(
                "📈 Bullish + Long Vega in lage IV → time spread overwegen i.p.v. long call"
            )
        if delta <= -0.15 and vega < -30 and ivr > 60:
            alerts.append(
                "📉 Bearish + Short Vega in hoog vol klimaat → oppassen voor squeeze"
            )

    # 🔹 IV-HV en skew analyse
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

    # bestaande winstneem-alert
    if strategy.get("unrealizedPnL") is not None:
        cost_basis = abs(strategy.get("cost_basis", 0))
        if cost_basis and strategy.get("theta") is not None:
            if strategy["unrealizedPnL"] > 0.7 * cost_basis and strategy["theta"] > 0:
                alerts.append("✅ Overweeg winstnemen (>70% premie afgebouwd)")
    pnl = strategy.get("unrealizedPnL")
    theta = strategy.get("theta")
    if pnl is not None and pnl < -100 and theta is not None and theta > 0:
        alerts.append("🔻 Negatieve PnL bij positieve theta – heroverweeg positie")

    # 🔹 Theta-rendement analyse
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

    # 🔹 Eventueel aanvullen met trend/spotalerts later
    dte = strategy.get("days_to_expiry")
    if dte is not None and dte < 10:
        alerts.append(
            "⏳ Minder dan 10 dagen tot expiratie – overweeg sluiten of doorrollen"
        )
    return alerts


def parse_plan_metrics(plan_text: str) -> dict:
    """Extract max win/loss from a plan string if possible."""
    if not plan_text:
        return {}
    metrics = {}
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
        metrics["risk_reward"] = metrics["max_profit"] / abs(metrics["max_loss"])
    return metrics


def heuristic_risk_metrics(legs, cost_basis):
    """Rough estimation of max win/loss for basic strategies."""
    if len(legs) == 2:
        rights = {l.get("right") or l.get("type") for l in legs}
        if len(rights) == 1:
            strikes = [l.get("strike", 0) for l in legs]
            width = abs(strikes[0] - strikes[1]) * 100
            credit = -cost_basis if cost_basis < 0 else 0
            debit = cost_basis if cost_basis > 0 else 0
            if credit:
                max_profit = credit
                max_loss = width - credit
            else:
                max_profit = width - debit
                max_loss = debit
            return {
                "max_profit": max_profit,
                "max_loss": -abs(max_loss),
                "risk_reward": max_profit / abs(max_loss) if max_loss else None,
            }
    if len(legs) == 4:
        rights = [l.get("right") or l.get("type") for l in legs]
        if rights.count("P") == 2 and rights.count("C") == 2:
            put_short = [
                l
                for l in legs
                if (l.get("right") or l.get("type")) == "P" and l.get("position", 0) < 0
            ][0]
            put_long = [
                l
                for l in legs
                if (l.get("right") or l.get("type")) == "P" and l.get("position", 0) > 0
            ][0]
            call_short = [
                l
                for l in legs
                if (l.get("right") or l.get("type")) == "C" and l.get("position", 0) < 0
            ][0]
            call_long = [
                l
                for l in legs
                if (l.get("right") or l.get("type")) == "C" and l.get("position", 0) > 0
            ][0]
            width_put = abs(put_short.get("strike", 0) - put_long.get("strike", 0))
            width_call = abs(call_short.get("strike", 0) - call_long.get("strike", 0))
            width = max(width_put, width_call) * 100
            credit = -cost_basis if cost_basis < 0 else 0
            max_profit = credit
            max_loss = width - credit
            return {
                "max_profit": max_profit,
                "max_loss": -abs(max_loss),
                "risk_reward": max_profit / abs(max_loss) if max_loss else None,
            }
    return {}


def collapse_legs(legs):
    merged = {}
    for leg in legs:
        key = (leg.get("strike"), leg.get("right") or leg.get("type"))
        if key not in merged:
            merged[key] = leg.copy()
        else:
            merged[key]["position"] += leg.get("position", 0)
    return [l for l in merged.values() if l.get("position")]


def group_strategies(positions, journal=None):
    """Group positions into strategies, mapping to journal trades when possible."""
    trade_by_id = {}
    conid_to_trade = {}
    symbol_expiry_lookup = {}
    if journal:
        for trade in journal:
            tid = trade.get("TradeID") or id(trade)
            trade_by_id[tid] = trade
            symbol_expiry_lookup[(trade.get("Symbool"), trade.get("Expiry"))] = trade
            for leg in trade.get("Legs", []):
                cid = leg.get("conId")
                if cid is not None:
                    conid_to_trade[cid] = tid

    trade_groups = defaultdict(list)
    fallback_groups = defaultdict(list)

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

    strategies = []

    def build_strategy(symbol, expiry, legs, trade_data=None, trade_id=None):
        legs = collapse_legs(legs)
        strat = {
            "symbol": symbol,
            "expiry": expiry,
            "type": (
                trade_data.get("Type") if trade_data else determine_strategy_type(legs)
            ),
            "legs": legs,
            "trade_id": trade_id,
        }
        # haal eventueel spotprijs uit een van de legs
        spot = None
        for leg in legs:
            for key in ["spot", "spot_price", "underlyingPrice", "Spot"]:
                if leg.get(key) is not None:
                    spot = leg.get(key)
                    break
            if spot is not None:
                break
        strat.update(aggregate_metrics(legs))
        strat["spot"] = spot
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
            strat.update(parse_plan_metrics(trade_data.get("Plan", "")))
            if trade_data.get("InitMargin") is not None:
                try:
                    strat["init_margin"] = float(trade_data.get("InitMargin"))
                except (TypeError, ValueError):
                    strat["init_margin"] = None
        strat["days_in_trade"] = days_in_trade

        if strat.get("spot") is None and trade_data:
            spot = trade_data.get("Spot")
            if not spot:
                snaps = trade_data.get("Snapshots", [])
                for snap in reversed(snaps):
                    if snap.get("spot") is not None:
                        spot = snap["spot"]
                        break
            strat["spot"] = spot

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


def compute_term_structure(strategies):
    """Annotate strategies with simple term structure slope."""
    by_symbol = defaultdict(list)
    for strat in strategies:
        exp = parse_date(strat.get("expiry"))
        iv = strat.get("avg_iv")
        if exp and iv is not None:
            by_symbol[strat["symbol"]].append((exp, iv, strat))
    for items in by_symbol.values():
        items.sort(key=lambda x: x[0])
        for i, (exp, iv, strat) in enumerate(items):
            if i + 1 < len(items):
                next_iv = items[i + 1][1]
                strat["term_slope"] = next_iv - iv
            else:
                strat["term_slope"] = None


def sort_legs(legs):
    """Return legs sorted by option type and position."""
    type_order = {"P": 0, "C": 1}

    def key(leg):
        right = leg.get("right") or leg.get("type")
        pos = leg.get("position", 0)
        return (
            type_order.get(right, 2),
            0 if pos < 0 else 1,
            leg.get("strike", 0),
        )

    return sorted(legs, key=key)


# Mapping of leg characteristics to emoji symbols
SYMBOL_MAP = {
    ("P", -1): "🔴",  # short put
    ("P", 1): "🔵",  # long put
    ("C", -1): "🟡",  # short call
    ("C", 1): "🟢",  # long call
}


def print_strategy(strategy, rule=None):
    pnl = strategy.get("unrealizedPnL")
    color = "🟩" if pnl is not None and pnl >= 0 else "🟥"
    print(f"{color} {strategy['symbol']} – {strategy['type']}")
    delta = strategy.get("delta")
    gamma = strategy.get("gamma")
    vega = strategy.get("vega")
    theta = strategy.get("theta")
    ivr = strategy.get("IV_Rank")
    ivr_display = f"{ivr:.1f}" if ivr is not None else "n.v.t."
    ivp = strategy.get("IV_Percentile")
    ivp_display = f"{ivp:.1f}" if ivp is not None else "n.v.t."
    print(
        f"→ Delta: {delta:+.3f} "
        f"Gamma: {gamma:+.3f} "
        f"Vega: {vega:+.3f} "
        f"Theta: {theta:+.3f} "
        f"IV Rank: {ivr_display} "
        f"IV Pctl: {ivp_display}"
    )
    iv_avg = strategy.get("avg_iv")
    hv = strategy.get("HV30")
    ivhv = strategy.get("iv_hv_spread")
    skew = strategy.get("skew")
    term = strategy.get("term_slope")
    parts = []
    if iv_avg is not None:
        parts.append(f"IV {iv_avg:.2%}")
    if hv is not None:
        parts.append(f"HV {hv:.2f}")
    if ivhv is not None:
        parts.append(f"IV-HV {ivhv:.2%}")
    if skew is not None:
        parts.append(f"Skew {skew*100:.1f}bp")
    if term is not None:
        parts.append(f"Term {term*100:.1f}bp")
    if parts:
        print("→ " + " | ".join(parts))
    days_line = []
    dte = strategy.get("days_to_expiry")
    dit = strategy.get("days_in_trade")
    if dte is not None:
        days_line.append(f"{dte}d tot exp")
    if dit is not None:
        days_line.append(f"{dit}d in trade")
    if days_line:
        print("→ " + " | ".join(days_line))
    if pnl is not None:
        margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
        rom = (pnl / margin_ref) * 100
        print(f"→ PnL: {pnl:+.2f} (ROM: {rom:+.1f}%)")
    spot = strategy.get("spot", 0)
    delta_dollar = strategy.get("delta_dollar")
    if delta is not None and spot and delta_dollar is not None:
        print(f"→ Delta exposure ≈ ${delta_dollar:,.0f} bij spot {spot}")

    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    if theta is not None and margin:
        theta_efficiency = abs(theta / margin) * 100
        if theta_efficiency < 0.5:
            rating = "⚠️ oninteressant"
        elif theta_efficiency < 1.5:
            rating = "🟡 acceptabel"
        elif theta_efficiency < 2.5:
            rating = "✅ goed"
        else:
            rating = "🟢 ideaal"
        print(
            f"→ Theta-rendement: {theta_efficiency:.2f}% per $1.000 margin - {rating}"
        )
    max_p = strategy.get("max_profit")
    max_l = strategy.get("max_loss")
    rr = strategy.get("risk_reward")
    if max_p is not None and max_l is not None:
        rr_disp = f" (R/R {rr:.2f})" if rr is not None else ""
        print(
            f"→ Max winst {_fmt_money(max_p)} | Max verlies {_fmt_money(max_l)}{rr_disp}"
        )

    alerts = strategy.get("alerts", [])
    # exit rule evaluation
    if rule:
        spot = strategy.get("spot")
        pnl = strategy.get("unrealizedPnL")
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
            pnl is not None
            and rule.get("target_profit_pct") is not None
            and rule.get("premium_entry")
        ):
            profit_pct = (pnl / (rule["premium_entry"] * 100)) * 100
            if profit_pct >= rule["target_profit_pct"]:
                alerts.append(
                    f"🚨 PnL {profit_pct:.1f}% >= target {rule['target_profit_pct']:.1f}%"
                )
    if alerts:
        for alert in alerts:
            print(alert)
    else:
        print("ℹ️ Geen directe aandachtspunten gedetecteerd")
    print("📎 Leg-details:")
    for leg in sort_legs(strategy.get("legs", [])):
        side = "Long" if leg.get("position", 0) > 0 else "Short"
        right = leg.get("right") or leg.get("type")
        symbol = SYMBOL_MAP.get((right, 1 if leg.get("position", 0) > 0 else -1), "▫️")

        qty = abs(leg.get("position", 0))
        print(
            f"  {symbol} {right} {leg.get('strike')} ({side}) - {qty} contract{'s' if qty != 1 else ''}"
        )

        d = leg.get("delta")
        g = leg.get("gamma")
        v = leg.get("vega")
        t = leg.get("theta")
        d_disp = f"{d:.3f}" if d is not None else "–"
        g_disp = f"{g:.3f}" if g is not None else "–"
        v_disp = f"{v:.3f}" if v is not None else "–"
        t_disp = f"{t:.3f}" if t is not None else "–"
        print(f"    Delta: {d_disp} Gamma: {g_disp} Vega: {v_disp} Theta: {t_disp}")
    print()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    json_output = None
    args = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json-output":
            if i + 1 >= len(argv):
                print(
                    "Gebruik: python strategy_dashboard.py positions.json [account_info.json] [--json-output PATH]"
                )
                return 1
            json_output = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--json-output="):
            json_output = arg.split("=", 1)[1]
            i += 1
            continue
        args.append(arg)
        i += 1

    if not args:
        print(
            "Gebruik: python strategy_dashboard.py positions.json [account_info.json] [--json-output PATH]"
        )
        return 1

    positions_file = args[0]
    account_file = (
        args[1] if len(args) > 1 else cfg_get("ACCOUNT_INFO_FILE", "account_info.json")
    )
    journal_file = cfg_get("JOURNAL_FILE", "journal.json")

    positions = load_positions(positions_file)
    account_info = load_account_info(account_file)
    journal = load_journal(journal_file)
    exit_rules = extract_exit_rules(journal_file)

    if account_info:
        print("=== Portfolio ===")
        print_account_overview(account_info)

    portfolio = compute_portfolio_greeks(positions)
    print("\n=== Portfolio Greeks ===")
    for k, v in portfolio.items():
        print(f"{k}: {v:.4f}")
    print()

    strategies = group_strategies(positions, journal)
    strategies.sort(
        key=lambda s: (
            s.get("trade_id") if s.get("trade_id") is not None else float("inf")
        )
    )
    compute_term_structure(strategies)
    type_counts = defaultdict(int)
    total_delta_dollar = 0.0
    total_vega = 0.0
    dtes = []
    total_pnl = 0.0
    total_margin = 0.0
    print("=== Open posities ===")
    for s in strategies:
        rule = exit_rules.get((s["symbol"], s["expiry"]))
        print_strategy(s, rule)
        type_counts[s.get("type")] += 1
        if s.get("delta_dollar") is not None:
            total_delta_dollar += s["delta_dollar"]
        if s.get("vega") is not None:
            total_vega += s["vega"]
        if s.get("days_to_expiry") is not None:
            dtes.append(s["days_to_expiry"])

        pnl_val = s.get("unrealizedPnL")
        margin_ref = s.get("init_margin") or s.get("margin_used") or 1000
        if pnl_val is not None:
            total_pnl += pnl_val
            total_margin += margin_ref

    global_alerts = []
    portfolio_vega = portfolio.get("Vega")
    if portfolio_vega is not None:
        abs_vega = abs(portfolio_vega)
        if abs_vega > 10000:
            global_alerts.append(
                "🚨 Totale Vega-exposure > 10.000 → gevoelig voor systematische vol-bewegingen"
            )
        elif abs_vega > 5000:
            global_alerts.append(
                "⚠️ Totale Vega-exposure > 5.000 → gevoelig voor systematische vol-bewegingen"
            )

    if strategies:
        total_strats = len(strategies)
        major_type, major_count = max(type_counts.items(), key=lambda x: x[1])
        pct = (major_count / total_strats) * 100
        if pct >= 80:
            global_alerts.append(
                f"⚠️ Strategieclustering: {major_count}x {major_type} van {total_strats} strategieën ({pct:.1f}%) → overweeg meer spreiding"
            )

    if global_alerts:
        for alert in global_alerts:
            print(alert)

    if strategies:
        print("=== Overzicht Open posities ===")
        for t, c in type_counts.items():
            print(f"{c}x {t}")
        print(f"Netto delta-dollar: ${total_delta_dollar:,.0f}")
        print(f"Totaal vega exposure: {total_vega:+.2f}")
        if dtes:
            avg_dte = sum(dtes) / len(dtes)
            print(f"Gemiddelde DTE: {avg_dte:.1f} dagen")
        if total_margin:
            avg_rom = (total_pnl / total_margin) * 100
            print(f"Gemiddeld ROM portfolio: {avg_rom:.1f}%")

    if json_output:
        strategies.sort(key=lambda s: (s["symbol"], s.get("expiry")))
        data = {
            "analysis_date": str(today()),
            "account_info": account_info,
            "portfolio_greeks": portfolio,
            "strategies": strategies,
            "global_alerts": global_alerts,
        }
        try:
            with open(json_output, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"❌ Kan niet schrijven naar {json_output}: {e}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
