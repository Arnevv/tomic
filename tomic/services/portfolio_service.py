"""Portfolio domain services used by CLI and other entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence

from ..logutils import logger
from ..reporting import to_float, format_dtes
from ..services.strategy_pipeline import StrategyProposal
from ._percent import normalize_percent
from .market_snapshot_service import ScanRow


@dataclass(frozen=True)
class Factsheet:
    """Structured representation of key metrics for a recommendation."""

    symbol: str
    strategy: str | None = None
    spot: float | None = None
    iv: float | None = None
    hv20: float | None = None
    hv30: float | None = None
    hv90: float | None = None
    hv252: float | None = None
    term_m1_m2: float | None = None
    term_m1_m3: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    skew: float | None = None
    criteria: str | None = None
    next_earnings: date | None = None
    days_until_earnings: int | None = None


@dataclass(frozen=True)
class Candidate:
    """Ranked trading candidate derived from a strategy proposal."""

    symbol: str
    strategy: str
    proposal: StrategyProposal
    score: float | None
    ev: float | None
    risk_reward: float | None
    dte_summary: str | None
    iv_rank: float | None
    iv_percentile: float | None
    skew: float | None
    bid_ask_pct: float | None
    mid_sources: tuple[str, ...]
    next_earnings: date | None
    metrics: Mapping[str, Any]
    spot: float | None
    spot_preview: bool = False
    spot_source: str | None = None
    spot_as_of: str | None = None
    spot_timestamp: str | None = None
    spot_baseline: bool = False
    mid_status: str = "tradable"
    needs_refresh: bool = False


class CandidateRankingError(RuntimeError):
    """Raised when candidate ranking cannot be completed."""


class PortfolioService:
    """Service responsible for portfolio related domain transformations."""

    def __init__(self, *, today_fn: Callable[[], date] | None = None) -> None:
        self._today = today_fn or date.today

    def build_factsheet(self, record: Mapping[str, Any]) -> Factsheet:
        """Convert a raw recommendation mapping into a :class:`Factsheet`."""

        symbol = str(record.get("symbol", ""))
        strategy = record.get("strategy")
        raw_next = record.get("next_earnings")
        earnings_date: date | None = None
        if isinstance(raw_next, date):
            earnings_date = raw_next
        elif isinstance(raw_next, str) and raw_next:
            try:
                earnings_date = datetime.strptime(raw_next, "%Y-%m-%d").date()
            except Exception:
                earnings_date = None

        raw_days = record.get("days_until_earnings")
        days_until: int | None = None
        if isinstance(raw_days, (int, float)):
            try:
                days_until = int(raw_days)
            except Exception:
                days_until = None
        if days_until is None and earnings_date is not None:
            try:
                days_until = (earnings_date - self._today()).days
            except Exception:
                days_until = None

        return Factsheet(
            symbol=symbol,
            strategy=strategy if isinstance(strategy, str) else None,
            spot=record.get("spot"),
            iv=record.get("iv"),
            hv20=record.get("hv20"),
            hv30=record.get("hv30"),
            hv90=record.get("hv90"),
            hv252=record.get("hv252"),
            term_m1_m2=record.get("term_m1_m2"),
            term_m1_m3=record.get("term_m1_m3"),
            iv_rank=normalize_percent(record.get("iv_rank")),
            iv_percentile=normalize_percent(record.get("iv_percentile")),
            skew=record.get("skew"),
            criteria=record.get("criteria") if isinstance(record.get("criteria"), str) else None,
            next_earnings=earnings_date,
            days_until_earnings=days_until,
        )

    def rank_candidates(
        self,
        symbols: Sequence[ScanRow],
        rules: Mapping[str, Any] | None = None,
    ) -> list[Candidate]:
        """Rank scan rows into candidates using proposal metrics."""

        if not isinstance(symbols, Sequence):
            raise CandidateRankingError("symbols must be a sequence of ScanRow entries")

        rules = rules or {}
        top_n = rules.get("top_n")
        max_candidates: int | None
        if top_n in {None, "", 0}:
            max_candidates = None
        else:
            try:
                max_candidates = int(top_n)
            except Exception as exc:  # pragma: no cover - invalid user config
                raise CandidateRankingError(f"invalid top_n value: {top_n!r}") from exc
            if max_candidates is not None and max_candidates < 0:
                max_candidates = None

        ranked: list[Candidate] = []

        for row in symbols:
            if not isinstance(row, ScanRow):
                logger.warning("Skipping non ScanRow entry: %r", row)
                continue
            proposal = row.proposal
            metrics = row.metrics or {}

            bid_ask_pct = self._avg_bid_ask_pct(proposal)
            risk_reward = self._risk_reward(proposal)
            mid_sources = self._mid_sources(proposal)
            needs_refresh = bool(getattr(proposal, "needs_refresh", False) or ("needs_refresh" in mid_sources))
            mid_status = mid_sources[0] if mid_sources else "tradable"
            next_earn = row.next_earnings
            if isinstance(next_earn, str):
                try:
                    next_earn = datetime.strptime(next_earn, "%Y-%m-%d").date()
                except Exception:
                    next_earn = None

            iv_rank = normalize_percent(metrics.get("iv_rank"))
            iv_pct = normalize_percent(metrics.get("iv_percentile"))
            skew_value = self._as_float(metrics.get("skew"))

            dte_summary = None
            try:
                dte_summary = format_dtes(proposal.legs)
            except Exception:
                dte_summary = None

            ranked.append(
                Candidate(
                    symbol=row.symbol,
                    strategy=row.strategy,
                    proposal=proposal,
                    score=self._as_float(proposal.score),
                    ev=self._as_float(proposal.ev),
                    risk_reward=risk_reward,
                    dte_summary=dte_summary,
                    iv_rank=iv_rank,
                    iv_percentile=iv_pct,
                    skew=skew_value,
                    bid_ask_pct=bid_ask_pct,
                    mid_sources=mid_sources,
                    next_earnings=next_earn,
                    metrics=metrics,
                    spot=row.spot,
                    spot_preview=getattr(row, "spot_preview", False),
                    spot_source=getattr(row, "spot_source", None),
                    spot_as_of=getattr(row, "spot_as_of", None),
                    spot_timestamp=getattr(row, "spot_timestamp", None),
                    spot_baseline=getattr(row, "spot_baseline", False),
                    mid_status=mid_status,
                    needs_refresh=needs_refresh,
                )
            )

        ranked.sort(key=lambda cand: cand.score or 0.0, reverse=True)

        if max_candidates is not None:
            ranked = ranked[:max_candidates]

        return ranked

    @staticmethod
    def _avg_bid_ask_pct(proposal: StrategyProposal) -> float | None:
        spreads: list[float] = []
        for leg in getattr(proposal, "legs", []):
            bid = to_float(leg.get("bid"))
            ask = to_float(leg.get("ask"))
            if bid is None or ask is None:
                continue
            mid = (bid + ask) / 2 if (bid is not None and ask is not None) else None
            base = ask if mid in {None, 0} else mid
            if base in {None, 0}:
                continue
            spreads.append(((ask - bid) / base) * 100)
        if not spreads:
            return None
        return sum(spreads) / len(spreads)

    @staticmethod
    def _risk_reward(proposal: StrategyProposal) -> float | None:
        profit = to_float(getattr(proposal, "max_profit", None))
        loss = to_float(getattr(proposal, "max_loss", None))
        if profit is None or loss in {None, 0}:
            return None
        risk = abs(loss)
        if risk <= 0:
            return None
        return profit / risk

    @staticmethod
    def _mid_sources(proposal: StrategyProposal) -> tuple[str, ...]:
        summary_raw = getattr(proposal, "fallback_summary", None)
        summary: dict[str, int]
        if isinstance(summary_raw, Mapping):
            summary = {
                str(source): int(summary_raw.get(source, 0) or 0)
                for source in summary_raw
            }
        else:
            summary = {}
            for leg in getattr(proposal, "legs", []):
                source = str(leg.get("mid_source") or "").strip()
                if not source:
                    source = str(leg.get("mid_fallback") or "").strip()
                if source == "parity":
                    source = "parity_true"
                if not source:
                    source = "true"
                summary[source] = summary.get(source, 0) + 1
        for key in ("true", "parity_true", "parity_close", "model", "close"):
            summary.setdefault(key, 0)

        preview_total = sum(summary.get(src, 0) for src in ("parity_close", "model", "close"))
        status = "advisory" if preview_total else "tradable"
        needs_refresh = bool(getattr(proposal, "needs_refresh", False) or preview_total > 0)

        tags: list[str] = [status]
        if needs_refresh:
            tags.append("needs_refresh")

        details = [
            f"{source}:{count}"
            for source, count in sorted(summary.items())
            if count > 0
        ]
        if not details:
            details.append("quotes")
        tags.extend(details)
        return tuple(tags)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and value:
                return float(value)
        except Exception:
            return None
        return None


__all__ = [
    "Candidate",
    "CandidateRankingError",
    "Factsheet",
    "PortfolioService",
    "ScanRow",
]
