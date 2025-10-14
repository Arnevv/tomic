from __future__ import annotations

"""Strategy generation pipeline used by CLI and services."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from ..bs_calculator import black_scholes
from ..metrics import calculate_edge, calculate_ev, calculate_pos, calculate_rom
from ..strategy_candidates import generate_strategy_candidates
from ..strike_selector import FilterConfig, StrikeSelector
from ..loader import load_strike_config
from ..logutils import logger
from ..mid_resolver import MidResolver, build_mid_resolver
from ..utils import get_option_mid_price, normalize_leg
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


ConfigGetter = Callable[[str, Any | None], Any]


@dataclass
class StrategyContext:
    """Input parameters for :class:`StrategyPipeline`."""

    symbol: str
    strategy: str
    option_chain: Sequence[MutableMapping[str, Any]]
    spot_price: float
    atr: float = 0.0
    config: Mapping[str, Any] | None = None
    interest_rate: float = 0.05
    dte_range: tuple[int, int] | None = None
    interactive_mode: bool = False
    criteria: Any | None = None
    next_earnings: date | None = None
    debug_path: Path | None = None


@dataclass
class StrategyProposal:
    """Resulting proposal exposed to the CLI layer."""

    strategy: str
    legs: list[dict[str, Any]] = field(default_factory=list)
    score: float | None = None
    pos: float | None = None
    ev: float | None = None
    ev_pct: float | None = None
    rom: float | None = None
    edge: float | None = None
    credit: float | None = None
    margin: float | None = None
    max_profit: float | None = None
    max_loss: float | None = None
    breakevens: list[float] | None = None
    fallback: str | None = None
    profit_estimated: bool = False
    scenario_info: dict[str, Any] | None = None
    fallback_summary: dict[str, int] | None = None
    spread_rejects_n: int = 0


@dataclass
class RejectionSummary:
    """Aggregated rejection information."""

    by_filter: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)
    by_strategy: dict[str, list[ReasonDetail]] = field(default_factory=dict)


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
        self._config_getter = self._resolve_config_getter(config)
        self._market_provider = market_provider
        self._selector_factory = strike_selector_factory
        self._strategy_generator = strategy_generator
        self._load_strike_config = strike_config_loader
        self._price_getter = price_getter
        self._mid_resolver: MidResolver | None = None

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
    def _resolve_config_getter(
        self, config: Mapping[str, Any] | ConfigGetter | None
    ) -> ConfigGetter:
        if callable(config):
            return config  # type: ignore[return-value]
        if hasattr(config, "get"):
            return lambda key, default=None: config.get(key, default)  # type: ignore[arg-type]
        if isinstance(config, Mapping):
            return lambda key, default=None: config.get(key, default)
        return lambda _key, default=None: default

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
            try:
                return float(val)
            except Exception:
                return default

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
        mid = self._safe_float(mid)
        model = self._extract_model_price(option, spot_price, interest_rate)
        margin = self._extract_margin(option, spot_price)
        delta = self._safe_float(option.get("delta"))

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
            "symbol": option.get("symbol"),
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
        normalize_leg(result)
        return result

    def _safe_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    def _extract_model_price(
        self, option: Mapping[str, Any], spot_price: float, interest_rate: float
    ) -> float | None:
        model = self._safe_float(option.get("modelprice"))
        if model is not None:
            return model
        iv = self._safe_float(option.get("iv"))
        strike = self._safe_float(option.get("strike"))
        expiry = option.get("expiry")
        opt_type = str(option.get("type") or option.get("right", "")).upper()[:1]
        if None in (iv, strike) or not expiry or opt_type not in {"C", "P"}:
            return None
        try:
            exp_date = parse_date(str(expiry))
            if exp_date is None:
                return None
            dte = max((exp_date - datetime.now().date()).days, 0)
            return round(
                black_scholes(
                    opt_type,
                    float(spot_price),
                    float(strike),
                    dte,
                    float(iv),
                    interest_rate,
                    0.0,
                ),
                2,
            )
        except Exception:
            return None

    def _extract_margin(
        self, option: Mapping[str, Any], spot_price: float
    ) -> float | None:
        margin = self._safe_float(option.get("marginreq"))
        if margin is not None:
            return margin
        strike = self._safe_float(option.get("strike"))
        base = float(spot_price) if spot_price else strike
        if base is None:
            return 350.0
        return round(base * 100 * 0.2, 2)

    def _convert_proposal(self, strategy: str, proposal: Any) -> StrategyProposal:
        converted = StrategyProposal(
            strategy=strategy,
            legs=[dict(leg) for leg in getattr(proposal, "legs", [])],
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
        )
        if converted.legs:
            fallback_summary: dict[str, int] = {
                source: 0
                for source in ("true", "parity_true", "parity_close", "model", "close")
            }
            spread_rejects = 0
            for leg in converted.legs:
                source = str(leg.get("mid_source") or "")
                if not source:
                    source = str(leg.get("mid_fallback") or "")
                if source == "parity":
                    source = "parity_true"
                if not source:
                    source = "true"
                if source not in fallback_summary:
                    fallback_summary[source] = 0
                fallback_summary[source] += 1
                if str(leg.get("spread_flag")) == "too_wide":
                    spread_rejects += 1
            converted.fallback_summary = fallback_summary
            converted.spread_rejects_n = spread_rejects
        return converted
