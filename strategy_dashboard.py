import json
import os
import sys
from collections import defaultdict
from statistics import mean


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
    for leg in legs:
        qty = leg.get("position", 0)
        mult = float(leg.get("multiplier") or 1)
        for g in ["delta", "gamma", "vega", "theta"]:
            val = leg.get(g)
            if val is not None:
                if g == "delta":
                    metrics[g] += val * qty
                else:
                    metrics[g] += val * qty * mult
        if leg.get("unrealizedPnL") is not None:
            metrics["unrealizedPnL"] += leg["unrealizedPnL"]
        if leg.get("avgCost") is not None:
            metrics["cost_basis"] += leg["avgCost"] * qty * mult
        if leg.get("IV_Rank") is not None:
            iv_ranks.append(leg["IV_Rank"])
        if leg.get("HV30") is not None:
            hv_values.append(leg["HV30"])
        if leg.get("ATR14") is not None:
            atr_values.append(leg["ATR14"])
    metrics["IV_Rank"] = mean(iv_ranks) if iv_ranks else None
    metrics["HV30"] = max(hv_values) if hv_values else None
    metrics["ATR14"] = max(atr_values) if atr_values else None
    return metrics


def generate_alerts(strategy):
    alerts = []
    # 🔹 Delta-analyse
    delta = strategy.get("delta")
    if delta is not None:
        if delta > 0.3:
            alerts.append("📈 Sterk bullish (Delta > +0.30)")
        elif delta > 0.15:
            alerts.append("📈 Licht bullish")
        elif delta < -0.3:
            alerts.append("📉 Sterk bearish (Delta < –0.30)")
        elif delta < -0.15:
            alerts.append("📉 Licht bearish")

    # 🔹 Vega en IV Rank-analyse
    vega = strategy.get("vega")
    ivr = strategy.get("IV_Rank")
    if vega is not None and ivr is not None:
        if vega < -30 and ivr > 60:
            alerts.append("⚠️ Short Vega in hoog vol klimaat — risico op squeeze")
        elif vega < -30 and ivr < 30:
            alerts.append("✅ Short Vega in lage IV — condorvriendelijk klimaat")
        elif vega > 30 and ivr < 30:
            alerts.append("⚠️ Long Vega in lage IV — kan dodelijk zijn bij crush")

    # bestaande winstneem-alert
    if strategy.get("unrealizedPnL") is not None:
        cost_basis = abs(strategy.get("cost_basis", 0))
        if cost_basis and strategy.get("theta") is not None:
            if strategy["unrealizedPnL"] > 0.7 * cost_basis and strategy["theta"] > 0:
                alerts.append("✅ Overweeg winstnemen (>70% premie afgebouwd)")

    # 🔹 Eventueel aanvullen met trend/spotalerts later
    return alerts


def group_strategies(positions):
    grouped = defaultdict(list)
    for pos in positions:
        symbol = pos.get("symbol")
        expiry = pos.get("lastTradeDate") or pos.get("expiry") or pos.get("expiration")
        if not symbol or not expiry:
            continue
        grouped[(symbol, expiry)].append(pos)
    strategies = []
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
        strat["alerts"] = generate_alerts(strat)
        strategies.append(strat)
    return strategies


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



def print_strategy(strategy):
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
    if pnl is not None:
        print(f"→ PnL: {pnl:+.2f}")
    spot = strategy.get("spot", 0)
    if delta is not None and spot:
        delta_dollar = delta * spot
        print(f"→ Delta exposure ≈ ${delta_dollar:,.0f} bij spot {spot}")

    margin = strategy.get("margin_used", 1000)
    if theta is not None and margin:
        theta_efficiency = (theta / margin) * 100
        print(f"→ Theta-rendement: {theta_efficiency:.2f}% per $1.000 margin")
    for alert in strategy.get("alerts", []):
        print(alert)
    print("📎 Leg-details:")
    for leg in sort_legs(strategy.get("legs", [])):
        side = "Long" if leg.get("position", 0) > 0 else "Short"
        right = leg.get("right") or leg.get("type")
        symbol = SYMBOL_MAP.get((right, 1 if leg.get("position", 0) > 0 else -1), "▫️")
        print(f"  {symbol} {right} {leg.get('strike')} ({side})")
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

    positions = load_positions(positions_file)
    account_info = load_account_info(account_file)        
        
    if account_info:
        print("🏦 Accountoverzicht:")
    for key in ["NetLiquidation", "BuyingPower", "ExcessLiquidity"]:
        if key in account_info:
            print(f"{key}: {account_info[key]}")
    print()


    strategies = group_strategies(positions)
    for s in strategies:
        print_strategy(s)


if __name__ == "__main__":
    main()
