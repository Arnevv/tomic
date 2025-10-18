from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass
class ControlPanelSession:
    """Typed container for runtime state shared between menu steps."""

    run_id: str | None = None
    config_hash: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    spot_price: float | None = None
    next_earnings: str | None = None
    days_until_earnings: int | None = None
    evaluated_trades: list[Any] = field(default_factory=list)
    combo_evaluations: list[Any] = field(default_factory=list)
    combo_evaluation_summary: Any | None = None

    def clear_combo_results(self) -> None:
        self.combo_evaluations.clear()
        self.combo_evaluation_summary = None

    def set_combo_results(self, evaluations: Iterable[Any], summary: Any | None) -> None:
        self.combo_evaluations = list(evaluations)
        self.combo_evaluation_summary = summary

    def update_from_mapping(self, mapping: Mapping[str, Any]) -> None:
        if "symbol" in mapping:
            symbol = mapping.get("symbol")
            self.symbol = str(symbol).strip().upper() if symbol else None
        if "strategy" in mapping:
            strategy = mapping.get("strategy")
            self.strategy = str(strategy).strip() if strategy else None
        if "spot_price" in mapping or "spot" in mapping:
            spot_val = mapping.get("spot_price", mapping.get("spot"))
            self.spot_price = _to_float_or_none(spot_val)
        if "next_earnings" in mapping:
            next_earnings = mapping.get("next_earnings")
            self.next_earnings = str(next_earnings) if next_earnings else None
        if "days_until_earnings" in mapping:
            days = mapping.get("days_until_earnings")
            try:
                self.days_until_earnings = int(days) if days is not None else None
            except (TypeError, ValueError):
                self.days_until_earnings = None


def _to_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
