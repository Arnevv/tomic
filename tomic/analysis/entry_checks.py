"""Entry condition analysis utilities."""

from typing import Any, Dict, List


def check_entry_conditions(
    strategy: Dict[str, Any],
    skew_threshold: float = 0.05,
    iv_hv_min_spread: float = 0.03,
    iv_rank_threshold: float = 30,
) -> List[str]:
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
            alerts.append(f"\u26A0\uFE0F IV ligt slechts {diff:.2%} boven HV30")
        else:
            alerts.append("\u2705 IV significant boven HV30")

    # 📐 Skew-analyse
    if skew is not None and abs(skew) > skew_threshold:
        alerts.append(f"\u26A0\uFE0F Skew buiten range ({skew:+.2%})")

    # 📊 IV Rank-analyse
    if ivr is not None and ivr < iv_rank_threshold:
        alerts.append(f"\u26A0\uFE0F IV Rank {ivr:.1f} lager dan {iv_rank_threshold}")

    return alerts
