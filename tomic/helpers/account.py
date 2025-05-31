"""Account-related helper functions shared across scripts."""

from __future__ import annotations


def _fmt_money(value):
    """Return value formatted as a dollar amount if possible."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return value or "-"


def print_account_overview(values: dict) -> None:
    """Print account status table with aligned columns."""
    net_liq = values.get("NetLiquidation")
    buying_power = values.get("BuyingPower")
    init_margin = values.get("InitMarginReq")
    excess_liq = values.get("ExcessLiquidity")
    gross_pos_val = values.get("GrossPositionValue")
    cushion = values.get("Cushion")

    margin_pct = None
    try:
        margin_pct = float(init_margin) / float(net_liq)
    except (TypeError, ValueError, ZeroDivisionError):
        margin_pct = None

    realized = values.get("RealizedProfit")

    rows = [
        (
            "💰 **Net Liquidation Value**",
            _fmt_money(net_liq),
            "Jouw actuele vermogen. Hoofdreferentie voor alles.",
        ),
        (
            "📈 **Realized Profit**",
            _fmt_money(realized) if realized is not None else "-",
            "Totaal gerealiseerd resultaat.",
        ),
        (
            "🏦 **Buying Power**",
            _fmt_money(buying_power),
            "Wat je direct mag inzetten voor nieuwe trades.",
        ),
        (
            "⚖️ **Used Margin (init)**",
            _fmt_money(init_margin)
            + (f" (≈ {margin_pct:.0%} van vermogen)" if margin_pct is not None else ""),
            "Hoeveel margin je in totaal verbruikt met je posities.",
        ),
        (
            "✅ **Excess Liquidity**",
            _fmt_money(excess_liq),
            "Hoeveel marge je veilig overhoudt. Buffer tegen margin calls.",
        ),
        ("**Gross Position Value**", _fmt_money(gross_pos_val), "–"),
        ("**Cushion**", str(cushion), "–"),
    ]

    col1 = max(len(r[0]) for r in rows + [("Label", "", "")])
    col2 = max(len(r[1]) for r in rows + [("", "Waarde", "")])
    col3 = max(len(r[2]) for r in rows + [("", "", "Waarom?")])
    header = (
        f"| {'Label'.ljust(col1)} | {'Waarde'.ljust(col2)} | {'Waarom?'.ljust(col3)} |"
    )
    sep = f"| {'-'*col1} | {'-'*col2} | {'-'*col3} |"
    print(header)
    print(sep)
    for label, value, reason in rows:
        print(f"| {label.ljust(col1)} | {value.ljust(col2)} | {reason.ljust(col3)} |")
