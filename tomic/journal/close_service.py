"""Service helpers for closing trades in the journal.

This module centralises the domain logic that is required to mark a trade
as closed.  It can be reused from interactive CLIs as well as from automated
workflows where trades need to be closed programmatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List

from tomic.logutils import logger

from .service import is_valid_trade_id, load_journal, update_trade


class TradeClosureError(RuntimeError):
    """Raised when a trade could not be closed."""


@dataclass(frozen=True)
class TradeClosureInput:
    """Raw user input required to close a trade.

    The CLI layer is responsible for collecting these fields.  This dataclass
    keeps the service API explicit and makes it easy to construct instances
    from other call sites (tests, automation, ...).
    """

    datum_uit: str
    exit_price: str | None = None
    resultaat: str | None = None
    return_on_margin: str | None = None
    evaluatie: str | None = None


def list_open_trades(path: str | None = None) -> List[Dict[str, Any]]:
    """Return all open trades from the journal at ``path``."""

    journal = load_journal(path) if path is not None else load_journal()
    return [trade for trade in journal if trade.get("Status") == "Open"]


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_days_in_trade(datum_in: str | None, datum_uit: str) -> int | None:
    if not datum_in:
        return None
    try:
        d_in = datetime.strptime(str(datum_in), "%Y-%m-%d")
        d_out = datetime.strptime(datum_uit, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (d_out - d_in).days


def close_trade(
    trade_id: str,
    details: TradeClosureInput,
    *,
    path: str | None = None,
) -> Dict[str, Any]:
    """Close the trade identified by ``trade_id``.

    ``details`` should contain the raw answers collected from the user.  The
    service performs validation and type conversions before updating the
    journal.  The updated trade dictionary is returned.
    """

    if not is_valid_trade_id(trade_id):
        raise TradeClosureError(f"Ongeldige TradeID: {trade_id}")

    journal: Iterable[Dict[str, Any]]
    journal = load_journal(path) if path is not None else load_journal()
    original = next((t for t in journal if t.get("TradeID") == trade_id), None)
    if not isinstance(original, dict):
        raise TradeClosureError(f"TradeID niet gevonden: {trade_id}")

    updates: Dict[str, Any] = {}
    datum_uit = details.datum_uit.strip()
    if not datum_uit:
        raise TradeClosureError("DatumUit is verplicht")

    updates["DatumUit"] = datum_uit
    days_in_trade = _parse_days_in_trade(original.get("DatumIn"), datum_uit)
    if days_in_trade is not None:
        updates["DaysInTrade"] = days_in_trade
    else:
        logger.warning("Could not determine DaysInTrade", extra={"trade": trade_id})

    exit_price = _safe_float(details.exit_price)
    if exit_price is not None:
        updates["ExitPrice"] = exit_price
    elif details.exit_price:
        logger.warning("ExitPrice niet gezet door ongeldige invoer", extra={"trade": trade_id})

    result = _safe_float(details.resultaat)
    if result is not None:
        updates["Resultaat"] = result
    elif details.resultaat:
        logger.warning("Resultaat niet gezet door ongeldige invoer", extra={"trade": trade_id})

    rom = _safe_float(details.return_on_margin)
    if rom is not None:
        updates["ReturnOnMargin"] = rom
    elif details.return_on_margin:
        logger.warning(
            "ReturnOnMargin niet gezet door ongeldige invoer",
            extra={"trade": trade_id},
        )

    if details.evaluatie:
        updates["Evaluatie"] = details.evaluatie

    updates["Status"] = "Gesloten"

    success = update_trade(trade_id, updates, path)
    if not success:
        raise TradeClosureError(f"Bijwerken van trade {trade_id} mislukt")

    updated_trade = dict(original)
    updated_trade.update(updates)
    return updated_trade


__all__ = ["TradeClosureInput", "TradeClosureError", "list_open_trades", "close_trade"]

