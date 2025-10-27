"""Facade around :mod:`tomic.mid_resolver` exposing rich mid metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Optional, Sequence

from ...helpers.numeric import safe_float
from ...mid_resolver import MidResolver, MidResolution, MidUsageSummary
from ..data import InterestRateProvider, InterestRateQuote


@dataclass(slots=True)
class MidPriceQuote:
    """Resolved mid price information with provenance metadata."""

    mid: float | None = None
    mid_source: str | None = None
    mid_fallback: str | None = None
    mid_reason: str | None = None
    spread_flag: str | None = None
    quote_age_sec: float | None = None
    one_sided: bool = False
    interest_rate: float | None = None
    interest_rate_source: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "mid": self.mid,
            "mid_source": self.mid_source,
            "mid_reason": self.mid_reason,
            "spread_flag": self.spread_flag,
            "quote_age_sec": self.quote_age_sec,
            "one_sided": self.one_sided,
            "mid_fallback": self.mid_fallback,
            "interest_rate": self.interest_rate,
            "interest_rate_source": self.interest_rate_source,
        }


def _normalized_source(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if not value:
        return None
    if value == "parity":
        return "parity_true"
    return value


def _has_resolution_data(resolution: MidResolution | None) -> bool:
    if resolution is None:
        return False
    return any(
        getattr(resolution, field)
        for field in (
            "mid",
            "mid_source",
            "mid_reason",
            "spread_flag",
            "mid_fallback",
        )
    )


class MidPricingContext:
    """Container bundling a :class:`MidResolver` with rate metadata."""

    def __init__(
        self,
        resolver: MidResolver | None,
        *,
        interest_rate: InterestRateQuote,
    ) -> None:
        self._resolver = resolver
        self._interest_rate = interest_rate

    @property
    def interest_rate(self) -> float | None:
        return self._interest_rate.value if self._interest_rate else None

    @property
    def interest_rate_source(self) -> str | None:
        return self._interest_rate.source if self._interest_rate else None

    def enrich_chain(self) -> list[MutableMapping[str, object]]:
        if self._resolver is None:
            return []
        enriched = []
        for option in self._resolver.enrich_chain():
            data = dict(option)
            data.setdefault("interest_rate", self.interest_rate)
            data.setdefault("interest_rate_source", self.interest_rate_source)
            enriched.append(data)
        return enriched

    def summarize_legs(self, legs: Iterable[Mapping[str, object]], *, fallback_allowed: int | None = None) -> MidUsageSummary:
        if self._resolver is None:
            return MidUsageSummary.from_legs(legs, resolver=None, fallback_allowed=fallback_allowed)
        return self._resolver.summarize_legs(legs, fallback_allowed=fallback_allowed)

    def max_fallback_legs(self, leg_count: int) -> int:
        if self._resolver is None:
            return 0
        return self._resolver.max_fallback_legs(leg_count)

    def quote_for(self, leg: Mapping[str, object]) -> MidPriceQuote:
        resolution = self._resolver.resolution_for(leg) if self._resolver else None
        if _has_resolution_data(resolution):
            return _quote_from_resolution(resolution, rate=self._interest_rate)
        return _heuristic_quote(leg, rate=self._interest_rate)


class MidService:
    """Build mid pricing contexts and ad-hoc quotes."""

    def __init__(self, *, interest_provider: InterestRateProvider | None = None) -> None:
        self._interest_provider = interest_provider or InterestRateProvider()

    def build_context(
        self,
        option_chain: Sequence[Mapping[str, object]],
        *,
        spot_price: float | None,
        interest_rate: float | None = None,
        config: Mapping[str, object] | None = None,
    ) -> MidPricingContext:
        rate_quote = self._interest_provider.current(override=interest_rate)
        resolver = MidResolver(
            option_chain,
            spot_price=spot_price,
            interest_rate=rate_quote.value,
            config=config,
        )
        return MidPricingContext(resolver, interest_rate=rate_quote)

    def quote_option(
        self,
        leg: Mapping[str, object],
        *,
        interest_rate: float | None = None,
    ) -> MidPriceQuote:
        rate_quote = self._interest_provider.current(override=interest_rate)
        return _heuristic_quote(leg, rate=rate_quote)


def _quote_from_resolution(resolution: MidResolution, *, rate: InterestRateQuote) -> MidPriceQuote:
    source = _normalized_source(resolution.mid_source)
    fallback = _normalized_source(resolution.mid_fallback)
    return MidPriceQuote(
        mid=resolution.mid,
        mid_source=source,
        mid_fallback=fallback,
        mid_reason=resolution.mid_reason,
        spread_flag=resolution.spread_flag,
        quote_age_sec=resolution.quote_age_sec,
        one_sided=resolution.one_sided,
        interest_rate=rate.value,
        interest_rate_source=rate.source,
    )


def _heuristic_quote(leg: Mapping[str, object], *, rate: InterestRateQuote) -> MidPriceQuote:
    mid = safe_float(leg.get("mid"))
    source = _normalized_source(leg.get("mid_source"))
    fallback = _normalized_source(leg.get("mid_fallback"))
    spread_flag = None
    reason = None
    quote_age = safe_float(leg.get("quote_age_sec")) or safe_float(leg.get("quote_age"))

    if mid is not None and mid > 0:
        return MidPriceQuote(
            mid=mid,
            mid_source=source or fallback or "true",
            mid_fallback=fallback,
            mid_reason=reason,
            spread_flag=spread_flag,
            quote_age_sec=quote_age,
            one_sided=bool(leg.get("one_sided")),
            interest_rate=rate.value,
            interest_rate_source=rate.source,
        )

    bid = safe_float(leg.get("bid"))
    ask = safe_float(leg.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        computed = (bid + ask) / 2
        spread_flag = "legacy"
        return MidPriceQuote(
            mid=computed,
            mid_source=source or fallback or "true",
            mid_fallback=fallback,
            mid_reason=reason,
            spread_flag=spread_flag,
            quote_age_sec=quote_age,
            one_sided=False,
            interest_rate=rate.value,
            interest_rate_source=rate.source,
        )

    last = safe_float(leg.get("last"))
    if last is not None and last > 0:
        return MidPriceQuote(
            mid=last,
            mid_source=source or fallback or "last",
            mid_fallback=fallback,
            mid_reason=reason,
            spread_flag=spread_flag,
            quote_age_sec=quote_age,
            one_sided=False,
            interest_rate=rate.value,
            interest_rate_source=rate.source,
        )

    model_price = safe_float(leg.get("modelprice") or leg.get("model"))
    if model_price is not None and model_price > 0:
        return MidPriceQuote(
            mid=model_price,
            mid_source="model",
            mid_fallback="model",
            mid_reason=reason,
            spread_flag=spread_flag,
            quote_age_sec=quote_age,
            one_sided=False,
            interest_rate=rate.value,
            interest_rate_source=rate.source,
        )

    close = safe_float(leg.get("close"))
    if close is not None and close > 0:
        src = source or fallback or "close"
        if src in {None, "true"}:
            src = "close"
        return MidPriceQuote(
            mid=close,
            mid_source=src,
            mid_fallback="close",
            mid_reason=reason,
            spread_flag=spread_flag,
            quote_age_sec=quote_age,
            one_sided=False,
            interest_rate=rate.value,
            interest_rate_source=rate.source,
        )

    return MidPriceQuote(
        mid=None,
        mid_source=source,
        mid_fallback=fallback,
        mid_reason=reason,
        spread_flag=spread_flag,
        quote_age_sec=quote_age,
        one_sided=bool(leg.get("one_sided")),
        interest_rate=rate.value,
        interest_rate_source=rate.source,
    )


_default_service = MidService()


def resolve_option_mid(leg: Mapping[str, object]) -> MidPriceQuote:
    """Return a :class:`MidPriceQuote` for ``leg`` using default heuristics."""

    return _default_service.quote_option(leg)


__all__ = [
    "MidPriceQuote",
    "MidPricingContext",
    "MidService",
    "resolve_option_mid",
]
