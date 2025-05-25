import json
from typing import Dict, List


def check_entry_conditions(strategy: Dict, skew_threshold: float = 0.05,
                           iv_hv_min_spread: float = 0.03,
                           iv_rank_threshold: float = 30) -> List[str]:
    """Return a list of entry warnings for the given strategy."""
    alerts = []
    iv = strategy.get("avg_iv")
    hv = strategy.get("HV30")
    ivr = strategy.get("IV_Rank")
    skew = strategy.get("skew")

    # 📏 Correcte schaalvergelijking IV vs HV
    if iv is not None and hv is not None:
        hv_decimal = hv / 100 if hv > 1 else hv  # normalize HV to decimal
        diff = iv - hv_decimal
        if diff < 0:
            alerts.append(f"⏬ IV onder HV ({diff:.2%}) – liever niet instappen")
        elif diff < iv_hv_min_spread:
            alerts.append(f"⚠️ IV ligt slechts {diff:.2%} boven HV30")
        else:
            alerts.append("✅ IV significant boven HV30")

    # 📐 Skew-analyse
    if skew is not None and abs(skew) > skew_threshold:
        alerts.append(f"⚠️ Skew buiten range ({skew:+.2%})")

    # 📊 IV Rank-analyse
    if ivr is not None and ivr < iv_rank_threshold:
        alerts.append(f"⚠️ IV Rank {ivr:.1f} lager dan {iv_rank_threshold}")

    return alerts


def main(argv=None):
    if argv is None:
        argv = []
    positions_file = argv[0] if argv else "positions.json"

    from strategy_dashboard import group_strategies

    with open(positions_file, "r", encoding="utf-8") as f:
        positions = json.load(f)
    strategies = group_strategies(positions)
    for strat in strategies:
        warnings = check_entry_conditions(strat)
        if warnings:
            print(f"{strat['symbol']} ({strat['type']}):")
            for w in warnings:
                print(f" - {w}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
