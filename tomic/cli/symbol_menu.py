"""Symbol management menu for the control panel.

Provides UI for managing symbols in the basket including:
- Basket overview with sector and liquidity info
- Adding/removing symbols
- Data synchronization
- Sector analysis
"""

from __future__ import annotations

from functools import partial
from typing import Any, Dict, List, Optional

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.services.liquidity_service import LiquidityService, get_liquidity_service
from tomic.services.qualification_service import (
    QualificationService,
    get_qualification_service,
    STRATEGIES,
    VALID_STATUSES,
)
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
    """Interactive metadata sync with ultra-fast cached processing."""
    manager = manager or get_symbol_manager()

    _print_header("\U0001f504 DATA SYNCHRONISEREN")

    current = manager.symbol_service.get_configured_symbols()
    print(f"Symbolen om te synchroniseren: {len(current)}")
    print()

    # Check cache status
    has_sector_mapping = bool(manager.symbol_service.load_sector_mapping())
    has_liquidity_cache = manager.symbol_service.is_liquidity_cache_valid()

    print("Cache status:")
    print(f"  - Sector mapping: {'✓ beschikbaar' if has_sector_mapping else '✗ leeg (run optie 2 eerst)'}")
    print(f"  - Liquidity cache: {'✓ geldig' if has_liquidity_cache else '✗ verouderd/leeg (run optie 2 eerst)'}")
    print()

    if not has_sector_mapping and not has_liquidity_cache:
        print("Tip: Run eerst 'ORATS symbool overzicht (Gem. Vol/OI)' (optie 2) om de liquidity cache te vullen.")
        print()

    refresh_sector = prompt_yes_no("Sector info uit cache gebruiken?", has_sector_mapping)
    refresh_liquidity = prompt_yes_no("Liquiditeit uit cache gebruiken?", has_liquidity_cache)
    force_refresh = prompt_yes_no("Forceer update van alle symbolen?", False)

    if not prompt_yes_no(f"Doorgaan met sync van {len(current)} symbolen?", True):
        print("Geannuleerd.")
        return

    print("\nSynchroniseren (ultra-snel)...")
    print("  - Sector en liquiditeit uit cache (O(1) lookup)")
    print("  - Incrementele sync (skip recente updates)")
    print()

    def progress(symbol: str, status: str) -> None:
        if symbol:
            print(f"  {symbol}: {status}")
        else:
            print(f"  {status}")

    results = manager.sync_metadata(
        refresh_sector=refresh_sector,
        refresh_liquidity=refresh_liquidity,
        progress_callback=progress,
        force_refresh=force_refresh,
    )

    print(f"\n✓ {len(results)} symbolen gesynchroniseerd.")
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


def show_orats_symbol_overview(
    liquidity_service: Optional[LiquidityService] = None,
    manager: Optional[SymbolManager] = None,
) -> None:
    """Show overview of all symbols from most recent ORATS file.

    Displays top 100 symbols sorted by average total volume with average OI.
    Results are cached for fast future lookups.
    """
    service = liquidity_service or get_liquidity_service()
    manager = manager or get_symbol_manager()

    _print_header("\U0001f4ca ORATS SYMBOOL OVERZICHT")

    # Check if we have a valid cache
    if manager.symbol_service.is_liquidity_cache_valid():
        cache = manager.symbol_service.load_liquidity_cache()
        cache_date = cache.get("timestamp", "")[:10] if cache else ""
        cache_days = cache.get("lookback_days", 0) if cache else 0
        cache_count = len(cache.get("results", [])) if cache else 0

        print(f"Cache beschikbaar: {cache_date} ({cache_count} symbolen, {cache_days} dagen)")
        print()

        use_cache = prompt_yes_no("Gecachte resultaten gebruiken?", True)
        if use_cache:
            results = cache.get("results", [])
            if results:
                _display_liquidity_results(results)
                return

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

    # Ask for lookback days (default 30)
    lookback_days = 30
    print(f"Standaard lookback: {lookback_days} dagen (~6 weken)")
    if prompt_yes_no("Andere lookback periode gebruiken?", False):
        try:
            lookback_days = int(input("Aantal dagen (bijv. 30, 60, 90): ").strip())
        except ValueError:
            lookback_days = 30
            print(f"Ongeldige invoer, gebruik {lookback_days} dagen.")

    print()
    print(f"Berekenen van liquiditeitsmetrics ({lookback_days} dagen)...")
    print("Verwerking per datum (parallel) in plaats van per symbool...")
    print()

    # Progress callback - now tracks dates instead of symbols
    def progress(date_str: str, idx: int, total: int) -> None:
        pct = int(idx / total * 100)
        print(f"\r  [{idx}/{total}] {pct}% - Datum {date_str}...".ljust(60), end="", flush=True)

    # Calculate metrics using optimized method
    results = service.get_all_symbols_overview_optimized(
        lookback_days=lookback_days,
        progress_callback=progress,
        max_workers=8,
    )

    print("\r" + " " * 60 + "\r", end="")  # Clear progress line
    print()

    # Save to cache automatically
    if results:
        manager.symbol_service.save_liquidity_cache(results, lookback_days)
        print(f"✓ Resultaten gecached naar liquidity_cache.json")
        print()

    _display_liquidity_results(results)


def _display_liquidity_results(results: List[Dict[str, Any]], top_n: int = 100) -> None:
    """Display liquidity results in a formatted table.

    Args:
        results: List of liquidity results sorted by volume descending.
        top_n: Number of top symbols to display (default 100).
    """
    if not results:
        print("Geen resultaten beschikbaar.")
        print()
        return

    # Limit to top N results
    display_results = results[:top_n]
    total_count = len(results)

    # Display results
    _print_header(f"TOP {len(display_results)} VAN {total_count} SYMBOLEN (gesorteerd op Gem. Volume)")

    print(f"{'#':<5} {'Symbol':<8} {'Gem. Volume':>18} {'Gem. OI':>18} {'Dagen':>8}")
    print("\u2500" * 60)

    for idx, r in enumerate(display_results, 1):
        vol = _format_number(r.get("avg_atm_volume"))
        oi = _format_number(r.get("avg_atm_oi"))
        days = r.get("days_analyzed", 0)

        print(f"{idx:<5} {r['symbol']:<8} {vol:>18} {oi:>18} {days:>8}")

    # Summary
    print("\u2500" * 60)

    # Calculate totals for ALL symbols with data (not just displayed)
    symbols_with_data = [r for r in results if r.get("avg_atm_volume") is not None]
    symbols_without_data = total_count - len(symbols_with_data)

    if symbols_with_data:
        total_vol = sum(r["avg_atm_volume"] for r in symbols_with_data)
        total_oi = sum(r.get("avg_atm_oi") or 0 for r in symbols_with_data)
        avg_vol = total_vol // len(symbols_with_data)
        avg_oi = total_oi // len(symbols_with_data)

        print(f"Totaal symbolen: {total_count} ({len(symbols_with_data)} met data)")
        print(f"Getoond: top {len(display_results)} op Gem. Volume")
        print(f"Gemiddeld Volume (alle): {_format_number(avg_vol)}")
        print(f"Gemiddeld OI (alle): {_format_number(avg_oi)}")

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


def _format_qual_status(status: str) -> str:
    """Format qualification status with icon."""
    if status == "qualified":
        return "\u2705"  # ✅
    if status == "disqualified":
        return "\u274c"  # ❌
    return "\u26a0\ufe0f"  # ⚠️ (watchlist)


def show_qualification_matrix(
    manager: Optional[SymbolManager] = None,
    qual_service: Optional[QualificationService] = None,
) -> None:
    """Show qualification matrix for all configured symbols."""
    manager = manager or get_symbol_manager()
    qual_service = qual_service or get_qualification_service()

    symbols = manager.symbol_service.get_configured_symbols()
    matrix = qual_service.get_matrix(symbols)

    _print_header("\U0001f3af KWALIFICATIE MATRIX")

    # Count qualified per strategy
    cal_qual = sum(1 for m in matrix if m["calendar_status"] == "qualified")
    ic_qual = sum(1 for m in matrix if m["iron_condor_status"] == "qualified")

    print(f"{'Symbol':<8} {'Calendar':^10} {'Iron Condor':^12} {'Notes':<40}")
    print("\u2500" * 75)

    for m in sorted(matrix, key=lambda x: x["symbol"]):
        cal_icon = _format_qual_status(m["calendar_status"])
        ic_icon = _format_qual_status(m["iron_condor_status"])

        # Combine reasons for notes column
        notes = []
        if m["calendar_reason"] and m["calendar_status"] != "qualified":
            notes.append(f"CAL: {m['calendar_reason']}")
        if m["iron_condor_reason"] and m["iron_condor_status"] != "qualified":
            notes.append(f"IC: {m['iron_condor_reason']}")
        notes_str = " | ".join(notes)[:40]

        print(f"{m['symbol']:<8} {cal_icon:^10} {ic_icon:^12} {notes_str:<40}")

    print("\u2500" * 75)
    print(f"Gekwalificeerd: Calendar {cal_qual}/{len(matrix)} | Iron Condor {ic_qual}/{len(matrix)}")
    print()


def update_qualification_interactive(
    manager: Optional[SymbolManager] = None,
    qual_service: Optional[QualificationService] = None,
) -> None:
    """Interactive qualification update."""
    manager = manager or get_symbol_manager()
    qual_service = qual_service or get_qualification_service()

    _print_header("\U0001f4dd KWALIFICATIE UPDATEN")

    # Show current symbols
    symbols = manager.symbol_service.get_configured_symbols()
    print(f"Beschikbare symbolen: {', '.join(sorted(symbols)[:15])}")
    if len(symbols) > 15:
        print(f"  ... en {len(symbols) - 15} meer")
    print()

    # Get symbol
    symbol_input = prompt("Symbool: ", "").strip().upper()
    if not symbol_input:
        print("Geen symbool opgegeven.")
        return

    if symbol_input not in symbols:
        print(f"Symbool {symbol_input} niet in basket.")
        if not prompt_yes_no("Toch doorgaan?", False):
            return

    # Show current status
    current = qual_service.get(symbol_input)
    print(f"\nHuidige status voor {symbol_input}:")
    print(f"  Calendar:    {_format_qual_status(current.calendar.status)} {current.calendar.status}")
    if current.calendar.reason:
        print(f"               {current.calendar.reason}")
    print(f"  Iron Condor: {_format_qual_status(current.iron_condor.status)} {current.iron_condor.status}")
    if current.iron_condor.reason:
        print(f"               {current.iron_condor.reason}")
    print()

    # Select strategy
    print("Strategie:")
    print("  1. Calendar")
    print("  2. Iron Condor")
    print("  3. Beide")
    strategy_choice = prompt("Keuze [1-3]: ", "3")

    if strategy_choice == "1":
        strategies_to_update = ["calendar"]
    elif strategy_choice == "2":
        strategies_to_update = ["iron_condor"]
    else:
        strategies_to_update = ["calendar", "iron_condor"]

    # Select status
    print("\nNieuwe status:")
    print("  1. Qualified (geschikt)")
    print("  2. Disqualified (ongeschikt)")
    print("  3. Watchlist (afwachten)")
    status_choice = prompt("Keuze [1-3]: ", "1")

    if status_choice == "1":
        new_status = "qualified"
    elif status_choice == "2":
        new_status = "disqualified"
    else:
        new_status = "watchlist"

    # Get reason
    reason = ""
    if new_status != "qualified":
        reason = prompt("Reden (optioneel): ", "")

    # Confirm and update
    print(f"\nUpdate {symbol_input}:")
    for strategy in strategies_to_update:
        print(f"  {strategy} -> {new_status}" + (f" ({reason})" if reason else ""))

    if not prompt_yes_no("Doorgaan?", True):
        print("Geannuleerd.")
        return

    # Apply updates
    for strategy in strategies_to_update:
        qual_service.update(symbol_input, strategy, new_status, reason)

    print(f"\n\u2713 {symbol_input} bijgewerkt.")
    print()


def run_symbol_menu(manager: Optional[SymbolManager] = None) -> None:
    """Run the symbol management menu."""
    manager = manager or get_symbol_manager()

    menu = Menu("\U0001f4e6 SYMBOLEN & BASKET")

    menu.add("Basket overzicht", partial(show_basket_overview, manager))
    menu.add("ORATS symbool overzicht (Gem. Vol/OI)", show_orats_symbol_overview)
    menu.add("Kwalificatie matrix", partial(show_qualification_matrix, manager))
    menu.add("Kwalificatie updaten", partial(update_qualification_interactive, manager))
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
    menu.add("ORATS symbool overzicht (Gem. Vol/OI)", show_orats_symbol_overview)
    menu.add("Kwalificatie matrix", partial(show_qualification_matrix, manager))
    menu.add("Kwalificatie updaten", partial(update_qualification_interactive, manager))
    menu.add("Symbool toevoegen", partial(add_symbols_interactive, manager))
    menu.add("Symbool verwijderen", partial(remove_symbols_interactive, manager))
    menu.add("Basket analyse", partial(show_sector_analysis, manager))
    menu.add("Liquiditeit check", partial(show_liquidity_warnings, manager))
    menu.add("Data synchroniseren", partial(sync_metadata_interactive, manager))
    menu.add("Data valideren", partial(validate_all_data, manager))
    menu.add("Verweesde data opruimen", partial(show_orphaned_data, manager))

    return menu
