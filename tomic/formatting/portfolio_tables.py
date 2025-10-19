"""Reusable table formatting helpers for the portfolio CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from tomic.reporting import format_dtes
from tomic.services.portfolio_service import Candidate, Factsheet
from tomic.services.strategy_pipeline import StrategyProposal


@dataclass(frozen=True)
class TableSpec:
    """Container describing tabular output for the CLI."""

    headers: Sequence[str]
    rows: Sequence[Sequence[object]]
    colalign: Sequence[str] | None = None


@dataclass(frozen=True)
class ProposalTableResult:
    """Formatted proposal table together with contextual flags."""

    table: TableSpec
    warn_missing_edge: bool
    missing_scenario: bool


def build_factsheet_table(factsheet: Factsheet) -> TableSpec:
    """Return table metadata for a :class:`Factsheet`."""

    def fmt(value: object, digits: int = 2) -> str:
        if value is None:
            return ""
        try:
            return f"{float(value):.{digits}f}"
        except Exception:  # pragma: no cover - defensive fallback
            return str(value)

    def fmt_pct(value: object | None) -> str:
        if value is None:
            return ""
        try:
            return f"{float(value) * 100:.0f}%"
        except Exception:  # pragma: no cover - defensive fallback
            return str(value)

    earn_str = ""
    if isinstance(factsheet.next_earnings, date):
        earn_str = factsheet.next_earnings.isoformat()
        if isinstance(factsheet.days_until_earnings, int):
            earn_str += f" ({factsheet.days_until_earnings}d)"

    rows = [
        ["Symbool", factsheet.symbol],
        ["Strategie", factsheet.strategy or ""],
        ["Spot", fmt(factsheet.spot)],
        ["IV", fmt(factsheet.iv)],
        ["HV20", fmt(factsheet.hv20)],
        ["HV30", fmt(factsheet.hv30)],
        ["HV90", fmt(factsheet.hv90)],
        ["HV252", fmt(factsheet.hv252)],
        ["Term m1/m2", fmt(factsheet.term_m1_m2, 2)],
        ["Term m1/m3", fmt(factsheet.term_m1_m3, 2)],
        ["IV Rank", fmt_pct(factsheet.iv_rank)],
        ["IV Perc", fmt_pct(factsheet.iv_percentile)],
        ["Skew", fmt(factsheet.skew, 2)],
        ["Earnings", earn_str],
        ["Criteria", factsheet.criteria or ""],
    ]

    return TableSpec(headers=("Veld", "Waarde"), rows=rows)


def build_evaluated_trades_table(
    evaluated_trades: Sequence[Mapping[str, object]]
) -> TableSpec:
    """Format the top evaluated trades for display."""

    rows: list[list[object]] = []
    for row in list(evaluated_trades)[:10]:
        rows.append(
            [
                row.get("expiry"),
                row.get("strike"),
                row.get("type"),
                (
                    f"{row.get('delta'):+.2f}"
                    if row.get("delta") is not None
                    else ""
                ),
                f"{row.get('edge'):.2f}" if row.get("edge") is not None else "",
                f"{row.get('pos'):.1f}%" if row.get("pos") is not None else "",
            ]
        )

    headers = ("Expiry", "Strike", "Type", "Delta", "Edge", "PoS")
    return TableSpec(headers=headers, rows=rows)


def build_proposals_table(
    proposals: Sequence[StrategyProposal],
) -> ProposalTableResult:
    """Create a table for ranked strategy proposals."""

    rows: list[list[object]] = []
    warn_edge = False
    no_scenario = False

    for prop in proposals:
        legs_desc = "; ".join(
            (
                f"{'S' if leg.get('position', 0) < 0 else 'L'}{leg.get('type')}{leg.get('strike')} "
                f"{leg.get('expiry', '?')}"
            )
            for leg in getattr(prop, "legs", [])
        )

        if any(leg.get("edge") is None for leg in getattr(prop, "legs", [])):
            warn_edge = True

        edge_vals = [
            float(leg.get("edge"))
            for leg in getattr(prop, "legs", [])
            if leg.get("edge") is not None
        ]
        if not edge_vals:
            edge_display = "—"
        elif len(edge_vals) < len(getattr(prop, "legs", [])):
            mn = min(edge_vals)
            edge_display = f"min={mn:.2f}" if mn < 0 else f"avg={sum(edge_vals)/len(edge_vals):.2f}"
        else:
            edge_display = f"{sum(edge_vals)/len(edge_vals):.2f}"

        label = None
        scenario_info = getattr(prop, "scenario_info", None)
        if isinstance(scenario_info, Mapping):
            label = scenario_info.get("scenario_label")
            if scenario_info.get("error") == "no scenario defined":
                no_scenario = True

        suffix = ""
        if getattr(prop, "profit_estimated", False):
            suffix = f" {label} (geschat)" if label else " (geschat)"

        ev_display = f"{prop.ev:.2f}{suffix}" if prop.ev is not None else "—"
        rom_display = f"{prop.rom:.2f}{suffix}" if prop.rom is not None else "—"

        rows.append(
            [
                f"{prop.score:.2f}" if prop.score is not None else "—",
                f"{prop.pos:.1f}" if prop.pos is not None else "—",
                ev_display,
                rom_display,
                edge_display,
                legs_desc,
            ]
        )

    headers = ("Score", "PoS", "EV", "ROM", "Edge", "Legs")
    return ProposalTableResult(
        table=TableSpec(headers=headers, rows=rows),
        warn_missing_edge=warn_edge,
        missing_scenario=no_scenario,
    )


def build_market_scan_table(candidates: Sequence[Candidate]) -> TableSpec:
    """Return table information for ranked market scan candidates."""

    def fmt_pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.0f}%"

    def fmt_ratio(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}"

    def fmt_money(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}"

    rows: list[list[object]] = []
    for idx, cand in enumerate(candidates, 1):
        prop = cand.proposal
        iv_rank_pct = float(cand.iv_rank) * 100 if cand.iv_rank is not None else None
        skew_fmt = "—"
        if cand.skew is not None:
            try:
                skew_fmt = f"{float(cand.skew):.2f}"
            except Exception:  # pragma: no cover - defensive fallback
                skew_fmt = "—"

        earnings = "—"
        earn_val = cand.next_earnings
        if isinstance(earn_val, date):
            earnings = earn_val.isoformat()
        elif isinstance(earn_val, str) and earn_val:
            earnings = earn_val

        mid_items = list(cand.mid_sources) if cand.mid_sources else []
        if mid_items:
            mid_sources = ",".join(
                "needs_refresh⚠" if item == "needs_refresh" else item for item in mid_items
            )
        else:
            mid_sources = "quotes"
        dte_summary = cand.dte_summary or format_dtes(prop.legs)

        rows.append(
            [
                idx,
                cand.symbol,
                cand.strategy,
                fmt_money(prop.score),
                fmt_money(prop.ev),
                fmt_ratio(cand.risk_reward),
                dte_summary,
                fmt_pct(iv_rank_pct),
                skew_fmt,
                fmt_pct(cand.bid_ask_pct),
                mid_sources,
                earnings,
            ]
        )

    headers = (
        "Nr",
        "Symbool",
        "Strategie",
        "Score",
        "EV",
        "R/R",
        "DTE",
        "IV Rank",
        "Skew",
        "Bid/Ask%",
        "MidSrc",
        "Earnings",
    )
    colalign = (
        "right",
        "left",
        "left",
        "right",
        "right",
        "right",
        "left",
        "right",
        "right",
        "right",
        "left",
        "left",
    )
    return TableSpec(headers=headers, rows=rows, colalign=colalign)


def build_market_overview_table(rows: Iterable[Sequence[object]]) -> TableSpec:
    """Table representation for the market overview recommendations."""

    headers = (
        "Nr",
        "Symbool",
        "Strategie",
        "IV",
        "Delta",
        "Vega",
        "Theta",
        "IV Rank (HV)",
        "Skew",
        "Earnings",
    )
    colalign = (
        "right",
        "left",
        "left",
        "right",
        "left",
        "left",
        "left",
        "right",
        "right",
        "left",
    )
    return TableSpec(headers=headers, rows=list(rows), colalign=colalign)

