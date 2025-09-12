"""Market overview analysis helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from tomic.cli.volatility_recommender import recommend_strategies


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


def build_market_overview(rows: List[List[Any]]) -> Tuple[List[Dict[str, Any]], List[List[str]]]:
    """Return recommendation records and formatted table rows.

    Parameters
    ----------
    rows:
        Output from the ``_load_market_rows`` helper in ``controlpanel``. Each
        entry should contain the metrics for a symbol.

    Returns
    -------
    (recs, table_rows):
        ``recs`` is a list of recommendation dictionaries used by the CLI for
        interactive selection. ``table_rows`` contains formatted values ready to
        be rendered by :func:`tabulate`.
    """
    recs: List[Dict[str, Any]] = []
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
        matches = recommend_strategies(metrics)
        for rec in matches:
            crit = ", ".join(rec.get("criteria", []))
            recs.append(
                {
                    "symbol": r[0],
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
                    "next_earnings": r[12],
                    "iv_rank": r[7],
                    "iv_percentile": r[8],
                    "skew": r[11],
                    "category": categorize(rec["greeks"].lower()),
                }
            )

    if not recs:
        return [], []

    order = [
        "Vega Short",
        "Delta Directioneel",
        "Vega Long",
        "Delta Neutraal",
        "Overig",
    ]
    order_idx = {cat: i for i, cat in enumerate(order)}
    recs.sort(key=lambda r: (r["symbol"], order_idx.get(r["category"], 99)))

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

    return recs, table_rows


__all__ = ["build_market_overview", "categorize", "parse_greeks"]
