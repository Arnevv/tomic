import json
from datetime import datetime
from typing import List, Dict

from strategy_dashboard import group_strategies


def simulate_portfolio_response(strategies: List[Dict], spot_shift_pct: float = 0.02,
                                iv_shift_pct: float = 0.05) -> Dict:
    """Simulate portfolio Greeks and PnL after spot/IV shifts."""
    totals = {"delta": 0.0, "vega": 0.0, "theta": 0.0}
    pnl_change = 0.0
    base_pnl = 0.0
    margin_total = 0.0
    today = datetime.utcnow()

    for strat in strategies:
        spot = strat.get("spot") or 0.0
        margin = strat.get("init_margin") or strat.get("margin_used") or 0.0
        margin_total += margin
        if strat.get("unrealizedPnL") is not None:
            base_pnl += strat.get("unrealizedPnL")
        for leg in strat.get("legs", []):
            qty = leg.get("position", 0)
            mult = float(leg.get("multiplier") or 1)
            delta = leg.get("delta") or 0.0
            gamma = leg.get("gamma") or 0.0
            vega = leg.get("vega") or 0.0
            theta = leg.get("theta") or 0.0
            iv = leg.get("iv") or strat.get("avg_iv") or 0.0
            dS = spot * spot_shift_pct
            new_delta = delta + gamma * dS
            totals["delta"] += new_delta * qty
            totals["vega"] += vega * qty * mult
            totals["theta"] += theta * qty * mult
            price_change = (delta * dS + 0.5 * gamma * dS ** 2 + vega * iv_shift_pct * iv) * mult * qty
            pnl_change += price_change

    rom_before = (base_pnl / margin_total) * 100 if margin_total else None
    rom_after = ((base_pnl + pnl_change) / margin_total) * 100 if margin_total else None
    return {
        "totals": totals,
        "pnl_change": pnl_change,
        "rom_before": rom_before,
        "rom_after": rom_after,
    }


def load_positions(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else "positions.json"
    spot_shift = float(argv[1]) if len(argv) > 1 else 0.02
    iv_shift = float(argv[2]) if len(argv) > 2 else 0.05

    positions = load_positions(positions_file)
    strategies = group_strategies(positions)
    result = simulate_portfolio_response(strategies, spot_shift, iv_shift)

    print("\n=== Scenario Analyse ===")
    print(f"Spot shift: {spot_shift*100:.1f}% | IV shift: {iv_shift*100:.1f}%")
    totals = result["totals"]
    print(f"Delta: {totals['delta']:+.2f} | Vega: {totals['vega']:+.2f} | Theta: {totals['theta']:+.2f}")
    pnl = result["pnl_change"]
    print(f"Geschatte PnL verandering: {pnl:+.2f}")
    if result["rom_before"] is not None:
        print(
            f"ROM voor shift: {result['rom_before']:.1f}% → na shift: {result['rom_after']:.1f}%")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
