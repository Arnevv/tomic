"""Market overview analysis helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Tuple

from tomic import config as cfg
from tomic.cli.volatility_recommender import recommend_strategies
from tomic.helpers.dateutils import normalize_earnings_context
from tomic.helpers.strategy_config import (
    canonical_strategy_name,
    coerce_int,
    get_strategy_setting,
)


def categorize(exposure: str) -> str:
    """Categorize strategy exposure string into a broad bucket."""
    low = exposure.lower()
    if "vega long" in low:
        return "Vega Long"
    if "vega short" in low:
        return "Vega Short"
    if (
        "delta directional" in low
        or "delta positive" in low
        or "delta negative" in low
    ):
        return "Delta Directioneel"
    if "delta neutral" in low:
        return "Delta Neutraal"
    return "Overig"


def parse_greeks(expr: str) -> Tuple[str, str, str]:
    """Return simplified (vega, theta, delta) greeks description."""
    low = expr.lower()
    vega = "Neutraal"
    theta = "Neutraal"
    delta = "Neutraal"
    if "vega long" in low:
        vega = "Long"
    elif "vega short" in low:
        vega = "Short"
    if "theta long" in low:
        theta = "Long"
    elif "theta short" in low:
        theta = "Short"
    if "delta positive" in low or "delta directional" in low:
        delta = "Long"
    elif "delta negative" in low:
        delta = "Short"
    elif "delta neutral" in low:
        delta = "Neutraal"
    return vega, theta, delta

def build_market_overview(
    rows: List[List[Any]],
) -> Tuple[List[Dict[str, Any]], List[List[str]], Dict[str, Any]]:
    """Return recommendation records, formatted table rows and metadata.

    Parameters
    ----------
    rows:
        Output from the ``_load_market_rows`` helper in ``controlpanel``. Each
        entry should contain the metrics for a symbol.

    Returns
    -------
    (recs, table_rows, meta):
        ``recs`` is a list of recommendation dictionaries used by the CLI for
        interactive selection. ``table_rows`` contains formatted values ready to
        be rendered by :func:`tabulate`. ``meta`` contains additional metadata
        such as information about filtered recommendations.
    """
    recs: List[Dict[str, Any]] = []
    config_data = cfg.get("STRATEGY_CONFIG") or {}
    filtered_meta_sets: Dict[str, set[str]] = defaultdict(set)

    for r in rows:
        metrics = {
            "IV": r[2],
            "HV20": r[3],
            "HV30": r[4],
            "HV90": r[5],
            "HV252": r[6],
            "iv_rank": r[7],
            "iv_percentile": r[8],
            "iv_vs_hv20": (r[2] - r[3]) if r[2] is not None and r[3] is not None else None,
            "iv_vs_hv90": (r[2] - r[5]) if r[2] is not None and r[5] is not None else None,
            "term_m1_m3": r[10],
            "skew": r[11],
        }
        symbol = r[0]
        earnings_date, days_until = normalize_earnings_context(
            r[12] if len(r) > 12 else None,
            r[13] if len(r) > 13 else None,
            date.today,
        )
        matches = recommend_strategies(metrics)
        for rec in matches:
            crit = ", ".join(rec.get("criteria", []))
            strategy_name = rec.get("strategy")
            if not isinstance(strategy_name, str):
                continue
            min_days_value = get_strategy_setting(
                config_data,
                canonical_strategy_name(strategy_name),
                "min_days_until_earnings",
            )
            min_days = coerce_int(min_days_value)
            if (
                min_days is not None
                and min_days > 0
                and days_until is not None
                and days_until < min_days
            ):
                filtered_meta_sets[symbol].add(strategy_name)
                continue
            recs.append(
                {
                    "symbol": symbol,
                    "spot": r[1],
                    "iv": r[2],
                    "hv20": r[3],
                    "hv30": r[4],
                    "hv90": r[5],
                    "hv252": r[6],
                    "strategy": rec["strategy"],
                    "greeks": rec["greeks"],
                    "indication": rec.get("indication"),
                    "criteria": crit,
                    "term_m1_m2": r[9],
                    "term_m1_m3": r[10],
                    "next_earnings": earnings_date.isoformat() if earnings_date else r[12],
                    "days_until_earnings": days_until,
                    "iv_rank": r[7],
                    "iv_percentile": r[8],
                    "skew": r[11],
                    "category": categorize(rec["greeks"].lower()),
                }
            )

    filtered_meta: Dict[str, List[str]] = {
        symbol: sorted(strategies)
        for symbol, strategies in filtered_meta_sets.items()
    }

    if not recs:
        return [], [], {"earnings_filtered": filtered_meta}

    order = [
        "Vega Short",
        "Delta Directioneel",
        "Vega Long",
        "Delta Neutraal",
        "Overig",
    ]
    order_idx = {cat: i for i, cat in enumerate(order)}
    recs.sort(
        key=lambda r: (
            r["symbol"],
            order_idx.get(r["category"], 99),
            r["strategy"],
        )
    )

    table_rows: List[List[str]] = []
    for idx, rec in enumerate(recs, 1):
        vega, theta, delta = parse_greeks(rec["greeks"])
        sym = rec["symbol"]
        link = f"[{sym}](https://marketchameleon.com/Overview/{sym}/)"
        iv_val = f"{rec['iv']:.4f}" if isinstance(rec.get("iv"), (int, float)) else ""
        ivr = rec.get("iv_rank")
        iv_rank_val = f"{ivr * 100:.0f}" if isinstance(ivr, (int, float)) else ""
        skew_val = rec.get("skew")
        skew_str = f"{skew_val:.2f}" if isinstance(skew_val, (int, float)) else ""
        earnings = rec.get("next_earnings", "")
        table_rows.append(
            [
                idx,
                link,
                rec["strategy"],
                iv_val,
                delta,
                vega,
                theta,
                iv_rank_val,
                skew_str,
                earnings,
            ]
        )

    return recs, table_rows, {"earnings_filtered": filtered_meta}


__all__ = ["build_market_overview", "categorize", "parse_greeks"]
