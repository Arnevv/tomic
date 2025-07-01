from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    def select(self, options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return ``options`` filtered by configured criteria."""

        selected: List[Dict[str, Any]] = []
        for opt in options:
            if self._passes(opt):
                logger.debug(
                    f"✅ Accept {opt.get('expiry')} {opt.get('strike')} {opt.get('type')}"
                )
                selected.append(opt)
            else:
                logger.debug(
                    f"❌ Reject {opt.get('expiry')} {opt.get('strike')} {opt.get('type')}"
                )
        logger.info(f"StrikeSelector result: {len(selected)}/{len(options)} kept")
        return selected

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------
    def _passes(self, option: Dict[str, Any]) -> bool:
        for name, func in self._filters:
            ok, reason = func(option)
            if not ok:
                logger.debug(
                    f"❌ [{name}] {option.get('expiry')} {option.get('strike')}: {reason}"
                )
                return False
        return True

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


__all__ = ["StrikeSelector", "FilterConfig", "load_filter_config"]
