import json
import os
import sys
from collections import defaultdict
from statistics import mean
from datetime import datetime, timezone
import re


def _fmt_money(value):
    """Return value formatted as dollar amount if possible."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value) if value is not None else "-"


def print_account_overview(values: dict) -> None:
    """Print account status table with aligned columns."""
    net_liq = values.get("NetLiquidation")
    buying_power = values.get("BuyingPower")
    init_margin = values.get("InitMarginReq")
    excess_liq = values.get("ExcessLiquidity")
    gross_pos_val = values.get("GrossPositionValue")
    cushion = values.get("Cushion")

    margin_pct = None
    try:
        margin_pct = float(init_margin) / float(net_liq)
    except (TypeError, ValueError, ZeroDivisionError):
        margin_pct = None

    rows = [
        ("💰 **Net Liquidation Value**", _fmt_money(net_liq),
         "Jouw actuele vermogen. Hoofdreferentie voor alles."),
        ("🏦 **Buying Power**", _fmt_money(buying_power),
         "Wat je direct mag inzetten voor nieuwe trades."),
        (
            "⚖️ **Used Margin (init)**",
            _fmt_money(init_margin)
            + (f" (≈ {margin_pct:.0%} van vermogen)" if margin_pct is not None else ""),
            "Hoeveel margin je in totaal verbruikt met je posities.",
        ),
        ("✅ **Excess Liquidity**", _fmt_money(excess_liq),
         "Hoeveel marge je veilig overhoudt. Buffer tegen margin calls."),
        ("**Gross Position Value**", _fmt_money(gross_pos_val), "–"),
        ("**Cushion**", str(cushion), "–"),
    ]

    col1 = max(len(r[0]) for r in rows + [("Label", "", "")])
    col2 = max(len(r[1]) for r in rows + [("", "Waarde", "")])
    col3 = max(len(r[2]) for r in rows + [("", "", "Waarom?")])
    header = f"| {'Label'.ljust(col1)} | {'Waarde'.ljust(col2)} | {'Waarom?'.ljust(col3)} |"
    sep = f"| {'-'*col1} | {'-'*col2} | {'-'*col3} |"
    print(header)
    print(sep)
    for label, value, reason in rows:
        print(f"| {label.ljust(col1)} | {value.ljust(col2)} | {reason.ljust(col3)} |")


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
    """Load positions JSON file and return as list."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_account_info(path: str):
    """Load account info JSON file and return as dict."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_journal(path: str):
    """Load journal JSON if available."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
            if isinstance(rule.get("premium_entry"), (int, float)) and rule["premium_entry"]:
                rule["target_profit_pct"] = (
                    (rule["premium_entry"] - rule["premium_target"]) / rule["premium_entry"]
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
    if n == 4 and len(calls) == 2 and len(puts) == 2:
        return "Iron Condor"
    if n == 3 and len(puts) == 3:
        long_puts = [l for l in puts if l.get("position", 0) > 0]
        short_puts = [l for l in puts if l.get("position", 0) < 0]
        if len(long_puts) == 1 and len(short_puts) == 2:
            return "Put Ratio Spread"
    if n == 2:
        return "Vertical"
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
            alerts.append(
                f"🚨 Delta-dollar blootstelling {delta_dollar:,.0f} > $15k"
            )
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
            alerts.append("📈 Bullish + Long Vega in lage IV → time spread overwegen i.p.v. long call")
        if delta <= -0.15 and vega < -30 and ivr > 60:
            alerts.append("📉 Bearish + Short Vega in hoog vol klimaat → oppassen voor squeeze")

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
    margin = abs(strategy.get("cost_basis", 0))
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
        alerts.append("⏳ Minder dan 10 dagen tot expiratie – overweeg sluiten of doorrollen")
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
            put_short = [l for l in legs if (l.get("right") or l.get("type")) == "P" and l.get("position",0) < 0][0]
            put_long = [l for l in legs if (l.get("right") or l.get("type")) == "P" and l.get("position",0) > 0][0]
            call_short = [l for l in legs if (l.get("right") or l.get("type")) == "C" and l.get("position",0) < 0][0]
            call_long = [l for l in legs if (l.get("right") or l.get("type")) == "C" and l.get("position",0) > 0][0]
            width_put = abs(put_short.get("strike",0) - put_long.get("strike",0))
            width_call = abs(call_short.get("strike",0) - call_long.get("strike",0))
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


def group_strategies(positions, journal=None):
    grouped = defaultdict(list)
    for pos in positions:
        symbol = pos.get("symbol")
        expiry = pos.get("lastTradeDate") or pos.get("expiry") or pos.get("expiration")
        if not symbol or not expiry:
            continue
        grouped[(symbol, expiry)].append(pos)
    strategies = []
    journal_lookup = {}
    if journal:
        for trade in journal:
            key = (trade.get("Symbool"), trade.get("Expiry"))
            journal_lookup[key] = trade
    for (symbol, expiry), legs in grouped.items():
        strat = {
            "symbol": symbol,
            "expiry": expiry,
            "type": determine_strategy_type(legs),
            "legs": legs,
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
            strat["days_to_expiry"] = (
                exp_date - datetime.now(timezone.utc).date()
            ).days
        else:
            strat["days_to_expiry"] = None

        days_in_trade = None
        trade_data = journal_lookup.get((symbol, expiry))
        if trade_data:
            if trade_data.get("DaysInTrade") is not None:
                days_in_trade = trade_data.get("DaysInTrade")
            else:
                d_in = parse_date(trade_data.get("DatumIn"))
                if d_in:
                    days_in_trade = (datetime.now(timezone.utc).date() - d_in).days
            strat.update(parse_plan_metrics(trade_data.get("Plan", "")))
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

        strat["alerts"] = generate_alerts(strat)

        strategies.append(strat)
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
    ("P", 1): "🔵",   # long put
    ("C", -1): "🟡",  # short call
    ("C", 1): "🟢",   # long call
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
    print(
        f"→ Delta: {delta:+.3f} "
        f"Gamma: {gamma:+.3f} "
        f"Vega: {vega:+.3f} "
        f"Theta: {theta:+.3f} "
        f"IV Rank: {ivr_display}"
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
        print(f"→ PnL: {pnl:+.2f}")
    spot = strategy.get("spot", 0)
    delta_dollar = strategy.get("delta_dollar")
    if delta is not None and spot and delta_dollar is not None:
        print(f"→ Delta exposure ≈ ${delta_dollar:,.0f} bij spot {spot}")
    
    margin = strategy.get("margin_used", 1000)
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
        print(f"  {symbol} {right} {leg.get('strike')} ({side}) - {qty} contract{'s' if qty != 1 else ''}")

        d = leg.get('delta')
        g = leg.get('gamma')
        v = leg.get('vega')
        t = leg.get('theta')
        d_disp = f"{d:.3f}" if d is not None else "–"
        g_disp = f"{g:.3f}" if g is not None else "–"
        v_disp = f"{v:.3f}" if v is not None else "–"
        t_disp = f"{t:.3f}" if t is not None else "–"
        print(f"    Delta: {d_disp} Gamma: {g_disp} Vega: {v_disp} Theta: {t_disp}")
    print()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("Gebruik: python strategy_dashboard.py positions.json [account_info.json]")
        return
    positions_file = argv[0]
    account_file = argv[1] if len(argv) > 1 else "account_info.json"
    journal_file = "journal.json"

    positions = load_positions(positions_file)
    account_info = load_account_info(account_file)
    journal = load_journal(journal_file)
    exit_rules = extract_exit_rules(journal_file)
        
    if account_info:
        print_account_overview(account_info)

    portfolio = compute_portfolio_greeks(positions)
    print("\n📐 Portfolio Greeks:")
    for k, v in portfolio.items():
        print(f"{k}: {v:.4f}")
    print()


    strategies = group_strategies(positions, journal)
    compute_term_structure(strategies)
    type_counts = defaultdict(int)
    total_delta_dollar = 0.0
    total_vega = 0.0
    dtes = []
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

    if strategies:
        print("=== Overzicht ===")
        for t, c in type_counts.items():
            print(f"{c}x {t}")
        print(f"Netto delta-dollar: ${total_delta_dollar:,.0f}")
        print(f"Totaal vega exposure: {total_vega:+.2f}")
        if dtes:
            avg_dte = sum(dtes) / len(dtes)
            print(f"Gemiddelde DTE: {avg_dte:.1f} dagen")


if __name__ == "__main__":
    main()
