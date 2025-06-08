"""High level helpers for manipulating the trading journal."""

from __future__ import annotations

from typing import Any, Dict

from .utils import JOURNAL_FILE, load_journal, save_journal
from tomic.logutils import logger


def is_valid_trade_id(tid: Any) -> bool:
    """Return ``True`` if ``tid`` represents a valid numeric TradeID."""

    return str(tid).isdigit()


def next_trade_id(path: str | None = None) -> str:
    """Return the next available TradeID for the journal at ``path``."""

    journal = load_journal(path or JOURNAL_FILE)
    existing = [
        int(t["TradeID"]) for t in journal if is_valid_trade_id(t.get("TradeID"))
    ]
    return str(max(existing + [0]) + 1)


def add_trade(trade: Dict[str, Any], path: str | None = None) -> None:
    """Append ``trade`` to the journal stored at ``path``."""
    journal_file = path or JOURNAL_FILE
    journal = load_journal(journal_file)
    journal.append(trade)
    save_journal(journal, journal_file)
    logger.info(f"➕ Trade added: {trade.get('TradeID')}")


def update_trade(
    trade_id: Any, updates: Dict[str, Any], path: str | None = None
) -> bool:
    """Update a trade by ``trade_id`` with ``updates``.

    Returns ``True`` when a trade was updated.
    """
    journal_file = path or JOURNAL_FILE
    journal = load_journal(journal_file)
    for trade in journal:
        if trade.get("TradeID") == trade_id:
            trade.update(updates)
            save_journal(journal, journal_file)
            logger.info(f"🔄 Trade updated: {trade_id}")
            return True
    logger.warning(f"⚠️ Trade not found: {trade_id}")
    return False


__all__ = [
    "add_trade",
    "update_trade",
    "load_journal",
    "save_journal",
    "next_trade_id",
    "is_valid_trade_id",
]
