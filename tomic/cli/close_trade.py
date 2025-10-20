"""Interactive helper to close a trade in the journal."""

from __future__ import annotations

from typing import Dict

from tomic.logutils import logger
from tomic.logutils import setup_logging

from tomic.journal.close_service import (
    TradeClosureError,
    TradeClosureInput,
    close_trade as close_trade_service,
    list_open_trades,
)
from .common import prompt


def load_journal() -> list[Dict[str, object]]:
    """Compatibility shim used by tests to stub journal data."""

    return list_open_trades()


def _collect_evaluatie() -> str:
    print("\n🧠 Evaluatie:")
    print("Zeg iets over:")
    print(
        "- je marktinschatting (IV, richting), effectiviteit van je edge (skew, premie vs risico)"
    )
    print(
        "- je risicomanagement: wat verwachtte je, wat gebeurde er, wat concludeer je?"
    )
    print("Typ '.' op een lege regel om te stoppen:")

    lijnen: list[str] = []
    while True:
        regel = prompt("> ")
        if regel.strip() == ".":
            break
        lijnen.append(regel)
    return "\n".join(lijnen)


def _vraag_exit_details(trade: Dict[str, object]) -> TradeClosureInput:
    logger.info(
        f"\n🔚 Trade afsluiten: {trade['TradeID']} - {trade.get('Symbool')} - {trade.get('Type')}"
    )

    datum_uit = prompt("📆 DatumUit (YYYY-MM-DD): ")
    entry_price = trade.get("EntryPrice", "?")
    exit_price_input = prompt(f"💰 Exitprijs (de entry prijs was: {entry_price}): ")
    resultaat = prompt("📉 Resultaat ($): ")
    return_on_margin = prompt("📊 Return on Margin (%): ")
    evaluatie = _collect_evaluatie()

    return TradeClosureInput(
        datum_uit=datum_uit,
        exit_price=exit_price_input or None,
        resultaat=resultaat or None,
        return_on_margin=return_on_margin or None,
        evaluatie=evaluatie or None,
    )


def main() -> None:
    """Interactive wrapper to close a trade from ``journal.json``."""

    setup_logging()
    logger.info("🚀 Trade afsluiten")

    open_trades = load_journal()
    if not open_trades:
        logger.warning("Geen open trades gevonden.")
        return

    print("\n📋 Open trades:")
    for t in open_trades:
        print(f"- {t['TradeID']}: {t.get('Symbool')} - {t.get('Type')}")

    keuze = prompt("\nVoer TradeID in om af te sluiten: ")
    gekozen_trade = next(
        (t for t in open_trades if str(t.get("TradeID")) == keuze),
        None,
    )
    if not gekozen_trade:
        logger.error("❌ TradeID niet gevonden of niet open.")
        return

    sluit_trade_af(gekozen_trade)


def sluit_trade_af(trade: Dict[str, object]) -> None:
    """Collect exit details for ``trade`` and persist the closure."""

    details = _vraag_exit_details(trade)
    trade_id = str(trade.get("TradeID"))

    try:
        close_trade_service(trade_id, details)
    except TradeClosureError as exc:
        logger.error(f"❌ Afsluiten mislukt: {exc}")
        return

    logger.success("✅ Trade afgesloten")


if __name__ == "__main__":
    main()
