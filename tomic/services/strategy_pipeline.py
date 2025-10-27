from __future__ import annotations

"""Strategy generation pipeline used by CLI and services."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from ..metrics import calculate_edge, calculate_ev, calculate_pos, calculate_rom
from ..strategy.models import StrategyContext, StrategyProposal
from ..strategy_candidates import generate_strategy_candidates
from ..strike_selector import FilterConfig, StrikeSelector, filter_by_expiry
from .utils import resolve_config_getter
from ..loader import load_strike_config
from ..logutils import combo_symbol_context, logger
from ..mid_resolver import MidResolver, MidUsageSummary, build_mid_resolver
from ..utils import get_option_mid_price, normalize_leg, resolve_symbol
from ..helpers.numeric import safe_float
from ..helpers.bs_utils import estimate_model_price
from ..helpers.dateutils import parse_date
from ..helpers.strategy_config import (
    canonical_strategy_name,
    coerce_int,
    get_strategy_setting,
)
from ..strategy.reasons import (
    ReasonCategory,
    ReasonDetail,
    dedupe_reasons,
    make_reason,
)
from ..strategy.reason_engine import ReasonEngine


ConfigGetter = Callable[[str, Any | None], Any]


@dataclass
class RejectionSummary:
    """Aggregated rejection information."""

    by_filter: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)
    by_strategy: dict[str, list[ReasonDetail]] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineRunResult:
    """Container returned by :func:`run` for downstream consumers."""

    context: StrategyContext
    proposals: list[StrategyProposal]
    summary: RejectionSummary
    filtered_chain: list[MutableMapping[str, Any]]


class PipelineRunError(RuntimeError):
    """Raised when a helper managed pipeline run fails."""


def run(
    pipeline: "StrategyPipeline",
    *,
    symbol: str,
    strategy: str,
    option_chain: Sequence[Mapping[str, Any]] | Sequence[MutableMapping[str, Any]],
    spot_price: float,
    atr: float = 0.0,
    config: Mapping[str, Any] | None = None,
    interest_rate: float = 0.05,
    dte_range: tuple[int, int] | None = None,
    interactive_mode: bool = False,
    criteria: Any | None = None,
    next_earnings: date | None = None,
    debug_path: Path | None = None,
) -> PipelineRunResult:
    """Execute ``pipeline`` with shared context construction and guards."""

    if pipeline is None:
        raise PipelineRunError("pipeline is required")

    try:
        records = list(option_chain)
    except TypeError as exc:  # pragma: no cover - defensive guard
        raise PipelineRunError("option_chain must be iterable") from exc

    if dte_range is not None:
        try:
            filtered_chain = filter_by_expiry(list(records), dte_range)
        except Exception as exc:
            raise PipelineRunError("failed to filter option chain by DTE range") from exc
    else:
        filtered_chain = list(records)

    context = StrategyContext(
        symbol=symbol,
        strategy=strategy,
        option_chain=filtered_chain,
        spot_price=float(spot_price or 0.0),
        atr=float(atr or 0.0),
        config=dict(config or {}),
        interest_rate=float(interest_rate),
        dte_range=dte_range,
        interactive_mode=bool(interactive_mode),
        criteria=criteria,
        next_earnings=next_earnings,
        debug_path=debug_path,
    )

    try:
        proposals, summary = pipeline.build_proposals(context)
    except Exception as exc:  # pragma: no cover - pipeline level failure
        raise PipelineRunError(
            f"pipeline execution failed for {symbol}/{strategy}"
        ) from exc

    return PipelineRunResult(
        context=context,
        proposals=list(proposals),
        summary=summary,
        filtered_chain=list(filtered_chain),
    )


class StrategyPipeline:
    """Encapsulate strike filtering and strategy generation logic."""

    def __init__(
        self,
        config: Mapping[str, Any] | ConfigGetter | None,
        market_provider: Any | None = None,
        *,
        strike_selector_factory: Callable[..., StrikeSelector] = StrikeSelector,
        strategy_generator: Callable[..., tuple[Sequence[Any], list[ReasonDetail]]] = generate_strategy_candidates,
        strike_config_loader: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] = load_strike_config,
        price_getter: Callable[[Mapping[str, Any]], tuple[float | None, str | None]] | None = None,
    ) -> None:
        self._config_getter = resolve_config_getter(config)
        self._market_provider = market_provider
        self._selector_factory = strike_selector_factory
        self._strategy_generator = strategy_generator
        self._load_strike_config = strike_config_loader
        self._price_getter = price_getter
        self._mid_resolver: MidResolver | None = None
        self._reason_engine = ReasonEngine()

        self.last_context: StrategyContext | None = None
        self.last_selected: list[MutableMapping[str, Any]] = []
        self.last_evaluated: list[dict[str, Any]] = []
        self.last_rejections: dict[str, Any] = {}
        self._earnings_data: dict[str, list[str]] | None = None
        self._earnings_cache: dict[str, date | None] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_proposals(
        self, context: StrategyContext
    ) -> tuple[list[StrategyProposal], RejectionSummary]:
        """Return generated proposals and rejection summary for ``context``."""

        logger.info(
            "StrategyPipeline.build_proposals symbol=%s strategy=%s", context.symbol, context.strategy
        )
        self.last_context = context
        canonical_strategy = self._canonical_strategy(context.strategy)
        rules = self._load_rules(canonical_strategy, context.config)
        dte_range = self._determine_dte_range(context, rules)
        selector = self._selector_factory(
            config=self._build_filter_config(rules),
            criteria=context.criteria,
        )
        resolver_cfg = self._config_getter("MID_RESOLVER", {})
        self._mid_resolver = build_mid_resolver(
            context.option_chain,
            spot_price=context.spot_price,
            interest_rate=context.interest_rate,
            config=resolver_cfg,
        )
        resolved_chain = self._mid_resolver.enrich_chain()

        selected, by_reason, by_filter = selector.select(
            list(resolved_chain),
            dte_range=dte_range,
            debug_csv=context.debug_path,
            return_info=True,
        )
        self.last_selected = list(selected)
        evaluated = [
            self._evaluate_leg(opt, context.spot_price, context.interest_rate)
            for opt in self.last_selected
        ]
        self.last_evaluated = evaluated
        self.last_rejections = {
            "by_filter": dict(by_filter),
            "by_reason": dict(by_reason),
            "by_strategy": {},
        }

        proposals: list[StrategyProposal] = []
        reasons: list[ReasonDetail] = []
        if context.spot_price and self.last_selected:
            try:
                with combo_symbol_context(context.symbol):
                    raw_props, reasons = self._strategy_generator(
                        context.symbol,
                        canonical_strategy,
                        self.last_selected,
                        context.atr,
                        context.config or self._config_getter("STRATEGY_CONFIG", {}) or {},
                        context.spot_price,
                        interactive_mode=context.interactive_mode,
                    )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Strategy generation failed: %s", exc)
                raw_props, reasons = [], []
            proposals = [
                self._convert_proposal(canonical_strategy, proposal)
                for proposal in raw_props
            ]
        earnings_reasons: list[ReasonDetail] = []
        if proposals:
            proposals, earnings_reasons = self._apply_earnings_filter(
                canonical_strategy, context, proposals
            )
        if earnings_reasons:
            reason_counts = self.last_rejections.get("by_reason", {})
            for reason in earnings_reasons:
                reason_counts[reason.code] = reason_counts.get(reason.code, 0) + 1
            self.last_rejections["by_reason"] = reason_counts

        combined_reasons: list[ReasonDetail] = []
        if reasons:
            combined_reasons.extend(dedupe_reasons(reasons))
        if earnings_reasons:
            combined_reasons.extend(dedupe_reasons(earnings_reasons))
        if combined_reasons:
            existing = self.last_rejections.get("by_strategy") or {}
            existing[canonical_strategy] = dedupe_reasons(combined_reasons)
            self.last_rejections["by_strategy"] = existing
        summary = self.summarize_rejections(self.last_rejections)
        return proposals, summary

    def summarize_rejections(self, results: dict[str, Any] | None = None) -> RejectionSummary:
        """Return :class:`RejectionSummary` from ``results`` or last run."""

        data = results or self.last_rejections or {}
        by_filter = dict(sorted((data.get("by_filter") or {}).items(), key=lambda item: item[1], reverse=True))
        by_reason = dict(sorted((data.get("by_reason") or {}).items(), key=lambda item: item[1], reverse=True))
        by_strategy = {
            name: dedupe_reasons(reasons)
            for name, reasons in (data.get("by_strategy") or {}).items()
        }
        return RejectionSummary(by_filter=by_filter, by_reason=by_reason, by_strategy=by_strategy)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _canonical_strategy(self, strategy: str) -> str:
        return canonical_strategy_name(strategy)

    def _load_rules(
        self, strategy: str, config: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        config_data = config or self._config_getter("STRATEGY_CONFIG", {}) or {}
        try:
            return self._load_strike_config(strategy, config_data)
        except Exception:
            return {}

    def _determine_dte_range(
        self, context: StrategyContext, rules: Mapping[str, Any]
    ) -> tuple[int, int]:
        if context.dte_range is not None:
            return context.dte_range
        dte_range = rules.get("dte_range") or [0, 365]
        try:
            return int(dte_range[0]), int(dte_range[1])
        except Exception:
            return 0, 365

    def _as_bool(self, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in {"true", "yes", "y", "1", "on"}:
                return True
            if low in {"false", "no", "n", "0", "off"}:
                return False
        return None

    def _earnings_filter_enabled(
        self, strategy: str, config: Mapping[str, Any] | None
    ) -> bool:
        config_data = config or self._config_getter("STRATEGY_CONFIG", {}) or {}
        value = get_strategy_setting(
            config_data,
            strategy,
            "exclude_expiry_before_earnings",
        )
        flag = self._as_bool(value)
        return bool(flag)

    def _min_days_to_earnings(
        self, strategy: str, config: Mapping[str, Any] | None
    ) -> int | None:
        config_data = config or self._config_getter("STRATEGY_CONFIG", {}) or {}
        value = get_strategy_setting(
            config_data,
            strategy,
            "min_days_until_earnings",
        )
        return coerce_int(value)

    def _load_earnings_data(self) -> dict[str, list[str]]:
        if self._earnings_data is not None:
            return self._earnings_data
        path_value = self._config_getter(
            "EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json"
        )
        if not path_value:
            self._earnings_data = {}
            return self._earnings_data
        path = Path(str(path_value)).expanduser()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._earnings_data = {}
            return self._earnings_data
        data: dict[str, list[str]] = {}
        if isinstance(raw, Mapping):
            for symbol, entries in raw.items():
                if not isinstance(symbol, str):
                    continue
                if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
                    normalized = [
                        str(item)
                        for item in entries
                        if isinstance(item, str) and item.strip()
                    ]
                    if normalized:
                        data[symbol.upper()] = normalized
        self._earnings_data = data
        return self._earnings_data

    def _next_earnings(self, context: StrategyContext) -> date | None:
        value = context.next_earnings
        parsed: date | None = None
        if isinstance(value, datetime):
            parsed = value.date()
        elif isinstance(value, date):
            parsed = value
        elif isinstance(value, str):
            parsed = parse_date(value)
        if parsed is not None:
            return parsed
        symbol = context.symbol.upper()
        if symbol in self._earnings_cache:
            return self._earnings_cache[symbol]
        data = self._load_earnings_data()
        entries = data.get(symbol, [])
        today_date = date.today()
        upcoming: list[date] = []
        for raw in entries:
            parsed_entry = parse_date(raw)
            if parsed_entry is None:
                continue
            if parsed_entry >= today_date:
                upcoming.append(parsed_entry)
        next_event = min(upcoming) if upcoming else None
        self._earnings_cache[symbol] = next_event
        return next_event

    def _latest_expiry(
        self, legs: Sequence[Mapping[str, Any]]
    ) -> date | None:
        expiries: list[date] = []
        for leg in legs:
            raw = leg.get("expiry")
            parsed: date | None
            if isinstance(raw, datetime):
                parsed = raw.date()
            elif isinstance(raw, date):
                parsed = raw
            elif isinstance(raw, str):
                parsed = parse_date(raw)
            else:
                parsed = None
            if parsed is not None:
                expiries.append(parsed)
        return max(expiries) if expiries else None

    def _apply_earnings_filter(
        self,
        strategy: str,
        context: StrategyContext,
        proposals: Sequence[StrategyProposal],
    ) -> tuple[list[StrategyProposal], list[ReasonDetail]]:
        if not proposals:
            return list(proposals), []
        earnings_date = self._next_earnings(context)
        if earnings_date is None:
            return list(proposals), []
        min_days = self._min_days_to_earnings(strategy, context.config)
        if min_days is not None and min_days > 0:
            days_until = self._days_until_earnings(earnings_date)
            if days_until is not None and days_until < min_days:
                reason = make_reason(
                    ReasonCategory.POLICY_VIOLATION,
                    "EARNINGS_TOO_CLOSE",
                    (
                        f"Earnings binnen {days_until} dagen voor {strategy}"
                        f" (minimaal {min_days} vereist)"
                    ),
                    data={
                        "earnings_date": earnings_date.isoformat(),
                        "days_until": days_until,
                        "required_days": min_days,
                        "strategy": strategy,
                    },
                )
                return [], [reason]
        if not self._earnings_filter_enabled(strategy, context.config):
            return list(proposals), []
        kept: list[StrategyProposal] = []
        rejected: list[ReasonDetail] = []
        for proposal in proposals:
            latest_expiry = self._latest_expiry(proposal.legs)
            if latest_expiry is None or latest_expiry >= earnings_date:
                kept.append(proposal)
                continue
            reason = make_reason(
                ReasonCategory.POLICY_VIOLATION,
                "EARNINGS_BEFORE_EVENT",
                f"Earnings {earnings_date.isoformat()} voor expiry {latest_expiry.isoformat()}",
                data={
                    "earnings_date": earnings_date.isoformat(),
                    "expiry": latest_expiry.isoformat(),
                    "strategy": strategy,
                },
            )
            rejected.append(reason)
        return kept, rejected

    def _days_until_earnings(self, earnings_date: date | None) -> int | None:
        if earnings_date is None:
            return None
        try:
            return (earnings_date - date.today()).days
        except Exception:
            return None

    def _build_filter_config(self, rules: Mapping[str, Any]) -> FilterConfig:
        def _float(val: Any, default: float | None = None) -> float | None:
            parsed = safe_float(val)
            return parsed if parsed is not None else default

        delta_range = (
            rules.get("delta_range")
            or rules.get("short_delta_range")
            or [-1.0, 1.0]
        )
        delta_min = _float(delta_range[0], -1.0) if isinstance(delta_range, (list, tuple)) else -1.0
        delta_max = (
            _float(delta_range[1], 1.0)
            if isinstance(delta_range, (list, tuple)) and len(delta_range) > 1
            else 1.0
        )
        return FilterConfig(
            delta_min=delta_min,
            delta_max=delta_max,
            min_rom=_float(rules.get("min_rom"), 0.0) or 0.0,
            min_edge=_float(rules.get("min_edge"), 0.0) or 0.0,
            min_pos=_float(rules.get("min_pos"), 0.0) or 0.0,
            min_ev=_float(rules.get("min_ev"), 0.0) or 0.0,
            skew_min=_float(rules.get("skew_min"), float("-inf")) or float("-inf"),
            skew_max=_float(rules.get("skew_max"), float("inf")) or float("inf"),
            term_min=_float(rules.get("term_min"), float("-inf")) or float("-inf"),
            term_max=_float(rules.get("term_max"), float("inf")) or float("inf"),
            max_gamma=_float(rules.get("max_gamma")),
            max_vega=_float(rules.get("max_vega")),
            min_theta=_float(rules.get("min_theta")),
        )

    def _apply_symbol_defaults(self, leg: MutableMapping[str, Any]) -> None:
        """Ensure that legs contain the underlying ticker information."""

        fallback = self.last_context.symbol if self.last_context else None
        symbol = resolve_symbol([leg], fallback=fallback)
        if symbol:
            leg["symbol"] = symbol
            leg.setdefault("underlying", symbol)

    def _normalize_proposal_leg(self, leg: Mapping[str, Any]) -> dict[str, Any]:
        normalized = normalize_leg(dict(leg))
        self._apply_symbol_defaults(normalized)
        return normalized

    def _evaluate_leg(
        self, option: MutableMapping[str, Any], spot_price: float, interest_rate: float
    ) -> dict[str, Any]:
        option = dict(option)
        resolution = self._mid_resolver.resolution_for(option) if self._mid_resolver else None
        if resolution and resolution.mid is not None:
            mid = resolution.mid
        elif self._price_getter is not None:
            mid, _ = self._price_getter(option)
        else:
            mid = option.get("mid")
            if mid is None:
                mid, _ = get_option_mid_price(option)
        mid = safe_float(mid)
        model = self._extract_model_price(option, spot_price, interest_rate)
        margin = self._extract_margin(option, spot_price)
        delta = safe_float(option.get("delta"))

        pos = calculate_pos(delta) if delta is not None else None
        rom = calculate_rom(mid * 100, margin) if mid is not None and margin is not None else None
        edge = (
            calculate_edge(model, mid)
            if model is not None and mid is not None
            else None
        )
        ev = (
            calculate_ev(pos, mid * 100, -margin)
            if None not in (pos, mid, margin)
            else None
        )
        result = {
            "symbol": resolve_symbol([option]),
            "expiry": option.get("expiry"),
            "strike": option.get("strike"),
            "type": option.get("type"),
            "delta": delta,
            "mid": mid,
            "model": model,
            "margin": margin,
            "pos": pos,
            "rom": rom,
            "edge": edge,
            "ev": ev,
        }
        if resolution:
            result.update(resolution.as_dict())
        self._apply_symbol_defaults(result)
        normalize_leg(result)
        self._apply_symbol_defaults(result)
        return result

    def _extract_model_price(
        self, option: Mapping[str, Any], spot_price: float, interest_rate: float
    ) -> float | None:
        model = safe_float(option.get("modelprice"))
        if model is not None:
            return model
        price = estimate_model_price(
            option,
            spot_price=spot_price,
            interest_rate=interest_rate,
        )
        if price is None:
            return None
        return round(price, 2)

    def _extract_margin(
        self, option: Mapping[str, Any], spot_price: float
    ) -> float | None:
        margin = safe_float(option.get("marginreq"))
        if margin is not None:
            return margin
        strike = safe_float(option.get("strike"))
        base = float(spot_price) if spot_price else strike
        if base is None:
            return 350.0
        return round(base * 100 * 0.2, 2)

    def _convert_proposal(self, strategy: str, proposal: Any) -> StrategyProposal:
        converted = StrategyProposal(
            strategy=strategy,
            legs=[
                self._normalize_proposal_leg(leg)
                for leg in getattr(proposal, "legs", [])
            ],
            score=getattr(proposal, "score", None),
            pos=getattr(proposal, "pos", None),
            ev=getattr(proposal, "ev", None),
            ev_pct=getattr(proposal, "ev_pct", None),
            rom=getattr(proposal, "rom", None),
            edge=getattr(proposal, "edge", None),
            credit=getattr(proposal, "credit", None),
            margin=getattr(proposal, "margin", None),
            max_profit=getattr(proposal, "max_profit", None),
            max_loss=getattr(proposal, "max_loss", None),
            breakevens=list(getattr(proposal, "breakevens", []) or []),
            fallback=getattr(proposal, "fallback", None),
            profit_estimated=bool(getattr(proposal, "profit_estimated", False)),
            scenario_info=dict(getattr(proposal, "scenario_info", {}) or {}),
            atr=getattr(proposal, "atr", None),
            iv_rank=getattr(proposal, "iv_rank", None),
            iv_percentile=getattr(proposal, "iv_percentile", None),
            hv20=getattr(proposal, "hv20", None),
            hv30=getattr(proposal, "hv30", None),
            hv90=getattr(proposal, "hv90", None),
            dte=(
                dict(getattr(proposal, "dte"))
                if getattr(proposal, "dte", None)
                else None
            ),
            wing_width=(
                dict(getattr(proposal, "wing_width"))
                if getattr(proposal, "wing_width", None)
                else None
            ),
            wing_symmetry=getattr(proposal, "wing_symmetry", None),
            breakeven_distances=(
                dict(getattr(proposal, "breakeven_distances"))
                if getattr(proposal, "breakeven_distances", None)
                else None
            ),
        )
        converted.reasons = list(getattr(proposal, "reasons", []) or [])
        converted.needs_refresh = bool(getattr(proposal, "needs_refresh", False))
        if converted.legs:
            if self._mid_resolver is not None:
                summary = self._mid_resolver.summarize_legs(converted.legs)
            else:
                summary = MidUsageSummary.from_legs(converted.legs)
            evaluation = self._reason_engine.evaluate(
                summary,
                existing_reasons=converted.reasons,
                needs_refresh=converted.needs_refresh,
            )
            converted.fallback_summary = dict(evaluation.fallback_summary)
            converted.spread_rejects_n = summary.spread_too_wide_count
            converted.needs_refresh = evaluation.needs_refresh
            converted.mid_status = evaluation.status
            converted.mid_status_tags = evaluation.tags
            converted.preview_sources = evaluation.preview_sources
            converted.fallback_limit_exceeded = evaluation.fallback_limit_exceeded
            converted.reasons = list(evaluation.reasons)
            if evaluation.preview_sources:
                converted.fallback = ",".join(evaluation.preview_sources)
            else:
                converted.fallback = None
        else:
            converted.mid_status_tags = (converted.mid_status,)
        return converted
