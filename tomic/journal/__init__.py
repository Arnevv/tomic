"""High level API for managing the trading journal.

This module exposes convenience functions that wrap the interactive
utilities found in the submodules.  Wrapper scripts can simply import
``tomic.journal`` and call the desired helper instead of reaching into
the individual modules.
"""


__all__ = [
    "add_trade",
    "close_trade",
    "link_positions",
    "update_margins",
    "inspect_journal",
]

def add_trade() -> None:
    """Launch the interactive flow for adding a trade."""

    from .journal_updater import interactieve_trade_invoer

    interactieve_trade_invoer()


def close_trade() -> None:
    """Launch the interactive flow for closing a trade."""

    from tomic.cli.close_trade import main as close_trade_main

    close_trade_main()


def link_positions() -> None:
    """Link existing IB positions to journal legs interactively."""

    from tomic.cli.link_positions import main as link_positions_main

    link_positions_main()


def update_margins() -> None:
    """Recalculate the initial margin for all trades."""

    from .update_margins import update_all_margins

    update_all_margins()


def inspect_journal() -> None:
    """Start the journal inspector CLI."""

    from .journal_inspector import main as inspect_main

    inspect_main()

