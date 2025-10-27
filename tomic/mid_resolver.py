"""Centralized mid-price resolution with graceful degradation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from .config import get as cfg_get
from .helpers.bs_utils import estimate_model_price
from .helpers.dateutils import dte_between_dates, parse_date
from .helpers.numeric import safe_float
from .logutils import logger
from .strategy.reasons import mid_reason_message
from .utils import get_leg_right, today


MID_SOURCES = ("true", "parity_true", "parity_close", "model", "close")


@dataclass(slots=True)
class MidResolution:
    """Resolved mid metadata for a single option quote."""

    mid: float | None = None
    mid_source: str | None = None
    mid_reason: str | None = None
    spread_flag: str | None = None
    quote_age_sec: float | None = None
    one_sided: bool = False
    mid_fallback: str | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mid": self.mid,
            "mid_source": self.mid_source,
            "mid_reason": self.mid_reason,
            "spread_flag": self.spread_flag,
            "quote_age_sec": self.quote_age_sec,
            "one_sided": self.one_sided,
            "mid_fallback": self.mid_fallback,
        }
class MidResolver:
    """Resolve mid prices with hierarchical fallbacks."""

    def __init__(
        self,
        option_chain: Iterable[Mapping[str, Any]],
        *,
        spot_price: float | None,
        interest_rate: float | None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self._raw_chain = [dict(opt) for opt in option_chain]
        self._spot_price = safe_float(spot_price)
        self._interest_rate = float(interest_rate or 0.0)
        self._config = config or {}
        self._resolutions: list[MidResolution] = [MidResolution() for _ in self._raw_chain]

        self._max_fallback_per_4 = int(
            self._config.get(
                "max_fallback_per_4_leg",
                cfg_get("MID_FALLBACK_MAX_PER_4", 2),
            )
        )

        spread_cfg = self._config.get("spread_thresholds") or {}
        self._relative_threshold = float(spread_cfg.get("relative", cfg_get("MID_SPREAD_RELATIVE", 0.12)))
        self._absolute_buckets = spread_cfg.get("absolute") or cfg_get(
            "MID_SPREAD_ABSOLUTE",
            [
                {"max_underlying": 50.0, "threshold": 0.10},
                {"max_underlying": 200.0, "threshold": 0.20},
                {"max_underlying": None, "threshold": 0.50},
            ],
        )

        self._key_to_index: dict[tuple[Any, ...], int] = {}
        for idx, option in enumerate(self._raw_chain):
            key = self._build_key(option)
            if key is not None:
                self._key_to_index[key] = idx

        self._resolve_all()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def enrich_chain(self) -> list[MutableMapping[str, Any]]:
        """Return option chain augmented with mid metadata."""

        enriched: list[MutableMapping[str, Any]] = []
        for option, resolution in zip(self._raw_chain, self._resolutions):
            enriched_opt = dict(option)
            enriched_opt.update(resolution.as_dict())
            if resolution.mid_source in {"parity_true", "parity_close"}:
                enriched_opt["mid_from_parity"] = True
            enriched.append(enriched_opt)
        return enriched

    def resolution_for(self, option: Mapping[str, Any]) -> MidResolution:
        """Return resolution metadata for ``option`` if known."""

        key = self._build_key(option)
        if key is None:
            return MidResolution()
        idx = self._key_to_index.get(key)
        if idx is None:
            return MidResolution()
        return self._resolutions[idx]

    def max_fallback_legs(self, leg_count: int) -> int:
        if self._max_fallback_per_4 <= 0:
            return 0
        return max(0, math.floor(self._max_fallback_per_4 * leg_count / 4))

    # ------------------------------------------------------------------
    # Internal processing
    # ------------------------------------------------------------------
    def _resolve_all(self) -> None:
        for idx, option in enumerate(self._raw_chain):
            res = self._resolutions[idx]
            res.quote_age_sec = self._extract_quote_age(option)
            self._try_true_mid(idx, option)

        for idx, option in enumerate(self._raw_chain):
            if self._resolutions[idx].mid is None:
                self._try_parity(idx, option)

        for idx, option in enumerate(self._raw_chain):
            if self._resolutions[idx].mid is None:
                self._try_model(idx, option)

        for idx, option in enumerate(self._raw_chain):
            if self._resolutions[idx].mid is None:
                self._try_close(idx, option)

        for idx, option in enumerate(self._raw_chain):
            res = self._resolutions[idx]
            if res.mid is None:
                res.mid_reason = res.mid_reason or "geen mid beschikbaar na fallbacks"
                res.spread_flag = res.spread_flag or "missing"

    def _try_true_mid(self, idx: int, option: Mapping[str, Any]) -> None:
        res = self._resolutions[idx]
        bid = safe_float(option.get("bid"))
        ask = safe_float(option.get("ask"))
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            spread = ask - bid
            if spread <= 0:
                res.mid_reason = "bid/ask onlogisch"
                res.spread_flag = "invalid"
                return
            mid = (bid + ask) / 2
            spread_ok, flag = self._spread_ok(mid, spread, option)
            if spread_ok:
                res.mid = round(mid, 4)
                res.mid_source = "true"
                res.mid_reason = mid_reason_message("true")
                res.spread_flag = flag
            else:
                res.mid_reason = "spread te wijd"
                res.spread_flag = flag
        else:
            res.one_sided = bool(
                (bid is not None and bid > 0 and (ask is None or ask <= 0))
                or (ask is not None and ask > 0 and (bid is None or bid <= 0))
            )
            if res.one_sided:
                res.mid_reason = "one sided quote"
                res.spread_flag = "one_sided"
            else:
                res.mid_reason = "bid/ask ontbreken"
                res.spread_flag = "missing"

    def _try_parity(self, idx: int, option: Mapping[str, Any]) -> None:
        res = self._resolutions[idx]
        if res.mid is not None:
            return
        counterpart = self._find_counterpart(option)
        if counterpart is None:
            res.mid_reason = res.mid_reason or "parity inputs ontbreken"
            return
        counterpart_res = self._resolutions[counterpart]

        base_mid = counterpart_res.mid
        base_source = counterpart_res.mid_source or "true"

        if base_mid is None:
            counterpart_close = safe_float(self._raw_chain[counterpart].get("close"))
            if counterpart_close is not None and counterpart_close > 0:
                base_mid = counterpart_close
                base_source = "close"
            else:
                res.mid_reason = res.mid_reason or "parity basis ontbreekt"
                return

        strike = safe_float(option.get("strike"))
        expiry = option.get("expiry") or option.get("expiration")
        if strike is None or not expiry:
            res.mid_reason = res.mid_reason or "parity strike/expiry ontbreekt"
            return

        dte = self._extract_dte(option, expiry)
        if dte is None:
            res.mid_reason = res.mid_reason or "parity dte ontbreekt"
            return

        right = get_leg_right(option)
        if right not in {"call", "put"}:
            res.mid_reason = res.mid_reason or "parity type onbekend"
            return

        spot = self._spot_price
        if spot is None:
            res.mid_reason = res.mid_reason or "parity spot ontbreekt"
            return

        discount = strike * math.exp(-self._interest_rate * (dte / 365))
        if right == "call":
            parity_mid = base_mid + spot - discount
        else:
            parity_mid = base_mid - spot + discount
        if parity_mid is None or parity_mid <= 0:
            res.mid_reason = res.mid_reason or "parity resultaat ongeldig"
            return
        res.mid = round(parity_mid, 4)
        if base_source not in {"true", "parity_true"}:
            res.mid_source = "parity_close"
            res.mid_reason = mid_reason_message("parity_close", base_source=base_source)
            res.mid_fallback = "parity_close"
        else:
            res.mid_source = "parity_true"
            res.mid_reason = mid_reason_message("parity_true")
            res.mid_fallback = "parity_true"

    def _try_model(self, idx: int, option: Mapping[str, Any]) -> None:
        res = self._resolutions[idx]
        if res.mid is not None:
            return

        model = safe_float(option.get("modelprice"))
        if model is None:
            model = self._black_scholes(option)
        if model is None:
            res.mid_reason = res.mid_reason or "model prijs ontbreekt"
            return
        res.mid = round(model, 4)
        res.mid_source = "model"
        res.mid_reason = mid_reason_message("model")
        res.mid_fallback = "model"

    def _try_close(self, idx: int, option: Mapping[str, Any]) -> None:
        res = self._resolutions[idx]
        if res.mid is not None:
            return
        close = safe_float(option.get("close"))
        if close is None:
            res.mid_reason = res.mid_reason or "close ontbreekt"
            return
        res.mid = round(close, 4)
        res.mid_source = "close"
        res.mid_reason = mid_reason_message("close")
        res.mid_fallback = "close"

    def _spread_ok(self, mid: float, spread: float, option: Mapping[str, Any]) -> tuple[bool, str]:
        if mid <= 0:
            return False, "invalid_mid"
        underlying = safe_float(option.get("spot"))
        if underlying is None:
            underlying = self._spot_price
        if underlying is None:
            underlying = safe_float(option.get("underlying_price"))

        abs_threshold = self._absolute_threshold(underlying)
        rel_threshold = self._relative_threshold * mid
        if spread <= abs_threshold:
            return True, "abs"
        if spread <= rel_threshold:
            return True, "rel"
        return False, "too_wide"

    def _absolute_threshold(self, underlying: float | None) -> float:
        price = underlying or 0.0
        for bucket in self._absolute_buckets:
            try:
                limit = bucket.get("max_underlying")
                threshold = float(bucket.get("threshold"))
            except Exception:
                continue
            if limit is None or price <= float(limit):
                return threshold
        return 0.50

    def _extract_quote_age(self, option: Mapping[str, Any]) -> float | None:
        for key in ("quote_age_sec", "quote_age", "age", "quote_age_seconds"):
            val = option.get(key)
            parsed = safe_float(val)
            if parsed is not None:
                return parsed
        return None

    def _find_counterpart(self, option: Mapping[str, Any]) -> int | None:
        key = self._build_key(option)
        if key is None:
            return None
        expiry, strike, right = key
        other_right = "put" if right == "call" else "call"
        counter_key = (expiry, strike, other_right)
        return self._key_to_index.get(counter_key)

    def _build_key(self, option: Mapping[str, Any]) -> tuple[Any, ...] | None:
        try:
            expiry = option.get("expiry") or option.get("expiration")
            if not expiry:
                return None
            strike = safe_float(option.get("strike"))
            if strike is None:
                return None
            right = get_leg_right(option)
            return (str(expiry), float(strike), right)
        except Exception:
            return None

    def _extract_dte(self, option: Mapping[str, Any], expiry: Any) -> Optional[int]:
        dte_val = option.get("dte")
        parsed = None if dte_val is None else safe_float(dte_val)
        if parsed is not None:
            return int(parsed)
        dt = parse_date(str(expiry))
        if dt is None:
            return None
        return dte_between_dates(today(), dt)

    def _black_scholes(self, option: Mapping[str, Any]) -> float | None:
        price = estimate_model_price(
            option,
            spot_price=self._spot_price,
            interest_rate=self._interest_rate,
            spot_keys=("spot",),
            on_error=lambda exc: logger.debug(
                "Black-Scholes failed for %s: %s", option, exc
            ),
        )
        if price is None:
            return None
        return round(price, 4)


def build_mid_resolver(
    option_chain: Iterable[Mapping[str, Any]],
    *,
    spot_price: float | None,
    interest_rate: float | None,
    config: Mapping[str, Any] | None = None,
) -> MidResolver:
    """Convenience helper mirroring existing pipeline injection pattern."""

    return MidResolver(
        option_chain,
        spot_price=spot_price,
        interest_rate=interest_rate,
        config=config,
    )


__all__ = ["MidResolver", "MidResolution", "build_mid_resolver", "MID_SOURCES"]

