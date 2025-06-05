"""Simulate portfolio exposure after spot and IV shifts."""

from typing import Any, Dict, List

from tomic.analysis.strategy import group_strategies
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from .common import prompt


def simulate_portfolio_response(
    strategies: List[Dict[str, Any]],
    spot_shift_pct: float = 0.02,
    iv_shift_pct: float = 0.05,
) -> Dict[str, Any]:
    """Simulate portfolio Greeks and PnL after spot/IV shifts."""
    totals = {"delta": 0.0, "vega": 0.0, "theta": 0.0}
    pnl_change = 0.0
    base_pnl = 0.0
    margin_total = 0.0

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
            price_change = (
                (delta * dS + 0.5 * gamma * dS**2 + vega * iv_shift_pct * iv)
                * mult
                * qty
            )
            pnl_change += price_change

    rom_before = (base_pnl / margin_total) * 100 if margin_total else None
    rom_after = ((base_pnl + pnl_change) / margin_total) * 100 if margin_total else None
    return {
        "totals": totals,
        "pnl_change": pnl_change,
        "rom_before": rom_before,
        "rom_after": rom_after,
    }


def load_positions(path: str) -> List[Dict[str, Any]]:
    """Load positions from ``path``."""
    return load_json(path)


def main(argv: List[str] | None = None) -> None:
    """Interactive scenario simulator."""
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else cfg_get("POSITIONS_FILE", "positions.json")

    while True:
        try:
            user_spot = prompt(
                "\nHoeveel procent spot shift wil je simuleren?\n(bijv. 2 voor +2%, -1 voor -1%): "
            )
            user_iv = prompt(
                "Hoeveel procent IV shift wil je simuleren?\n(bijv. 5 voor +5%, -3 voor -3%): "
            )
            spot_shift = float(user_spot) / 100
            iv_shift = float(user_iv) / 100
        except ValueError:
            print("❌ Ongeldige invoer, probeer opnieuw.")
            continue

        positions = load_positions(positions_file)
        strategies = group_strategies(positions)
        result = simulate_portfolio_response(strategies, spot_shift, iv_shift)

        print("\n=== Scenario Analyse ===")
        print(f"Spot shift: {spot_shift*100:.1f}% | IV shift: {iv_shift*100:.1f}%")
        totals = result["totals"]
        print(
            f"Delta: {totals['delta']:+.2f} | Vega: {totals['vega']:+.2f} | Theta: {totals['theta']:+.2f}"
        )
        pnl = result["pnl_change"]
        print(f"Geschatte PnL verandering: {pnl:+.2f}")
        if result["rom_before"] is not None and result["rom_after"] is not None:
            delta_rom = result["rom_after"] - result["rom_before"]
            print(
                f"ROM voor shift: {result['rom_before']:.1f}% → na shift: {result['rom_after']:.1f}% "
                f"({delta_rom:+.1f}%)"
            )

            # Interpretatie
            if totals["vega"] < -30 and iv_shift > 0:
                print("⚠️ Short Vega + stijgende IV → mogelijk verlies bij volaspike")
            if totals["vega"] > 30 and iv_shift < 0:
                print("⚠️ Long Vega + dalende IV → risico op volacrunch")
            if totals["delta"] > 0.2 and spot_shift < 0:
                print("⚠️ Bullish delta + daling → richtingverlies")
            if totals["delta"] < -0.2 and spot_shift > 0:
                print("⚠️ Bearish delta + stijging → richtingverlies")

        again = prompt("\nNog een scenario simuleren? (j/n): ").lower()
        if again != "j":
            break


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
