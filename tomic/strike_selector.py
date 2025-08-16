from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import os
import csv

from datetime import datetime

from .utils import today

from .logutils import logger
from .criteria import CriteriaConfig, load_criteria


def _as_float(value: Any) -> Optional[float]:
    """Return ``value`` as ``float`` if possible."""
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


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
        ]
        if self.max_gamma is not None:
            parts.append(f"gamma<={self.max_gamma}")
        if self.max_vega is not None:
            parts.append(f"vega<={self.max_vega}")
        if self.min_theta is not None:
            parts.append(f"theta>={self.min_theta}")
        return " ".join(parts)


def load_filter_config(criteria: CriteriaConfig | None = None) -> FilterConfig:
    """Return filter config derived from :class:`CriteriaConfig`."""

    crit = criteria or load_criteria()
    s = crit.strike
    return FilterConfig(
        delta_min=s.delta_min,
        delta_max=s.delta_max,
        min_rom=s.min_rom,
        min_edge=s.min_edge,
        min_pos=s.min_pos,
        min_ev=s.min_ev,
        skew_min=s.skew_min,
        skew_max=s.skew_max,
        term_min=s.term_min,
        term_max=s.term_max,
        max_gamma=_as_float(s.max_gamma),
        max_vega=_as_float(s.max_vega),
        min_theta=_as_float(s.min_theta),
    )


def _dte(expiry: str) -> Optional[int]:
    """Return days to expiry for ``expiry``."""
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            exp_date = datetime.strptime(str(expiry), fmt).date()
            return (exp_date - today()).days
        except Exception:
            continue
    return None


def filter_by_expiry(
    options: List[Dict[str, Any]],
    dte_range: Tuple[int, int],
) -> List[Dict[str, Any]]:
    """Return ``options`` for all expiries whose DTE lies within ``dte_range``.

    All options belonging to an expiry with a days-to-expiry (DTE) between
    ``min_dte`` and ``max_dte`` (inclusive) are returned. Expiries outside the
    range are ignored.
    """

    min_dte, max_dte = dte_range

    exp_map: Dict[str, List[Dict[str, Any]]] = {}
    for opt in options:
        exp = opt.get("expiry")
        if exp:
            exp_map.setdefault(str(exp), []).append(opt)

    included: List[tuple[str, int]] = []
    for exp, opts in exp_map.items():
        dte = _dte(exp)
        if dte is not None and min_dte <= dte <= max_dte:
            included.append((exp, dte))

    if not included:
        logger.info(
            f"filter_by_expiry: no expiries within range {min_dte}-{max_dte} DTE"
        )
        return []

    included.sort(key=lambda t: t[1])

    selected: List[Dict[str, Any]] = []
    for exp, dte in included:
        logger.info(f"Including expiry {exp} (DTE {dte})")
        selected.extend(exp_map[exp])

    logger.info(
        f"filter_by_expiry selected {len(selected)} options across {len(included)} expiries"
    )
    return selected


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
    ) -> List[Dict[str, Any]]:
        """Return ``options`` filtered by expiry and configured criteria."""

        logger.info(
            f"StrikeSelector start: {len(options)} options, dte_range={dte_range}, config={self.config}"
        )

        working = options
        if dte_range is not None:
            working = filter_by_expiry(working, dte_range)
            logger.info(
                f"After expiry filter {dte_range}: {len(working)} options remain"
            )
        else:
            logger.info(f"No expiry filter applied: {len(working)} options")

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
        logger.info(f"StrikeSelector result: {len(selected)}/{len(working)} kept")
        for flt, cnt in by_filter.items():
            logger.info(f"- {cnt} rejected by {flt} filter")

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
            logger.info("Top rejected options:")
            for row in preview:
                logger.info(
                    f"- {row.get('expiry')} {row.get('strike')} {row.get('type')}: {row.get('reject_reason')}"
                )

        if len(selected) == 0:
            logger.info(
                f"[FILTER] Geen opties over na filtering — config: delta={self.config.delta_min}..{self.config.delta_max}, rom={self.config.min_rom}, dte={dte_range}, edge={self.config.min_edge}"
            )

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
        delta = _as_float(option.get("delta") or option.get("Delta"))
        if delta is None:
            return True, ""
        if delta < self.config.delta_min or delta > self.config.delta_max:
            return (
                False,
                f"delta {delta:+.2f} outside {self.config.delta_min}..{self.config.delta_max}",
            )
        return True, ""

    def _rom_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        rom = _as_float(option.get("rom"))
        if rom is None:
            return True, ""
        if rom < self.config.min_rom:
            return False, f"ROM {rom:.1f}% < {self.config.min_rom}"
        return True, ""

    def _edge_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        edge = _as_float(option.get("edge"))
        if edge is None:
            return True, ""
        if edge < self.config.min_edge:
            return False, f"edge {edge:.2f} < {self.config.min_edge}"
        return True, ""

    def _pos_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        pos = _as_float(option.get("pos"))
        if pos is None:
            return True, ""
        if pos < self.config.min_pos:
            return False, f"PoS {pos:.1f}% < {self.config.min_pos}"
        return True, ""

    def _ev_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        ev = _as_float(option.get("ev"))
        if ev is None:
            return True, ""
        if ev < self.config.min_ev:
            return False, f"EV {ev:.2f} < {self.config.min_ev}"
        return True, ""

    def _skew_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        skew = _as_float(option.get("skew"))
        if skew is None:
            return True, ""
        if skew < self.config.skew_min or skew > self.config.skew_max:
            return (
                False,
                f"skew {skew:+.2f} outside {self.config.skew_min}..{self.config.skew_max}",
            )
        return True, ""

    def _term_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        term = _as_float(option.get("term_m1_m3"))
        if term is None:
            return True, ""
        if term < self.config.term_min or term > self.config.term_max:
            return (
                False,
                f"term {term:+.2f} outside {self.config.term_min}..{self.config.term_max}",
            )
        return True, ""

    def _greek_filter(self, option: Dict[str, Any]) -> Tuple[bool, str]:
        gamma = _as_float(option.get("gamma") or option.get("Gamma"))
        if (
            self.config.max_gamma is not None
            and gamma is not None
            and abs(gamma) > self.config.max_gamma
        ):
            return False, f"gamma {gamma:+.2f} > {self.config.max_gamma}"

        vega = _as_float(option.get("vega") or option.get("Vega"))
        if (
            self.config.max_vega is not None
            and vega is not None
            and abs(vega) > self.config.max_vega
        ):
            return False, f"vega {vega:+.2f} > {self.config.max_vega}"

        theta = _as_float(option.get("theta") or option.get("Theta"))
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
