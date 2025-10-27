from __future__ import annotations

"""Viewmodel construction helpers for proposal details."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, MutableMapping, Sequence

from ..helpers.dateutils import normalize_earnings_context, parse_date
from ..logutils import logger, normalize_reason
from .strategy_pipeline import StrategyProposal


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN check without importing math
        return None
    return number


def _first_expiry(legs: Sequence[Mapping[str, Any]]) -> str | None:
    for leg in legs:
        expiry = leg.get("expiry")
        if isinstance(expiry, str) and expiry:
            return expiry
    return None


def _normalize_symbol(
    symbol: str | None,
    legs: Sequence[Mapping[str, Any]],
) -> str | None:
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip().upper()
    for leg in legs:
        for key in ("symbol", "underlying", "ticker", "root", "root_symbol"):
            value = leg.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
    return None


def _normalize_reasons(reasons: Sequence[Any]) -> tuple[Any, ...]:
    normalized: list[Any] = []
    for reason in reasons:
        try:
            normalized.append(normalize_reason(reason))
        except Exception:
            logger.debug("Could not normalize reason", exc_info=True)
            normalized.append(reason)
    return tuple(normalized)


@dataclass(frozen=True)
class ProposalCore:
    """Minimal immutable description of a proposal for downstream consumers."""

    symbol: str | None
    strategy: str | None
    expiry: str | None
    strikes: tuple[float | None, ...]
    legs: tuple[Mapping[str, Any], ...]
    greeks: Mapping[str, float | None]
    pricing_meta: Mapping[str, Any]


def build_proposal_core(
    proposal: StrategyProposal,
    *,
    symbol: str | None = None,
    entry: Mapping[str, Any] | None = None,
) -> ProposalCore:
    """Return an immutable snapshot with the essential proposal data."""

    legs = tuple(
        leg if isinstance(leg, Mapping) else {}
        for leg in proposal.legs
    )
    expiry = _first_expiry(legs)
    strikes: list[float | None] = []
    for leg in legs:
        strikes.append(_safe_float(leg.get("strike")))

    totals: dict[str, float | None] = {}
    for greek in ("delta", "gamma", "vega", "theta"):
        values: list[float] = []
        for leg in legs:
            val = _safe_float(leg.get(greek))
            if val is not None:
                values.append(val)
        totals[greek] = sum(values) if values else None

    pricing_meta: dict[str, Any] = {
        "credit": proposal.credit,
        "margin": proposal.margin,
        "max_profit": proposal.max_profit,
        "max_loss": proposal.max_loss,
        "pos": proposal.pos,
        "ev": proposal.ev,
        "rom": proposal.rom,
        "score": proposal.score,
        "edge": proposal.edge,
    }
    if isinstance(entry, Mapping):
        raw_meta = entry.get("pricing_meta")
        if isinstance(raw_meta, Mapping):
            pricing_meta.update(raw_meta)

    resolved_symbol = _normalize_symbol(symbol, legs)

    strategy_value = proposal.strategy if hasattr(proposal, "strategy") else None
    if not isinstance(strategy_value, str):
        strategy_value = None

    return ProposalCore(
        symbol=resolved_symbol,
        strategy=strategy_value,
        expiry=expiry,
        strikes=tuple(strikes),
        legs=legs,
        greeks=totals,
        pricing_meta=pricing_meta,
    )


@dataclass(frozen=True)
class ProposalLegVM:
    expiry: str | None
    strike: float | None
    option_type: str | None
    position: int | None
    bid: float | None
    ask: float | None
    mid: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    vega: float | None
    theta: float | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class EarningsVM:
    next_earnings: date | None
    days_until: int | None
    expiry_gap_days: int | None
    occurs_before_expiry: bool | None


@dataclass(frozen=True)
class ProposalSummaryVM:
    credit: float | None
    margin: float | None
    max_profit: float | None
    max_loss: float | None
    breakevens: tuple[float, ...]
    pos: float | None
    ev: float | None
    rom: float | None
    score: float | None
    risk_reward: float | None
    profit_estimated: bool
    scenario_label: str | None
    scenario_error: str | None
    iv_rank: float | None
    iv_percentile: float | None
    hv20: float | None
    hv30: float | None
    hv90: float | None
    hv252: float | None
    edge: float | None
    greeks: Mapping[str, float | None]


@dataclass(frozen=True)
class ProposalVM:
    """Structured view of proposal details for presentation layers."""

    core: ProposalCore
    legs: tuple[ProposalLegVM, ...]
    warnings: tuple[str, ...]
    missing_quotes: tuple[str, ...]
    summary: ProposalSummaryVM
    earnings: EarningsVM
    accepted: bool | None
    reasons: tuple[Any, ...]
    credit_capped: bool
    has_missing_edge: bool
def _parse_earnings_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            parsed = parse_date(value)
        except Exception:
            return None
        return parsed
    return None


def _compute_earnings_summary(
    earnings_ctx: Mapping[str, Any] | None,
    legs: Sequence[Mapping[str, Any]],
) -> EarningsVM:
    raw_date = None
    raw_days = None
    if isinstance(earnings_ctx, Mapping):
        raw_date = earnings_ctx.get("next_earnings_date") or earnings_ctx.get("next_earnings")
        raw_days = earnings_ctx.get("days_until_earnings") or earnings_ctx.get("earnings_dte")

    next_date, days_until = normalize_earnings_context(raw_date, raw_days, date.today)

    expiry_value = _first_expiry(legs)
    expiry_date = _parse_earnings_date(expiry_value)
    occurs_before = None
    gap_days = None
    if next_date is not None and expiry_date is not None:
        gap_days = (expiry_date - next_date).days
        occurs_before = expiry_date <= next_date

    return EarningsVM(
        next_earnings=next_date,
        days_until=days_until,
        expiry_gap_days=gap_days,
        occurs_before_expiry=occurs_before,
    )


def _build_leg_vm(leg: Mapping[str, Any]) -> ProposalLegVM:
    bid = _safe_float(leg.get("bid"))
    ask = _safe_float(leg.get("ask"))
    mid = _safe_float(leg.get("mid"))
    warnings: list[str] = []
    if bid is None or ask is None:
        warnings.append(
            f"⚠️ Bid/ask ontbreekt voor strike {leg.get('strike')}"
        )
    if mid is not None and bid is not None and abs(mid - bid) < 1e-6:
        warnings.append(
            f"⚠️ Midprijs gelijk aan bid voor strike {leg.get('strike')}"
        )
    if mid is not None and ask is not None and abs(mid - ask) < 1e-6:
        warnings.append(
            f"⚠️ Midprijs gelijk aan ask voor strike {leg.get('strike')}"
        )
    missing_metrics = leg.get("missing_metrics") or []
    if missing_metrics:
        metrics_list = ", ".join(str(m) for m in missing_metrics)
        msg = f"⚠️ Ontbrekende metrics voor strike {leg.get('strike')}: {metrics_list}"
        if leg.get("metrics_ignored"):
            msg += " (toegestaan)"
        warnings.append(msg)

    position = None
    try:
        position_val = leg.get("position")
        if position_val is not None:
            position = int(position_val)
    except Exception:
        position = None

    return ProposalLegVM(
        expiry=leg.get("expiry"),
        strike=_safe_float(leg.get("strike")),
        option_type=leg.get("type"),
        position=position,
        bid=bid,
        ask=ask,
        mid=mid,
        iv=_safe_float(leg.get("iv")),
        delta=_safe_float(leg.get("delta")),
        gamma=_safe_float(leg.get("gamma")),
        vega=_safe_float(leg.get("vega")),
        theta=_safe_float(leg.get("theta")),
        warnings=tuple(warnings),
    )


def _calculate_risk_reward(proposal: StrategyProposal) -> float | None:
    profit = _safe_float(proposal.max_profit)
    loss = _safe_float(proposal.max_loss)
    if profit is None or loss in (None, 0.0):
        return None
    risk = abs(loss)
    if risk <= 0:
        return None
    return profit / risk


def _collect_breakevens(proposal: StrategyProposal) -> tuple[float, ...]:
    values: list[float] = []
    if not proposal.breakevens:
        return tuple(values)
    for value in proposal.breakevens:
        val = _safe_float(value)
        if val is not None:
            values.append(val)
    return tuple(values)


def build_proposal_viewmodel(
    candidate: Any,
    earnings_ctx: Mapping[str, Any] | None = None,
) -> ProposalVM:
    """Return a :class:`ProposalVM` with normalized proposal details."""

    if isinstance(candidate, StrategyProposal):
        proposal = candidate
        core = build_proposal_core(proposal)
        reasons: tuple[Any, ...] = ()
        missing_quotes: tuple[str, ...] = ()
        accepted: bool | None = None
    else:
        proposal = getattr(candidate, "proposal", None)
        if proposal is None or not hasattr(proposal, "legs"):
            raise TypeError("candidate lacks StrategyProposal data")
        core = getattr(candidate, "core", None)
        if not isinstance(core, ProposalCore):
            source = getattr(candidate, "source", None)
            entry: Mapping[str, Any] | None = None
            symbol = None
            if isinstance(source, Mapping):  # pragma: no cover - defensive
                entry = source.get("entry")  # type: ignore[assignment]
                symbol = source.get("symbol")
            else:
                symbol = getattr(source, "symbol", None)
                entry = getattr(source, "entry", None)
            core = build_proposal_core(
                proposal,
                symbol=symbol,
                entry=entry if isinstance(entry, Mapping) else None,
            )
        reasons = _normalize_reasons(getattr(candidate, "reasons", ()))
        missing_quotes = tuple(getattr(candidate, "missing_quotes", ()))
        accepted = getattr(candidate, "accepted", None)
        if accepted is None:
            name = candidate.__class__.__name__
            if name == "Proposal":
                accepted = True
            elif name == "Rejection":
                accepted = False

    legs_vm = tuple(_build_leg_vm(leg) for leg in core.legs)
    warnings = [warning for leg in legs_vm for warning in leg.warnings]

    missing_edge = False
    for leg in proposal.legs:
        if not isinstance(leg, Mapping):
            continue
        if leg.get("edge") is None:
            logger.debug(
                "[EDGE missing] %s %s %s %s",
                leg.get("position"),
                leg.get("type"),
                leg.get("strike"),
                leg.get("expiry"),
            )
            missing_edge = True
    if missing_edge:
        warnings.append("⚠️ Eén of meerdere edges niet beschikbaar")
    if missing_quotes:
        warnings.append("⚠️ Geen verse quotes voor: " + ", ".join(missing_quotes))
    if getattr(proposal, "credit_capped", False):
        warnings.append(
            "⚠️ Credit afgetopt op theoretisch maximum vanwege ontbrekende bid/ask"
        )

    summary = ProposalSummaryVM(
        credit=_safe_float(proposal.credit),
        margin=_safe_float(proposal.margin),
        max_profit=_safe_float(proposal.max_profit),
        max_loss=_safe_float(proposal.max_loss),
        breakevens=_collect_breakevens(proposal),
        pos=_safe_float(proposal.pos),
        ev=_safe_float(proposal.ev),
        rom=_safe_float(proposal.rom),
        score=_safe_float(proposal.score),
        risk_reward=_calculate_risk_reward(proposal),
        profit_estimated=bool(getattr(proposal, "profit_estimated", False)),
        scenario_label=(
            proposal.scenario_info.get("scenario_label")
            if isinstance(getattr(proposal, "scenario_info", None), MutableMapping)
            else None
        ),
        scenario_error=(
            proposal.scenario_info.get("error")
            if isinstance(getattr(proposal, "scenario_info", None), MutableMapping)
            else None
        ),
        iv_rank=_safe_float(getattr(proposal, "iv_rank", None)),
        iv_percentile=_safe_float(getattr(proposal, "iv_percentile", None)),
        hv20=_safe_float(getattr(proposal, "hv20", None)),
        hv30=_safe_float(getattr(proposal, "hv30", None)),
        hv90=_safe_float(getattr(proposal, "hv90", None)),
        hv252=_safe_float(getattr(proposal, "hv252", None)),
        edge=_safe_float(getattr(proposal, "edge", None)),
        greeks=core.greeks,
    )

    earnings = _compute_earnings_summary(earnings_ctx, core.legs)

    return ProposalVM(
        core=core,
        legs=legs_vm,
        warnings=tuple(warnings),
        missing_quotes=missing_quotes,
        summary=summary,
        earnings=earnings,
        accepted=accepted,
        reasons=reasons,
        credit_capped=bool(getattr(proposal, "credit_capped", False)),
        has_missing_edge=missing_edge,
    )
