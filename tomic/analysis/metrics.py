from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Sequence

import math
import statistics

from tomic.helpers.dateutils import parse_date
from tomic.helpers.account import _fmt_money


def compute_term_structure(strategies: Iterable[Dict[str, Any]]) -> None:
    """Annotate each strategy dict with a term structure slope."""
    by_symbol: Dict[str, list[tuple[Any, float, Dict[str, Any]]]] = defaultdict(list)
    for strat in strategies:
        exp = parse_date(strat.get("expiry"))
        iv = strat.get("avg_iv")
        if exp and iv is not None:
            by_symbol[strat["symbol"]].append((exp, iv, strat))

    for items in by_symbol.values():
        items.sort(key=lambda x: x[0])
        for i, (_, iv, strat) in enumerate(items):
            if i + 1 < len(items):
                next_iv = items[i + 1][1]
                strat["term_slope"] = next_iv - iv
            else:
                strat["term_slope"] = None


def render_kpi_box(strategy: Dict[str, Any]) -> str:
    """Return a formatted KPI summary for a strategy dict."""
    rom = strategy.get("rom")
    theta = strategy.get("theta")
    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    max_p = strategy.get("max_profit")
    max_l = strategy.get("max_loss")
    rr = strategy.get("risk_reward")

    rom_str = f"{rom:+.1f}%" if rom is not None else "n.v.t."
    theta_eff = None
    rating = ""
    if theta is not None and margin:
        theta_eff = abs(theta / margin) * 100
        if theta_eff < 0.5:
            rating = "⚠️"
        elif theta_eff < 1.5:
            rating = "🟡"
        elif theta_eff < 2.5:
            rating = "✅"
        else:
            rating = "🟢"
    theta_str = f"{rating} {theta_eff:.2f}%/k" if theta_eff is not None else "n.v.t."
    max_p_str = _fmt_money(max_p) if max_p is not None else "-"
    max_l_str = _fmt_money(max_l) if max_l is not None else "-"
    rr_str = f"{rr:.2f}" if rr is not None else "n.v.t."
    return (
        f"ROM: {rom_str} | Theta-efficiëntie: {theta_str} | "
        f"Max winst: {max_p_str} | Max verlies: {max_l_str} | R/R: {rr_str}"
    )


def historical_volatility(
    closes: Sequence[float], *, window: int = 30, trading_days: int = 252
) -> float | None:
    """Return annualised historical volatility in percent.

    Parameters
    ----------
    closes:
        Daily closing prices with the most recent value last.
    window:
        Number of returns to include, default 30.
    trading_days:
        Number of trading days per year used for annualisation.
    """
    if len(closes) < 2:
        return None
    returns = [math.log(c2 / c1) for c1, c2 in zip(closes[:-1], closes[1:])]
    if not returns:
        return None
    window_returns = returns[-window:]
    if len(window_returns) < 2:
        return None
    hv = statistics.stdev(window_returns) * math.sqrt(trading_days) * 100
    return hv


def average_true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    period: int = 14,
) -> float | None:
    """Return the average true range over ``period`` days."""
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        hi = highs[i]
        lo = lows[i]
        prev_close = closes[i - 1]
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
    if not trs:
        return None
    period_trs = trs[-period:]
    return sum(period_trs) / len(period_trs)


__all__ = [
    "compute_term_structure",
    "render_kpi_box",
    "historical_volatility",
    "average_true_range",
]
