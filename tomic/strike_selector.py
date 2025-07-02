from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import os
import csv

from datetime import datetime

from .utils import today

from .config import get as cfg_get
from .logutils import logger


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

    delta_min: float = -0.8
    delta_max: float = 0.8
    min_rom: float = 0.0
    min_edge: float = 0.0
    min_pos: float = 0.0
    min_ev: float = 0.0
    skew_min: float = -0.1
    skew_max: float = 0.1
    term_min: float = -0.2
    term_max: float = 0.2
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


def load_filter_config() -> FilterConfig:
    """Return filter config from YAML or defaults."""

    return FilterConfig(
        delta_min=_as_float(cfg_get("DELTA_MIN", -0.8)) or -0.8,
        delta_max=_as_float(cfg_get("DELTA_MAX", 0.8)) or 0.8,
        min_rom=_as_float(cfg_get("STRIKE_MIN_ROM", 0.0)) or 0.0,
        min_edge=_as_float(cfg_get("STRIKE_MIN_EDGE", 0.0)) or 0.0,
        min_pos=_as_float(cfg_get("STRIKE_MIN_POS", 0.0)) or 0.0,
        min_ev=_as_float(cfg_get("STRIKE_MIN_EV", 0.0)) or 0.0,
        skew_min=_as_float(cfg_get("STRIKE_SKEW_MIN", -0.1)) or -0.1,
        skew_max=_as_float(cfg_get("STRIKE_SKEW_MAX", 0.1)) or 0.1,
        term_min=_as_float(cfg_get("STRIKE_TERM_MIN", -0.2)) or -0.2,
        term_max=_as_float(cfg_get("STRIKE_TERM_MAX", 0.2)) or 0.2,
        max_gamma=_as_float(cfg_get("STRIKE_MAX_GAMMA", None)),
        max_vega=_as_float(cfg_get("STRIKE_MAX_VEGA", None)),
        min_theta=_as_float(cfg_get("STRIKE_MIN_THETA", None)),
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
    *,
    multi: bool = False,
) -> List[Dict[str, Any]]:
    """Return ``options`` filtered to expiries within ``dte_range``.

    When ``multi`` is ``True``, include the nearest expiry in range and a second
    expiry at least 20 days later when available.
    """

    min_dte, max_dte = dte_range
    exp_map: Dict[str, List[Dict[str, Any]]] = {}
    for opt in options:
        exp = opt.get("expiry")
        if exp:
            exp_map.setdefault(str(exp), []).append(opt)

    valid: List[tuple[str, int]] = []
    for exp in exp_map:
        dte = _dte(exp)
        if dte is not None and min_dte <= dte <= max_dte:
            valid.append((exp, dte))

    if not valid:
        return []

    valid.sort(key=lambda t: t[1])
    selected: List[Dict[str, Any]] = []

    first_exp, first_dte = valid[0]
    selected.extend(exp_map[first_exp])

    if multi:
        for exp, dte in valid[1:]:
            if dte - first_dte >= 20:
                selected.extend(exp_map[exp])
                break

    return selected


class StrikeSelector:
    """Filter option strikes based on configurable criteria."""

    def __init__(self, config: FilterConfig | None = None) -> None:
        self.config = config or load_filter_config()
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
        multi: bool = False,
        debug_csv: str | os.PathLike[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Return ``options`` filtered by expiry and configured criteria."""

        logger.info(
            "StrikeSelector start: %s options, dte_range=%s, multi=%s, config=%s",
            len(options),
            dte_range,
            multi,
            self.config,
        )

        working = options
        if dte_range is not None:
            working = filter_by_expiry(working, dte_range, multi=multi)
            logger.info(
                "After expiry filter %s: %s options remain",
                dte_range,
                len(working),
            )
        else:
            logger.info("No expiry filter applied: %s options", len(working))

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
            logger.info("- %d rejected by %s filter", cnt, flt)

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
                    "- %s %s %s: %s",
                    row.get("expiry"),
                    row.get("strike"),
                    row.get("type"),
                    row.get("reject_reason"),
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
        term = _as_float(option.get("term") or option.get("term_slope"))
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
