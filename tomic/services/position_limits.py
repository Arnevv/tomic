"""Position limits governance for automated entry flows.

This module provides guardrails to prevent opening too many positions,
enforcing configurable limits on total open trades and trades per symbol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from tomic.config import get as cfg_get
from tomic.journal.close_service import list_open_trades
from tomic.logutils import logger


@dataclass(frozen=True)
class PositionLimitsConfig:
    """Configuration for position limits enforcement."""

    max_open_trades: int = 5
    max_per_symbol: int = 1

    @classmethod
    def from_config(cls) -> "PositionLimitsConfig":
        """Load limits from application configuration."""
        return cls(
            max_open_trades=int(cfg_get("ENTRY_FLOW_MAX_OPEN_TRADES", 5)),
            max_per_symbol=int(cfg_get("ENTRY_FLOW_MAX_PER_SYMBOL", 1)),
        )


@dataclass(frozen=True)
class PositionLimitsResult:
    """Result of position limits evaluation."""

    open_count: int
    symbols_with_positions: frozenset[str]
    available_slots: int
    can_open_any: bool


def _extract_symbol(trade: Mapping[str, Any]) -> str | None:
    """Extract normalized symbol from a trade record."""
    symbol = trade.get("Symbool") or trade.get("symbol") or trade.get("Symbol")
    if symbol:
        return str(symbol).strip().upper()
    return None


def evaluate_position_limits(
    config: PositionLimitsConfig | None = None,
    *,
    journal_path: str | None = None,
) -> PositionLimitsResult:
    """Evaluate current position limits against open trades.

    Args:
        config: Position limits configuration. Uses defaults if not provided.
        journal_path: Optional path to journal file.

    Returns:
        PositionLimitsResult with current state and available capacity.
    """
    if config is None:
        config = PositionLimitsConfig.from_config()

    open_trades = list_open_trades(journal_path)
    open_count = len(open_trades)

    symbols: set[str] = set()
    for trade in open_trades:
        symbol = _extract_symbol(trade)
        if symbol:
            symbols.add(symbol)

    available_slots = max(0, config.max_open_trades - open_count)
    can_open_any = available_slots > 0

    logger.debug(
        "Position limits: open=%d, max=%d, available=%d, symbols=%s",
        open_count,
        config.max_open_trades,
        available_slots,
        sorted(symbols),
    )

    return PositionLimitsResult(
        open_count=open_count,
        symbols_with_positions=frozenset(symbols),
        available_slots=available_slots,
        can_open_any=can_open_any,
    )


def can_open_position(
    symbol: str,
    config: PositionLimitsConfig | None = None,
    *,
    journal_path: str | None = None,
    current_state: PositionLimitsResult | None = None,
) -> tuple[bool, str]:
    """Check if a new position can be opened for the given symbol.

    Args:
        symbol: The symbol to check.
        config: Position limits configuration.
        journal_path: Optional path to journal file.
        current_state: Pre-computed limits state to avoid re-loading journal.

    Returns:
        Tuple of (allowed, reason).
    """
    if config is None:
        config = PositionLimitsConfig.from_config()

    if current_state is None:
        current_state = evaluate_position_limits(config, journal_path=journal_path)

    symbol_upper = symbol.strip().upper()

    # Check total limit
    if not current_state.can_open_any:
        return False, f"max_open_trades_reached ({current_state.open_count}/{config.max_open_trades})"

    # Check per-symbol limit
    if symbol_upper in current_state.symbols_with_positions:
        return False, f"symbol_already_open ({symbol_upper})"

    return True, "allowed"


def filter_candidates_by_limits(
    candidates: Sequence[Mapping[str, Any]],
    config: PositionLimitsConfig | None = None,
    *,
    journal_path: str | None = None,
) -> tuple[list[Mapping[str, Any]], list[tuple[Mapping[str, Any], str]]]:
    """Filter candidates based on position limits.

    Args:
        candidates: List of candidate trades to filter.
        config: Position limits configuration.
        journal_path: Optional path to journal file.

    Returns:
        Tuple of (allowed_candidates, rejected_with_reasons).
    """
    if config is None:
        config = PositionLimitsConfig.from_config()

    state = evaluate_position_limits(config, journal_path=journal_path)

    allowed: list[Mapping[str, Any]] = []
    rejected: list[tuple[Mapping[str, Any], str]] = []

    # Track symbols we're adding in this batch
    symbols_in_batch: set[str] = set()
    slots_used = 0

    for candidate in candidates:
        symbol = _extract_symbol(candidate)
        if not symbol:
            rejected.append((candidate, "missing_symbol"))
            continue

        # Check total limit (accounting for batch)
        remaining_slots = state.available_slots - slots_used
        if remaining_slots <= 0:
            rejected.append((candidate, f"max_open_trades_reached"))
            continue

        # Check per-symbol limit (accounting for existing + batch)
        if symbol in state.symbols_with_positions:
            rejected.append((candidate, f"symbol_already_open ({symbol})"))
            continue

        if symbol in symbols_in_batch:
            rejected.append((candidate, f"symbol_already_in_batch ({symbol})"))
            continue

        # Candidate passes
        allowed.append(candidate)
        symbols_in_batch.add(symbol)
        slots_used += 1

    logger.info(
        "Position limits filter: %d candidates -> %d allowed, %d rejected",
        len(candidates),
        len(allowed),
        len(rejected),
    )

    return allowed, rejected


__all__ = [
    "PositionLimitsConfig",
    "PositionLimitsResult",
    "can_open_position",
    "evaluate_position_limits",
    "filter_candidates_by_limits",
]
