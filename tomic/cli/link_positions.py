"""Utility to link IB position IDs to journal trades."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from tomic.logging import logger

from tomic.config import get as cfg_get
from tomic.logging import setup_logging
from tomic.journal.utils import load_journal, save_journal, load_json

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))
POSITIONS_FILE = Path(cfg_get("POSITIONS_FILE", "positions.json"))


def list_open_trades(journal: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Display open trades and return them."""
    open_trades = [t for t in journal if t.get("Status") == "Open"]
    print("\n📋 Open trades:")
    for t in open_trades:
        print(f"- {t['TradeID']}: {t['Symbool']} - {t['Type']}")
    return open_trades


def choose_trade(open_trades: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the selected trade from ``open_trades`` or ``None``."""
    keuze = input("\nVoer TradeID in (ENTER om te stoppen): ").strip()
    if not keuze:
        return None
    return next((t for t in open_trades if t["TradeID"] == keuze), None)


def choose_leg(trade: Dict[str, Any]) -> int | None:
    """Return leg index to update or ``None``."""
    print("\n📦 Legs:")
    legs = trade.get("Legs", [])
    for i, leg in enumerate(legs, 1):
        print(f"{i}. {leg['action']} {leg['qty']}x {leg['type']} @ {leg['strike']}")
    keuze = input("Kies leg nummer om conId toe te voegen (ENTER voor terug): ").strip()
    if not keuze:
        return None
    if not keuze.isdigit() or int(keuze) not in range(1, len(legs) + 1):
        logger.error("❌ Ongeldige keuze.")
        return None
    return int(keuze) - 1


def list_positions(
    symbol: str, positions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Print positions for ``symbol`` and return them."""
    sym_pos = [p for p in positions if p.get("symbol") == symbol]
    if not sym_pos:
        logger.error("⚠️ Geen open posities gevonden voor dit symbool.")
        return []
    print(f"\n📈 Open posities voor {symbol}:")
    for p in sym_pos:
        exp = p.get("lastTradeDate") or p.get("expiry") or p.get("expiration")
        qty = p.get("position")
        qty_disp = int(qty) if qty is not None else "?"
        right = p.get("right")
        if right == "C":
            right_disp = "Call"
        elif right == "P":
            right_disp = "Put"
        else:
            right_disp = right or ""
        print(
            f"  {symbol}, {p.get('strike')} {right_disp}, {exp}, {qty_disp}, {p.get('conId')}"
        )
    return sym_pos


def main() -> None:
    """Interactively link position IDs from TWS to journal entries."""
    setup_logging()
    logger.info("🚀 Posities koppelen aan journal")
    journal = load_journal(JOURNAL_FILE)
    positions = load_json(POSITIONS_FILE)
    if not journal:
        return

    while True:
        open_trades = list_open_trades(journal)
        trade = choose_trade(open_trades)
        if not trade:
            break

        while True:
            list_positions(trade.get("Symbool"), positions)
            idx = choose_leg(trade)
            if idx is None:
                break
            conid_input = input("Voer conId in (ENTER om te annuleren): ").strip()
            if not conid_input:
                continue
            try:
                trade["Legs"][idx]["conId"] = int(conid_input)
                logger.info("✅ conId toegevoegd.")
                save_journal(journal)
                logger.info("✅ Wijzigingen opgeslagen.")
            except ValueError:
                logger.error("❌ Ongeldig conId.")

    logger.success("✅ Linken voltooid")


if __name__ == "__main__":
    main()
