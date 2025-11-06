from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
import os
import csv

from .utils import today
from .helpers.dateutils import filter_by_dte
from .helpers.numeric import safe_float
from .logutils import logger
from .criteria import CriteriaConfig, load_criteria


DEFAULT_DTE_RANGE: Tuple[int, int] = (0, 365)


def _is_range(candidate: Any) -> bool:
    return isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes))


def _as_float(value: Any, fallback: float) -> float:
    parsed = safe_float(value)
    return parsed if parsed is not None else fallback


def _as_optional_float(value: Any, fallback: float | None) -> float | None:
    parsed = safe_float(value)
    return parsed if parsed is not None else fallback


def _as_int(value: Any, fallback: int) -> int:
    parsed = safe_float(value)
    if parsed is None:
        try:
            return int(value)  # type: ignore[arg-type]
        except Exception:
            return fallback
    try:
        return int(parsed)
    except Exception:
        return fallback


@dataclass
class FilterConfig:
    """Configuration for :class:`StrikeSelector`."""

    delta_min: float
    delta_max: float
    min_rom: float
    min_edge: float
    min_pos: float
    min_ev: float
    skew_min: float
    skew_max: float
    term_min: float
    term_max: float
    dte_min: int = DEFAULT_DTE_RANGE[0]
    dte_max: int = DEFAULT_DTE_RANGE[1]
    max_gamma: Optional[float] = None
    max_vega: Optional[float] = None
    min_theta: Optional[float] = None

    def __str__(self) -> str:  # pragma: no cover - logging helper
        parts = [
            f"delta={self.delta_min}..{self.delta_max}",
            f"ROM>={self.min_rom}",
            f"edge>={self.min_edge}",
            f"PoS>={self.min_pos}",
            f"EV>={self.min_ev}",
            f"skew={self.skew_min}..{self.skew_max}",
            f"term={self.term_min}..{self.term_max}",
            f"dte={self.dte_min}..{self.dte_max}",
        ]
        if self.max_gamma is not None:
            parts.append(f"gamma<={self.max_gamma}")
        if self.max_vega is not None:
            parts.append(f"vega<={self.max_vega}")
        if self.min_theta is not None:
            parts.append(f"theta>={self.min_theta}")
        return " ".join(parts)

    @property
    def delta_range(self) -> Tuple[float, float]:
        return self.delta_min, self.delta_max

    @property
    def dte_range(self) -> Tuple[int, int]:
        return int(self.dte_min), int(self.dte_max)


def load_filter_config(
    criteria: CriteriaConfig | None = None,
    rules: Mapping[str, Any] | None = None,
) -> FilterConfig:
    """Return filter config derived from :class:`CriteriaConfig` and rules."""

    crit = criteria or load_criteria()
    strike_rules = crit.strike
    rule_data: Mapping[str, Any] = rules or {}

    delta_values: Sequence[Any] | None = None
    candidate = rule_data.get("delta_range")
    if _is_range(candidate):
        delta_values = candidate  # type: ignore[assignment]
    elif _is_range(rule_data.get("short_delta_range")):
        delta_values = rule_data["short_delta_range"]  # type: ignore[index]

    dte_values: Sequence[Any] | None = None
    if _is_range(rule_data.get("dte_range")):
        dte_values = rule_data["dte_range"]  # type: ignore[index]

    delta_min = (
        _as_float(delta_values[0], strike_rules.delta_min)
        if delta_values and len(delta_values) >= 1
        else strike_rules.delta_min
    )
    delta_max = (
        _as_float(delta_values[1], strike_rules.delta_max)
        if delta_values and len(delta_values) >= 2
        else strike_rules.delta_max
    )

    dte_min = (
        _as_int(dte_values[0], DEFAULT_DTE_RANGE[0])
        if dte_values and len(dte_values) >= 1
        else DEFAULT_DTE_RANGE[0]
    )
    dte_max = (
        _as_int(dte_values[1], DEFAULT_DTE_RANGE[1])
        if dte_values and len(dte_values) >= 2
        else DEFAULT_DTE_RANGE[1]
    )

    return FilterConfig(
        delta_min=delta_min,
        delta_max=delta_max,
        min_rom=_as_float(rule_data.get("min_rom"), strike_rules.min_rom),
        min_edge=_as_float(rule_data.get("min_edge"), strike_rules.min_edge),
        min_pos=_as_float(rule_data.get("min_pos"), strike_rules.min_pos),
        min_ev=_as_float(rule_data.get("min_ev"), strike_rules.min_ev),
        skew_min=_as_float(rule_data.get("skew_min"), strike_rules.skew_min),
        skew_max=_as_float(rule_data.get("skew_max"), strike_rules.skew_max),
        term_min=_as_float(rule_data.get("term_min"), strike_rules.term_min),
        term_max=_as_float(rule_data.get("term_max"), strike_rules.term_max),
        dte_min=dte_min,
        dte_max=dte_max,
        max_gamma=_as_optional_float(rule_data.get("max_gamma"), safe_float(strike_rules.max_gamma)),
        max_vega=_as_optional_float(rule_data.get("max_vega"), safe_float(strike_rules.max_vega)),
        min_theta=_as_optional_float(rule_data.get("min_theta"), safe_float(strike_rules.min_theta)),
    )
def filter_by_expiry(
    options: List[Dict[str, Any]],
    dte_range: Tuple[int, int],
) -> List[Dict[str, Any]]:
    """Return ``options`` filtered by DTE within ``dte_range``."""

    return filter_by_dte(options, lambda opt: opt.get("expiry"), dte_range)


class StrikeSelector:
    """Filter option strikes based on configurable criteria."""

    def __init__(
        self, config: FilterConfig | None = None, criteria: CriteriaConfig | None = None
    ) -> None:
        self._criteria = criteria or load_criteria()
        self.config = config or load_filter_config(self._criteria)
        self._filters: List[Tuple[str, Callable[[Dict[str, Any]], Tuple[bool, str]]]] = [
            ("delta", self._delta_filter),
            ("rom", self._rom_filter),
            ("edge", self._edge_filter),
            ("pos", self._pos_filter),
            ("ev", self._ev_filter),
            ("skew", self._skew_filter),
            ("term", self._term_filter),
            ("greeks", self._greek_filter),
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def select(
        self,
        options: List[Dict[str, Any]],
        *,
        dte_range: Tuple[int, int] | None = None,
        debug_csv: str | os.PathLike[str] | None = None,
        return_info: bool = False,
    ) -> (
        List[Dict[str, Any]]
        | Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, int]]
    ):
        """Return ``options`` filtered by expiry and configured criteria.

        When ``return_info`` is :data:`True`, a tuple of ``(selected,
        reasons, by_filter)`` is returned where ``reasons`` contains counts of
        individual rejection reasons and ``by_filter`` aggregates these counts
        per filter category.
        """

        logger.debug(
            f"StrikeSelector start: {len(options)} options, dte_range={dte_range}, config={self.config}"
        )

        working = options
        if dte_range is not None:
            working = filter_by_expiry(working, dte_range)
            logger.debug(
                f"After expiry filter {dte_range}: {len(working)} options remain"
            )
        else:
            logger.debug(f"No expiry filter applied: {len(working)} options")

        selected: List[Dict[str, Any]] = []
        reasons: Dict[str, int] = {}
        by_filter: Dict[str, int] = {}
        rejected_rows: List[Dict[str, Any]] = []
        for opt in working:
            ok, reason = self._passes(opt)
            if ok:
                logger.debug(
                    f"✅ Accept {opt.get('expiry')} {opt.get('strike')} {opt.get('type')}"
                )
                selected.append(opt)
            else:
                logger.debug(
                    f"❌ Reject {opt.get('expiry')} {opt.get('strike')} {opt.get('type')}"
                )
                reasons[reason] = reasons.get(reason, 0) + 1
                cat = reason.split(":", 1)[0]
                by_filter[cat] = by_filter.get(cat, 0) + 1
                if debug_csv:
                    row = dict(opt)
                    row["reject_reason"] = reason
                    rejected_rows.append(row)
        logger.debug(f"StrikeSelector result: {len(selected)}/{len(working)} kept")
        for flt, cnt in by_filter.items():
            logger.debug(f"- {cnt} rejected by {flt} filter")

        if debug_csv and rejected_rows:
            try:
                with open(debug_csv, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=rejected_rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rejected_rows)
                logger.info(f"Debug rejects written to {os.fspath(debug_csv)}")
            except Exception as exc:
                logger.warning(f"Failed to write debug CSV {debug_csv}: {exc}")

        if not selected and rejected_rows:
            preview = rejected_rows[:3]
            logger.debug("Top rejected options:")
            for row in preview:
                logger.debug(
                    f"- {row.get('expiry')} {row.get('strike')} {row.get('type')}: {row.get('reject_reason')}"
                )

        if len(selected) == 0:
            logger.info(
                f"[FILTER] Geen opties over na filtering — config: delta={self.config.delta_min}..{self.config.delta_max}, rom={self.config.min_rom}, dte={dte_range}, edge={self.config.min_edge}"
            )
        if return_info:
            return selected, reasons, by_filter
        return selected

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------
    def _passes(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        for name, func in self._filters:
            ok, reason = func(option)
            if not ok:
                msg = f"{name}: {reason}"
                logger.debug(
                    f"❌ [{name}] {option.get('expiry')} {option.get('strike')}: {reason}"
                )
                return False, msg
        return True, ""

    def _delta_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        delta = safe_float(option.get("delta") or option.get("Delta"))
        if delta is None:
            return True, ""
        if delta < self.config.delta_min or delta > self.config.delta_max:
            return (
                False,
                f"delta {delta:+.2f} outside {self.config.delta_min}..{self.config.delta_max}",
            )
        return True, ""

    def _rom_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        rom = safe_float(option.get("rom"))
        if rom is None:
            return True, ""
        if rom < self.config.min_rom:
            return False, f"ROM {rom:.1f}% < {self.config.min_rom}"
        return True, ""

    def _edge_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        edge = safe_float(option.get("edge"))
        if edge is None:
            return True, ""
        if edge < self.config.min_edge:
            return False, f"edge {edge:.2f} < {self.config.min_edge}"
        return True, ""

    def _pos_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        pos = safe_float(option.get("pos"))
        if pos is None:
            return True, ""
        if pos < self.config.min_pos:
            return False, f"PoS {pos:.1f}% < {self.config.min_pos}"
        return True, ""

    def _ev_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        ev = safe_float(option.get("ev"))
        if ev is None:
            return True, ""
        if ev < self.config.min_ev:
            return False, f"EV {ev:.2f} < {self.config.min_ev}"
        return True, ""

    def _skew_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        skew = safe_float(option.get("skew"))
        if skew is None:
            return True, ""
        if skew < self.config.skew_min or skew > self.config.skew_max:
            return (
                False,
                f"skew {skew:+.2f} outside {self.config.skew_min}..{self.config.skew_max}",
            )
        return True, ""

    def _term_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        term = safe_float(option.get("term_m1_m3"))
        if term is None:
            return True, ""
        if term < self.config.term_min or term > self.config.term_max:
            return (
                False,
                f"term {term:+.2f} outside {self.config.term_min}..{self.config.term_max}",
            )
        return True, ""

    def _greek_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        gamma = safe_float(option.get("gamma") or option.get("Gamma"))
        if (
            self.config.max_gamma is not None
            and gamma is not None
            and abs(gamma) > self.config.max_gamma
        ):
            return False, f"gamma {gamma:+.2f} > {self.config.max_gamma}"

        vega = safe_float(option.get("vega") or option.get("Vega"))
        if (
            self.config.max_vega is not None
            and vega is not None
            and abs(vega) > self.config.max_vega
        ):
            return False, f"vega {vega:+.2f} > {self.config.max_vega}"

        theta = safe_float(option.get("theta") or option.get("Theta"))
        if (
            self.config.min_theta is not None
            and theta is not None
            and theta < self.config.min_theta
        ):
            return False, f"theta {theta:+.2f} < {self.config.min_theta}"

        return True, ""


__all__ = [
    "StrikeSelector",
    "FilterConfig",
    "load_filter_config",
    "filter_by_expiry",
]
