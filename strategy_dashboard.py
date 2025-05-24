import json
import sys
from collections import defaultdict
from statistics import mean


def load_positions(path: str):
    """Load positions JSON file and return as list."""
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
        strat.update(aggregate_metrics(legs))
        strat["alerts"] = generate_alerts(strat)
        strategies.append(strat)
    return strategies


def print_strategy(strategy):
    pnl = strategy.get("unrealizedPnL")
    color = "🟩" if pnl is not None and pnl >= 0 else "🟥"
    print(f"{color} {strategy['symbol']} – {strategy['type']}")
    delta = strategy.get("delta")
    vega = strategy.get("vega")
    theta = strategy.get("theta")
    ivr = strategy.get("IV_Rank")
    ivr_display = f"{ivr:.1f}" if ivr is not None else "n.v.t."
    print(
        f"→ Delta: {delta:+.2f} "
        f"Vega: {vega:+.1f} "
        f"Theta: {theta:+.1f} "
        f"IV Rank: {ivr_display}"
    )
    if pnl is not None:
        print(f"→ PnL: {pnl:+.2f}")
    for alert in strategy.get("alerts", []):
        print(alert)
    print()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("Gebruik: python strategy_dashboard.py positions.json")
        return
    positions = load_positions(argv[0])
    strategies = group_strategies(positions)
    for s in strategies:
        print_strategy(s)


if __name__ == "__main__":
    main()
