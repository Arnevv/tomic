"""Utilities for rendering journal entries."""

from __future__ import annotations

from typing import Any, Mapping

from tomic.services.strategy_pipeline import StrategyProposal


def render_journal_entries(candidate: StrategyProposal | Mapping[str, Any]) -> list[str]:
    """Return journal lines for ``candidate``."""

    proposal: StrategyProposal
    symbol: str | None = None
    strategy: str | None = None

    if isinstance(candidate, StrategyProposal):
        proposal = candidate
        strategy = candidate.strategy
    elif isinstance(candidate, Mapping):
        proposal_obj = candidate.get("proposal")
        if isinstance(proposal_obj, StrategyProposal):
            proposal = proposal_obj
        else:
            raise TypeError("candidate must contain a StrategyProposal under 'proposal'")
        symbol = candidate.get("symbol")
        strategy = candidate.get("strategy") or proposal.strategy
    else:
        raise TypeError("candidate must be StrategyProposal or mapping")

    symbol = symbol or getattr(proposal, "symbol", None)

    lines = [
        f"Symbol: {symbol or '—'}",
        f"Strategy: {strategy or '—'}",
        f"Credit: { _fmt_number(proposal.credit) }",
        f"Margin: { _fmt_number(proposal.margin) }",
        f"ROM: { _fmt_number(proposal.rom) }",
        f"PoS: { _fmt_number(proposal.pos) }",
        f"EV: { _fmt_number(proposal.ev) }",
    ]

    for leg in proposal.legs:
        side = "Short" if (leg.get("position") or 0) < 0 else "Long"
        typ = leg.get("type", "?")
        strike = leg.get("strike", "?")
        expiry = leg.get("expiry", "?")
        mid = leg.get("mid")
        mid_str = f"{mid:.2f}" if isinstance(mid, (int, float)) else ""
        lines.append(f"{side} {typ} {strike} {expiry} @ {mid_str}")

    return lines


def _fmt_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)
