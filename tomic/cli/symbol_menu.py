"""Symbol management menu for the control panel.

Provides UI for managing symbols in the basket including:
- Basket overview with sector and liquidity info
- Adding/removing symbols
- Data synchronization
- Sector analysis
"""

from __future__ import annotations

from functools import partial
from typing import Optional

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.services.liquidity_service import LiquidityService, get_liquidity_service
from tomic.services.symbol_manager import SymbolManager, get_symbol_manager


def _format_number(n: Optional[int]) -> str:
    """Format number with thousands separator."""
    if n is None:
        return "-"
    return f"{n:,}"


def _format_status(status: str) -> str:
    """Format data status with emoji."""
    if status == "complete":
        return "\u2713 Complete"
    if status == "incomplete":
        return "\u26a0 Incomplete"
    return "\u2717 Missing"


def _print_header(title: str) -> None:
    """Print section header."""
    print(f"\n{title}")
    print("\u2500" * 70)


def show_basket_overview(manager: Optional[SymbolManager] = None) -> None:
    """Show basket overview with all symbols."""
    manager = manager or get_symbol_manager()
    overview = manager.get_basket_overview()

    _print_header(f"\U0001f4e6 BASKET OVERZICHT ({overview['total_symbols']} symbolen)")

    # Table header
    print(f"{'Symbol':<8} {'Sector':<25} {'Avg Vol':>12} {'Avg OI':>12} {'Status':<15}")
    print("\u2500" * 70)

    # Sort by sector then symbol
    symbols = sorted(overview["symbols"], key=lambda x: (x["sector"], x["symbol"]))

    for s in symbols:
        status = _format_status(s["data_status"])
        vol = _format_number(s["avg_atm_volume"])
        oi = _format_number(s["avg_atm_oi"])
        sector = (s["sector"] or "Unknown")[:24]

        print(f"{s['symbol']:<8} {sector:<25} {vol:>12} {oi:>12} {status:<15}")

    # Summary
    print("\u2500" * 70)
    avg_vol = _format_number(overview["avg_volume"])
    avg_oi = _format_number(overview["avg_oi"])
    print(f"Totaal: {overview['total_symbols']} symbolen | "
          f"{overview['sector_count']} sectors | "
          f"Gem: {avg_vol} vol / {avg_oi} OI")

    # Data status summary
    print(f"Data: {overview['data_complete']} complete, "
          f"{overview['data_incomplete']} incomplete, "
          f"{overview['data_missing']} missing")

    print()


def show_sector_analysis(manager: Optional[SymbolManager] = None) -> None:
    """Show sector diversification analysis."""
    manager = manager or get_symbol_manager()
    analysis = manager.get_sector_analysis()

    _print_header("\U0001f4ca SECTOR DIVERSIFICATIE")

    # Sort sectors by count descending
    sectors = sorted(
        analysis["sectors"].items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )

    max_bar = 30
    total = sum(s[1]["count"] for s in sectors)

    for sector, data in sectors:
        pct = data["percentage"]
        count = data["count"]
        bar_len = int(pct / 100 * max_bar) if pct > 0 else 0
        bar = "\u2588" * bar_len + "\u2591" * (max_bar - bar_len)

        # Warning for overweight
        warning = " \u26a0" if pct > 40 else ""

        print(f"{sector:<25} {count:>3} {pct:>5.1f}%  {bar}{warning}")

    # Recommendations
    if analysis["recommendations"]:
        print()
        print("Aanbevelingen:")
        for rec in analysis["recommendations"]:
            print(f"  \u2022 {rec}")

    print()


def show_liquidity_warnings(manager: Optional[SymbolManager] = None) -> None:
    """Show symbols with low liquidity."""
    manager = manager or get_symbol_manager()
    warnings = manager.get_liquidity_warnings(min_volume=10000)

    _print_header("\u26a0 LIQUIDITEIT WAARSCHUWINGEN")

    if not warnings:
        print("Geen symbolen met lage liquiditeit gevonden.")
        print()
        return

    print(f"{'Symbol':<8} {'Avg Vol':>12} {'Avg OI':>12} {'Waarschuwing':<30}")
    print("\u2500" * 70)

    for w in warnings:
        vol = _format_number(w["avg_volume"])
        oi = _format_number(w["avg_oi"])
        print(f"{w['symbol']:<8} {vol:>12} {oi:>12} {w['message']:<30}")

    print()


def add_symbols_interactive(manager: Optional[SymbolManager] = None) -> None:
    """Interactive symbol addition."""
    manager = manager or get_symbol_manager()

    _print_header("\U0001f4e5 SYMBOOL TOEVOEGEN")

    symbols_input = prompt("Symbolen (komma-gescheiden): ", "")
    if not symbols_input.strip():
        print("Geen symbolen opgegeven.")
        return

    # Parse symbols
    symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
    if not symbols:
        print("Geen geldige symbolen opgegeven.")
        return

    print(f"\nToevoegen van {len(symbols)} symbolen: {', '.join(symbols)}")

    # Options
    fetch_data = prompt_yes_no("Historische data ophalen?", True)
    fetch_sector = prompt_yes_no("Sector informatie ophalen?", True)

    print()

    # Progress callback
    def progress(symbol: str, status: str) -> None:
        print(f"  {symbol}: {status}")

    # Add symbols
    results = manager.add_symbols(
        symbols,
        fetch_data=fetch_data,
        fetch_sector=fetch_sector,
        fetch_liquidity=True,
        progress_callback=progress,
    )

    # Summary
    print()
    _print_header("RESULTAAT")

    for result in results:
        status_icon = "\u2713" if result.success else "\u2717"
        print(f"  {status_icon} {result.symbol}: {result.message}")

        if result.metadata:
            meta = result.metadata
            sector = meta.sector or "Unknown"
            vol = _format_number(meta.avg_atm_call_volume)
            oi = _format_number(meta.avg_atm_call_oi)
            print(f"      Sector: {sector}")
            print(f"      Liquiditeit: {vol} vol / {oi} OI")

        if result.validation:
            print(f"      Data: {_format_status(result.validation.status)}")

    print()


def remove_symbols_interactive(manager: Optional[SymbolManager] = None) -> None:
    """Interactive symbol removal."""
    manager = manager or get_symbol_manager()

    _print_header("\U0001f5d1 SYMBOOL VERWIJDEREN")

    # Show current symbols
    current = manager.symbol_service.get_configured_symbols()
    print(f"Huidige symbolen ({len(current)}): {', '.join(sorted(current)[:20])}")
    if len(current) > 20:
        print(f"  ... en {len(current) - 20} meer")
    print()

    symbols_input = prompt("Symbolen om te verwijderen (komma-gescheiden): ", "")
    if not symbols_input.strip():
        print("Geen symbolen opgegeven.")
        return

    # Parse symbols
    symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
    if not symbols:
        print("Geen geldige symbolen opgegeven.")
        return

    # Confirm
    print(f"\nTe verwijderen: {', '.join(symbols)}")
    if not prompt_yes_no("Weet je dit zeker?", False):
        print("Geannuleerd.")
        return

    delete_data = prompt_yes_no("Bijbehorende data bestanden verwijderen?", True)

    # Progress callback
    def progress(symbol: str, status: str) -> None:
        print(f"  {symbol}: {status}")

    # Remove symbols
    results = manager.remove_symbols(
        symbols,
        delete_data=delete_data,
        progress_callback=progress,
    )

    # Summary
    print()
    _print_header("RESULTAAT")

    for result in results:
        status_icon = "\u2713" if result.success else "\u2717"
        print(f"  {status_icon} {result.symbol}: {result.message}")

    print()


def sync_metadata_interactive(manager: Optional[SymbolManager] = None) -> None:
    """Interactive metadata sync."""
    manager = manager or get_symbol_manager()

    _print_header("\U0001f504 DATA SYNCHRONISEREN")

    current = manager.symbol_service.get_configured_symbols()
    print(f"Symbolen om te synchroniseren: {len(current)}")
    print()

    refresh_sector = prompt_yes_no("Sector informatie verversen?", True)
    refresh_liquidity = prompt_yes_no("Liquiditeit metrics verversen?", True)

    if not prompt_yes_no(f"Doorgaan met sync van {len(current)} symbolen?", True):
        print("Geannuleerd.")
        return

    print("\nSynchroniseren...")

    # Progress callback
    def progress(symbol: str, status: str) -> None:
        print(f"  {symbol}: {status}")

    results = manager.sync_metadata(
        refresh_sector=refresh_sector,
        refresh_liquidity=refresh_liquidity,
        progress_callback=progress,
    )

    print(f"\n\u2713 {len(results)} symbolen gesynchroniseerd.")
    print()


def show_orphaned_data(manager: Optional[SymbolManager] = None) -> None:
    """Show and optionally clean up orphaned data."""
    manager = manager or get_symbol_manager()

    _print_header("\U0001f9f9 VERWEESDE DATA")

    orphaned = manager.symbol_service.find_orphaned_data()

    if not orphaned:
        print("Geen verweesde data gevonden.")
        print()
        return

    print(f"Gevonden verweesde data voor {len(orphaned)} symbolen:\n")

    for symbol, files in sorted(orphaned.items()):
        print(f"  {symbol}:")
        for f in files:
            print(f"    - {f}")

    print()

    if prompt_yes_no("Verweesde data verwijderen?", False):
        deleted = manager.symbol_service.cleanup_orphaned_data()
        total_files = sum(len(files) for files in deleted.values())
        print(f"\n\u2713 {total_files} bestanden verwijderd.")

    print()


def show_orats_symbol_overview(liquidity_service: Optional[LiquidityService] = None) -> None:
    """Show overview of all symbols from most recent ORATS file.

    Displays symbols sorted by average ATM volume (252 days) with average OI.
    """
    service = liquidity_service or get_liquidity_service()

    _print_header("\U0001f4ca ORATS SYMBOOL OVERZICHT")

    # Find most recent file
    most_recent = service.get_most_recent_orats_file()
    if most_recent is None:
        print("Geen ORATS bestanden gevonden in cache.")
        print("Voer eerst een ORATS backfill uit om data te downloaden.")
        print()
        return

    # Extract date from filename
    try:
        date_str = most_recent.stem.split("_")[-1]
        file_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    except (ValueError, IndexError):
        file_date = "onbekend"

    print(f"Meest recente ORATS bestand: {most_recent.name}")
    print(f"Datum: {file_date}")
    print()

    # Get all symbols from file
    symbols = service.get_symbols_from_orats_file(most_recent)
    if not symbols:
        print("Geen symbolen gevonden in ORATS bestand.")
        print()
        return

    print(f"Gevonden: {len(symbols)} symbolen")
    print()

    # Ask for confirmation since this can take a while
    print("Let op: Het berekenen van gemiddelden over 252 dagen kan even duren.")
    if not prompt_yes_no(f"Doorgaan met analyse van {len(symbols)} symbolen?", True):
        print("Geannuleerd.")
        return

    print()
    print("Berekenen van liquiditeitsmetrics (geoptimaliseerd)...")
    print("Verwerking per datum (parallel) in plaats van per symbool...")
    print()

    # Progress callback - now tracks dates instead of symbols
    def progress(date_str: str, idx: int, total: int) -> None:
        pct = int(idx / total * 100)
        print(f"\r  [{idx}/{total}] {pct}% - Datum {date_str}...".ljust(60), end="", flush=True)

    # Calculate metrics using optimized method
    results = service.get_all_symbols_overview_optimized(
        lookback_days=252,
        progress_callback=progress,
        max_workers=8,
    )

    print("\r" + " " * 60 + "\r", end="")  # Clear progress line
    print()

    if not results:
        print("Geen resultaten beschikbaar.")
        print()
        return

    # Display results
    _print_header(f"OVERZICHT ({len(results)} symbolen, gesorteerd op ATM Volume)")

    print(f"{'#':<5} {'Symbol':<8} {'Gem. ATM Volume':>18} {'Gem. ATM OI':>18} {'Dagen':>8}")
    print("\u2500" * 60)

    for idx, r in enumerate(results, 1):
        vol = _format_number(r["avg_atm_volume"])
        oi = _format_number(r["avg_atm_oi"])
        days = r["days_analyzed"]

        print(f"{idx:<5} {r['symbol']:<8} {vol:>18} {oi:>18} {days:>8}")

    # Summary
    print("\u2500" * 60)

    # Calculate totals for symbols with data
    symbols_with_data = [r for r in results if r["avg_atm_volume"] is not None]
    symbols_without_data = len(results) - len(symbols_with_data)

    if symbols_with_data:
        total_vol = sum(r["avg_atm_volume"] for r in symbols_with_data)
        total_oi = sum(r["avg_atm_oi"] or 0 for r in symbols_with_data)
        avg_vol = total_vol // len(symbols_with_data)
        avg_oi = total_oi // len(symbols_with_data)

        print(f"Symbolen met data: {len(symbols_with_data)}")
        print(f"Symbolen zonder data: {symbols_without_data}")
        print(f"Gemiddelde ATM Volume: {_format_number(avg_vol)}")
        print(f"Gemiddelde ATM OI: {_format_number(avg_oi)}")

    print()


def validate_all_data(manager: Optional[SymbolManager] = None) -> None:
    """Validate data for all symbols."""
    manager = manager or get_symbol_manager()

    _print_header("\u2705 DATA VALIDATIE")

    validations = manager.symbol_service.validate_all_symbols()

    # Group by status
    complete = []
    incomplete = []
    missing = []

    for symbol, validation in sorted(validations.items()):
        if validation.status == "complete":
            complete.append((symbol, validation))
        elif validation.status == "incomplete":
            incomplete.append((symbol, validation))
        else:
            missing.append((symbol, validation))

    # Summary
    print(f"Complete: {len(complete)} | Incomplete: {len(incomplete)} | Missing: {len(missing)}")
    print()

    # Show incomplete/missing details
    if incomplete:
        print("Incomplete data:")
        for symbol, v in incomplete:
            missing_str = ", ".join(v.missing_files)
            print(f"  {symbol}: ontbreekt {missing_str}")
        print()

    if missing:
        print("Ontbrekende data:")
        for symbol, v in missing:
            print(f"  {symbol}: geen data gevonden")
        print()


def run_symbol_menu(manager: Optional[SymbolManager] = None) -> None:
    """Run the symbol management menu."""
    manager = manager or get_symbol_manager()

    menu = Menu("\U0001f4e6 SYMBOLEN & BASKET")

    menu.add("Basket overzicht", partial(show_basket_overview, manager))
    menu.add("ORATS symbool overzicht (ATM Vol/OI)", show_orats_symbol_overview)
    menu.add("Symbool toevoegen", partial(add_symbols_interactive, manager))
    menu.add("Symbool verwijderen", partial(remove_symbols_interactive, manager))
    menu.add("Basket analyse", partial(show_sector_analysis, manager))
    menu.add("Liquiditeit check", partial(show_liquidity_warnings, manager))
    menu.add("Data synchroniseren", partial(sync_metadata_interactive, manager))
    menu.add("Data valideren", partial(validate_all_data, manager))
    menu.add("Verweesde data opruimen", partial(show_orphaned_data, manager))

    menu.run()


def build_symbol_menu(manager: Optional[SymbolManager] = None) -> Menu:
    """Build and return the symbol management menu."""
    manager = manager or get_symbol_manager()

    menu = Menu("\U0001f4e6 SYMBOLEN & BASKET")

    menu.add("Basket overzicht", partial(show_basket_overview, manager))
    menu.add("ORATS symbool overzicht (ATM Vol/OI)", show_orats_symbol_overview)
    menu.add("Symbool toevoegen", partial(add_symbols_interactive, manager))
    menu.add("Symbool verwijderen", partial(remove_symbols_interactive, manager))
    menu.add("Basket analyse", partial(show_sector_analysis, manager))
    menu.add("Liquiditeit check", partial(show_liquidity_warnings, manager))
    menu.add("Data synchroniseren", partial(sync_metadata_interactive, manager))
    menu.add("Data valideren", partial(validate_all_data, manager))
    menu.add("Verweesde data opruimen", partial(show_orphaned_data, manager))

    return menu
