"""High level helpers for manipulating the trading journal."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .utils import JOURNAL_FILE, load_journal, save_journal


def add_trade(trade: Dict[str, Any], path: str | None = None) -> None:
    """Append ``trade`` to the journal stored at ``path``."""
    journal = load_journal(path or JOURNAL_FILE)
    journal.append(trade)
    save_journal(journal, path or JOURNAL_FILE)


def update_trade(trade_id: Any, updates: Dict[str, Any], path: str | None = None) -> bool:
    """Update a trade by ``trade_id`` with ``updates``.

    Returns ``True`` when a trade was updated.
    """
    journal = load_journal(path or JOURNAL_FILE)
    for trade in journal:
        if trade.get("TradeID") == trade_id:
            trade.update(updates)
            save_journal(journal, path or JOURNAL_FILE)
            return True
    return False


__all__ = ["add_trade", "update_trade", "load_journal", "save_journal"]
