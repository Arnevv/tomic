from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from tomic.analysis.greeks import compute_greeks_by_symbol
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.logutils import setup_logging


BENCHMARK_TABLE = [
    (
        "Delta",
        "Rond 0 (of licht directioneel)",
        "Te veel directional bias \u2192 herbalanceren",
        "Mogelijk weinig kans/edge",
    ),
    (
        "Theta",
        "Positief",
        "Onrealistisch hoge theta kan wijzen op te veel short premium",
        "Negatieve theta is ongewenst",
    ),
    (
        "Vega",
        "Licht negatief / neutraal",
        "Grote negatieve vega \u2192 kwetsbaar bij IV-stijging",
        "Positieve vega = long premium = risico bij tijdsverloop",
    ),
    (
        "Gamma",
        "Laag en gecontroleerd",
        "Hoge gamma = risico bij prijsbeweging",
        "Te laag kan wijzen op weinig responsiviteit bij beweging",
    ),
]


def load_positions(path: str) -> List[Dict[str, Any]]:
    """Load positions from ``path``."""
    data = load_json(path)
    return [p for p in data if p.get("position")]


def format_val(val: float) -> str:
    return f"{val:+.0f}"


def print_greeks_table(greeks: Dict[str, Dict[str, float]]) -> None:
    symbols = [s for s in greeks.keys() if s != "TOTAL"]
    headers = ["Symbool", "Delta", "Theta", "Vega", "Gamma"]
    col_w = [len(h) for h in headers]
    rows: List[List[str]] = []
    for sym in sorted(symbols):
        vals = greeks[sym]
        row = [
            sym,
            format_val(vals.get("Delta", 0.0)),
            format_val(vals.get("Theta", 0.0)),
            format_val(vals.get("Vega", 0.0)),
            format_val(vals.get("Gamma", 0.0)),
        ]
        rows.append(row)
        for i, c in enumerate(row):
            col_w[i] = max(col_w[i], len(c))
    totals = greeks.get("TOTAL", {k: 0.0 for k in headers[1:]})
    total_row = [
        "Totaal",
        format_val(totals.get("Delta", 0.0)),
        format_val(totals.get("Theta", 0.0)),
        format_val(totals.get("Vega", 0.0)),
        format_val(totals.get("Gamma", 0.0)),
    ]
    for i, c in enumerate(total_row):
        col_w[i] = max(col_w[i], len(c))

    header_line = (
        "| " + " | ".join(h.ljust(col_w[i]) for i, h in enumerate(headers)) + " |"
    )
    sep_line = "| " + " | ".join("-" * col_w[i] for i in range(len(headers))) + " |"
    print("\n=== PORTFOLIO GREEKS ===")
    print(header_line)
    print(sep_line)
    for row in rows:
        print(
            "| "
            + " | ".join(row[i].ljust(col_w[i]) for i in range(len(headers)))
            + " |"
        )
    bold_row = [f"**{c}**" if i == 0 else f"**{c}**" for i, c in enumerate(total_row)]
    print(
        "| "
        + " | ".join(bold_row[i].ljust(col_w[i]) for i in range(len(headers)))
        + " |"
    )


def print_benchmark() -> None:
    headers = ["Greek", "Richtlijn binnen TOMIC", "Te veel?", "Te weinig?"]
    col_w = [len(h) for h in headers]
    rows = []
    for greek, guide, high, low in BENCHMARK_TABLE:
        row = [greek, guide, high, low]
        rows.append(row)
        for i, c in enumerate(row):
            col_w[i] = max(col_w[i], len(c))
    header_line = (
        "| " + " | ".join(h.ljust(col_w[i]) for i, h in enumerate(headers)) + " |"
    )
    sep_line = "| " + " | ".join("-" * col_w[i] for i in range(len(headers))) + " |"
    print("\n=== TOMIC Benchmark ===")
    print(header_line)
    print(sep_line)
    for row in rows:
        print(
            "| "
            + " | ".join(row[i].ljust(col_w[i]) for i in range(len(headers)))
            + " |"
        )


def generate_alerts(greeks: Dict[str, Dict[str, float]]) -> List[str]:
    totals = greeks.get("TOTAL", {})
    alerts: List[str] = []
    delta = totals.get("Delta", 0.0)
    theta = totals.get("Theta", 0.0)
    vega = totals.get("Vega", 0.0)
    gamma_count = sum(1 for v in greeks.values() if abs(v.get("Gamma", 0.0)) > 10)
    if abs(delta) > 25:
        alerts.append(
            "⚠️ Alert: Je portfolio is sterk directioneel.\n💡 Strategie: overweeg Delta-neutrale spreads zoals iron_condor of calender."
        )
    if theta < 0:
        alerts.append(
            "⚠️ Alert: Je portfolio verliest waarde door tijdsverloop.\n💡 Strategie: overweeg short premium setups zoals iron_condor of ATM_iron_butterfly."
        )
    if vega < -100:
        alerts.append(
            "⚠️ Alert: Je bent kwetsbaar bij stijgende implied volatility.\n💡 Strategie: overweeg vega-neutrale of vega-positieve strategieën zoals calender of Ratio Backspreads."
        )
    if vega > 50:
        alerts.append(
            "⚠️ Alert: Je portfolio profiteert enkel bij IV-stijging.\n💡 Strategie: neutraliseer via Vertical Spreads of iron_condor."
        )
    if gamma_count > 1:
        alerts.append(
            "⚠️ Alert: Hoge gevoeligheid voor prijsbewegingen \u2192 verhoogd risico.\n💡 Strategie: verlaag gamma via bredere spreads of wings dichterbij halen."
        )
    return alerts


def main(argv: List[str] | None = None) -> None:
    """Display portfolio Greeks overview with alerts."""
    setup_logging()
    if argv is None:
        argv = []
    path = Path(argv[0]) if argv else Path(cfg_get("POSITIONS_FILE", "positions.json"))
    if not path.exists():
        print(f"❌ Kan positions niet vinden: {path}")
        return
    positions = load_positions(str(path))
    greeks = compute_greeks_by_symbol(positions)
    print_greeks_table(greeks)
    print_benchmark()
    alerts = generate_alerts(greeks)
    if alerts:
        print("\n=== Alerts ===")
        for msg in alerts:
            print(msg)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
