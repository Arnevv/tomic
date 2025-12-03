"""CLI interface for backtesting functionality.

Provides menu handlers for running and configuring backtests
within the TOMIC control panel.

Supports multiple strategy types:
- Iron Condor: Credit strategy, enter on HIGH IV
- Calendar Spread: Debit strategy, enter on LOW IV
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.backtest.config import (
    BacktestConfig,
    load_backtest_config,
    save_backtest_config,
)
from tomic.backtest.engine import BacktestEngine, run_backtest
from tomic.backtest.reports import BacktestReport, print_backtest_report
from tomic.backtest.results import BacktestResult
from tomic.logutils import logger

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Store last results for viewing (per strategy type)
_LAST_RESULT = None
_LAST_RESULTS: dict[str, BacktestResult] = {}


# Strategy type constants
STRATEGY_IRON_CONDOR = "iron_condor"
STRATEGY_CALENDAR = "calendar"


def _load_calendar_config() -> BacktestConfig:
    """Load calendar spread specific configuration."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    calendar_config_path = base_dir / "config" / "backtest_calendar.yaml"

    if calendar_config_path.exists():
        return load_backtest_config(calendar_config_path)

    # Fallback: create calendar config from defaults
    config = BacktestConfig()
    config.strategy_type = STRATEGY_CALENDAR
    config.entry_rules.iv_percentile_min = 0.0
    config.entry_rules.iv_percentile_max = 40.0
    config.exit_rules.profit_target_pct = 10.0
    config.exit_rules.stop_loss_pct = 10.0
    config.exit_rules.max_days_in_trade = 10
    return config


def _select_strategy() -> Optional[str]:
    """Prompt user to select a strategy type.

    Returns:
        Strategy type string, or None if cancelled.
    """
    print("\n" + "=" * 50)
    print("KIES STRATEGIE TYPE")
    print("=" * 50)
    print("1. Iron Condor  (credit, hoge IV entry)")
    print("2. Calendar     (debit, lage IV entry)")
    print("3. Beide        (vergelijk IC vs Calendar)")
    print("4. Terug")

    choice = prompt("Maak je keuze [1-4]: ")

    if choice == "1":
        return STRATEGY_IRON_CONDOR
    elif choice == "2":
        return STRATEGY_CALENDAR
    elif choice == "3":
        return "both"
    else:
        return None


def run_backtest_menu() -> None:
    """Run the backtesting submenu."""
    menu = Menu("📈 BACKTESTING")
    menu.add("Backtest uitvoeren", _run_backtest_with_strategy_choice)
    menu.add("Parameters configureren", _configure_with_strategy_choice)
    menu.add("Laatste resultaten bekijken", view_last_results)
    menu.add("Resultaten exporteren (JSON)", export_results)
    menu.run()


def _run_backtest_with_strategy_choice() -> None:
    """Run backtest after selecting strategy type."""
    strategy = _select_strategy()

    if strategy is None:
        return
    elif strategy == STRATEGY_IRON_CONDOR:
        run_iron_condor_backtest()
    elif strategy == STRATEGY_CALENDAR:
        run_calendar_backtest()
    elif strategy == "both":
        run_both_backtests()


def run_iron_condor_backtest() -> None:
    """Run a full Iron Condor backtest."""
    global _LAST_RESULT, _LAST_RESULTS

    print("\n" + "=" * 60)
    print("IRON CONDOR BACKTEST")
    print("=" * 60)

    # Load configuration
    try:
        config = load_backtest_config()
        config.strategy_type = STRATEGY_IRON_CONDOR  # Ensure correct type
    except Exception as e:
        print(f"Fout bij laden configuratie: {e}")
        print("Gebruik standaard configuratie...")
        config = BacktestConfig()

    # Show configuration summary
    print(f"\nStrategie: Iron Condor (credit, hoge IV entry)")
    print(f"Symbolen: {', '.join(config.symbols)}")
    print(f"Periode: {config.start_date} tot {config.end_date}")
    print(f"Entry: IV percentile >= {config.entry_rules.iv_percentile_min}%")
    print(f"Exit: Profit {config.exit_rules.profit_target_pct}%, "
          f"Stop {config.exit_rules.stop_loss_pct}%, "
          f"Max DIT {config.exit_rules.max_days_in_trade}d")
    print(f"Max risico per trade: ${config.position_sizing.max_risk_per_trade}")
    print(f"Sample split: {config.sample_split.in_sample_ratio*100:.0f}% in-sample")

    print("\n" + "-" * 60)

    if not prompt_yes_no("Backtest starten met deze configuratie?"):
        print("Backtest geannuleerd.")
        return

    result = _execute_backtest(config, "Iron Condor")
    if result:
        _LAST_RESULT = result
        _LAST_RESULTS[STRATEGY_IRON_CONDOR] = result
        print("\n")
        print_backtest_report(result)

        if prompt_yes_no("\nResultaten exporteren naar JSON?"):
            export_results()


def run_calendar_backtest() -> None:
    """Run a full Calendar Spread backtest."""
    global _LAST_RESULT, _LAST_RESULTS

    print("\n" + "=" * 60)
    print("CALENDAR SPREAD BACKTEST")
    print("=" * 60)

    # Load calendar-specific configuration
    try:
        config = _load_calendar_config()
    except Exception as e:
        print(f"Fout bij laden configuratie: {e}")
        print("Gebruik standaard calendar configuratie...")
        config = _load_calendar_config()

    # Show configuration summary (calendar-specific)
    print(f"\nStrategie: Calendar Spread (debit, lage IV entry)")
    print(f"Symbolen: {', '.join(config.symbols)}")
    print(f"Periode: {config.start_date} tot {config.end_date}")

    iv_max = config.entry_rules.iv_percentile_max or 40.0
    print(f"Entry: IV percentile <= {iv_max}%")

    if config.entry_rules.term_structure_min is not None:
        print(f"       Term structure >= {config.entry_rules.term_structure_min} (front >= back)")

    print(f"Exit: Profit {config.exit_rules.profit_target_pct}%, "
          f"Stop {config.exit_rules.stop_loss_pct}%, "
          f"Max DIT {config.exit_rules.max_days_in_trade}d")
    print(f"Near leg DTE: {config.calendar_near_dte}d, Far leg DTE: {config.calendar_far_dte}d")
    print(f"Max risico per trade: ${config.position_sizing.max_risk_per_trade}")
    print(f"Sample split: {config.sample_split.in_sample_ratio*100:.0f}% in-sample")

    print("\n" + "-" * 60)

    if not prompt_yes_no("Backtest starten met deze configuratie?"):
        print("Backtest geannuleerd.")
        return

    result = _execute_backtest(config, "Calendar Spread")
    if result:
        _LAST_RESULT = result
        _LAST_RESULTS[STRATEGY_CALENDAR] = result
        print("\n")
        print_backtest_report(result)

        if prompt_yes_no("\nResultaten exporteren naar JSON?"):
            export_results()


def run_both_backtests() -> None:
    """Run both Iron Condor and Calendar backtests and compare."""
    global _LAST_RESULT, _LAST_RESULTS

    print("\n" + "=" * 60)
    print("VERGELIJKING: IRON CONDOR vs CALENDAR")
    print("=" * 60)

    # Load both configurations
    try:
        ic_config = load_backtest_config()
        ic_config.strategy_type = STRATEGY_IRON_CONDOR
    except Exception:
        ic_config = BacktestConfig()

    try:
        cal_config = _load_calendar_config()
    except Exception:
        cal_config = _load_calendar_config()

    print("\nDe volgende backtests worden uitgevoerd:")
    print(f"  1. Iron Condor: {', '.join(ic_config.symbols[:3])}... ({ic_config.start_date} - {ic_config.end_date})")
    print(f"  2. Calendar:    {', '.join(cal_config.symbols[:3])}... ({cal_config.start_date} - {cal_config.end_date})")

    if not prompt_yes_no("\nBeide backtests uitvoeren?"):
        print("Geannuleerd.")
        return

    results: dict[str, BacktestResult] = {}

    # Run Iron Condor
    print("\n" + "-" * 60)
    print("STAP 1/2: Iron Condor Backtest")
    print("-" * 60)
    ic_result = _execute_backtest(ic_config, "Iron Condor")
    if ic_result:
        results[STRATEGY_IRON_CONDOR] = ic_result
        _LAST_RESULTS[STRATEGY_IRON_CONDOR] = ic_result

    # Run Calendar
    print("\n" + "-" * 60)
    print("STAP 2/2: Calendar Spread Backtest")
    print("-" * 60)
    cal_result = _execute_backtest(cal_config, "Calendar Spread")
    if cal_result:
        results[STRATEGY_CALENDAR] = cal_result
        _LAST_RESULTS[STRATEGY_CALENDAR] = cal_result

    # Print comparison
    if len(results) == 2:
        _print_comparison_report(results)

        if prompt_yes_no("\nBeide resultaten exporteren naar JSON?"):
            _export_comparison_results(results)
    else:
        print("\nNiet alle backtests zijn succesvol afgerond.")


def _execute_backtest(config: BacktestConfig, name: str) -> Optional[BacktestResult]:
    """Execute a backtest with progress feedback.

    Args:
        config: Backtest configuration
        name: Display name for the backtest

    Returns:
        BacktestResult if successful, None otherwise
    """
    print(f"\n{name} backtest wordt uitgevoerd...\n")

    if RICH_AVAILABLE:
        console = Console()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Initialiseren...", total=100)

            def update_progress(message: str, percent: float) -> None:
                progress.update(task, description=message, completed=percent)

            try:
                return run_backtest(config=config, progress_callback=update_progress)
            except Exception as e:
                logger.error(f"Backtest fout: {e}")
                print(f"\nFout tijdens backtest: {e}")
                return None
    else:
        def simple_progress(message: str, percent: float) -> None:
            if percent % 20 == 0:
                print(f"[{percent:.0f}%] {message}")

        try:
            return run_backtest(config=config, progress_callback=simple_progress)
        except Exception as e:
            logger.error(f"Backtest fout: {e}")
            print(f"\nFout tijdens backtest: {e}")
            return None


def _print_comparison_report(results: dict[str, BacktestResult]) -> None:
    """Print a comparison report of multiple strategy results."""
    print("\n" + "=" * 70)
    print("VERGELIJKING RESULTATEN")
    print("=" * 70)

    ic = results.get(STRATEGY_IRON_CONDOR)
    cal = results.get(STRATEGY_CALENDAR)

    if not ic or not cal:
        print("Onvoldoende data voor vergelijking.")
        return

    ic_m = ic.combined_metrics
    cal_m = cal.combined_metrics

    if not ic_m or not cal_m:
        print("Onvoldoende metrics voor vergelijking.")
        return

    # Header
    print(f"\n{'Metric':<25} {'Iron Condor':>18} {'Calendar':>18} {'Winnaar':>12}")
    print("-" * 73)

    # Compare metrics
    comparisons = [
        ("Total Trades", ic_m.total_trades, cal_m.total_trades, "higher"),
        ("Win Rate", f"{ic_m.win_rate:.1%}", f"{cal_m.win_rate:.1%}", "higher"),
        ("Total P&L", f"${ic_m.total_pnl:.2f}", f"${cal_m.total_pnl:.2f}", "higher"),
        ("Sharpe Ratio", f"{ic_m.sharpe_ratio:.2f}", f"{cal_m.sharpe_ratio:.2f}", "higher"),
        ("Max Drawdown", f"{ic_m.max_drawdown_pct:.1f}%", f"{cal_m.max_drawdown_pct:.1f}%", "lower"),
        ("Profit Factor", f"{ic_m.profit_factor:.2f}", f"{cal_m.profit_factor:.2f}", "higher"),
        ("Expectancy", f"${ic_m.expectancy:.2f}", f"${cal_m.expectancy:.2f}", "higher"),
    ]

    for metric, ic_val, cal_val, prefer in comparisons:
        # Determine winner
        try:
            ic_num = float(str(ic_val).replace("$", "").replace("%", ""))
            cal_num = float(str(cal_val).replace("$", "").replace("%", ""))

            if prefer == "higher":
                winner = "IC" if ic_num > cal_num else ("CAL" if cal_num > ic_num else "Gelijk")
            else:
                winner = "IC" if ic_num < cal_num else ("CAL" if cal_num < ic_num else "Gelijk")
        except (ValueError, TypeError):
            winner = "-"

        print(f"{metric:<25} {str(ic_val):>18} {str(cal_val):>18} {winner:>12}")

    print("-" * 73)

    # Overall recommendation
    print("\n📊 SAMENVATTING:")
    if ic_m.sharpe_ratio > cal_m.sharpe_ratio and ic_m.total_pnl > cal_m.total_pnl:
        print("   Iron Condor presteert beter op zowel Sharpe als P&L")
    elif cal_m.sharpe_ratio > ic_m.sharpe_ratio and cal_m.total_pnl > ic_m.total_pnl:
        print("   Calendar Spread presteert beter op zowel Sharpe als P&L")
    else:
        print("   Gemengde resultaten - overweeg marktcondities en persoonlijke voorkeur")


def _export_comparison_results(results: dict[str, BacktestResult]) -> None:
    """Export comparison results to separate JSON files."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_dir = Path(__file__).resolve().parent.parent.parent
    export_dir = base_dir / "exports"
    export_dir.mkdir(exist_ok=True)

    for strategy_type, result in results.items():
        filename = f"backtest_{strategy_type}_{timestamp}.json"
        export_path = export_dir / filename

        try:
            report = BacktestReport(result)
            report.export_json(export_path)
            print(f"  Geexporteerd: {export_path}")
        except Exception as e:
            print(f"  Fout bij exporteren {strategy_type}: {e}")


def _configure_with_strategy_choice() -> None:
    """Configure parameters after selecting strategy type."""
    print("\n" + "=" * 50)
    print("CONFIGURATIE - KIES STRATEGIE")
    print("=" * 50)
    print("1. Iron Condor parameters")
    print("2. Calendar Spread parameters")
    print("3. Terug")

    choice = prompt("Maak je keuze [1-3]: ")

    if choice == "1":
        configure_iron_condor_params()
    elif choice == "2":
        configure_calendar_params()


def configure_backtest_params() -> None:
    """Interactive configuration of backtest parameters (Iron Condor)."""
    configure_iron_condor_params()


def configure_iron_condor_params() -> None:
    """Interactive configuration of Iron Condor backtest parameters."""
    print("\n" + "=" * 60)
    print("IRON CONDOR CONFIGURATIE")
    print("=" * 60)

    # Load current config
    try:
        config = load_backtest_config()
    except Exception:
        config = BacktestConfig()

    menu = Menu("Iron Condor Opties", exit_text="Terug (wijzigingen opslaan)")

    # Entry rules
    menu.add(
        f"Startdatum [{config.start_date}]",
        partial(_edit_start_date, config),
    )
    menu.add(
        f"Einddatum [{config.end_date}]",
        partial(_edit_end_date, config),
    )

    menu.add(
        f"IV Percentile minimum [{config.entry_rules.iv_percentile_min}]",
        partial(_edit_iv_percentile_min, config),
    )

    # Exit rules
    menu.add(
        f"Profit target [{config.exit_rules.profit_target_pct}%]",
        partial(_edit_profit_target, config),
    )
    menu.add(
        f"Stop loss [{config.exit_rules.stop_loss_pct}%]",
        partial(_edit_stop_loss, config),
    )
    menu.add(
        f"Max DIT [{config.exit_rules.max_days_in_trade}d]",
        partial(_edit_max_dit, config),
    )

    # Position sizing
    menu.add(
        f"Max risico per trade [${config.position_sizing.max_risk_per_trade}]",
        partial(_edit_max_risk, config),
    )

    # Symbols
    menu.add(
        f"Symbolen [{', '.join(config.symbols)}]",
        partial(_edit_symbols, config),
    )

    menu.run()

    # Save config
    try:
        save_backtest_config(config)
        print("\nConfiguratie opgeslagen naar config/backtest.yaml")
    except Exception as e:
        print(f"\nFout bij opslaan: {e}")


def configure_calendar_params() -> None:
    """Interactive configuration of Calendar Spread backtest parameters."""
    print("\n" + "=" * 60)
    print("CALENDAR SPREAD CONFIGURATIE")
    print("=" * 60)

    # Load calendar config
    base_dir = Path(__file__).resolve().parent.parent.parent
    calendar_config_path = base_dir / "config" / "backtest_calendar.yaml"

    try:
        config = _load_calendar_config()
    except Exception:
        config = BacktestConfig()
        config.strategy_type = STRATEGY_CALENDAR

    menu = Menu("Calendar Spread Opties", exit_text="Terug (wijzigingen opslaan)")

    # Date range
    menu.add(
        f"Startdatum [{config.start_date}]",
        partial(_edit_start_date, config),
    )
    menu.add(
        f"Einddatum [{config.end_date}]",
        partial(_edit_end_date, config),
    )

    # Calendar-specific entry rules
    iv_max = config.entry_rules.iv_percentile_max or 40.0
    menu.add(
        f"IV Percentile maximum [{iv_max}]",
        partial(_edit_iv_percentile_max, config),
    )

    term_min = config.entry_rules.term_structure_min
    term_min_str = str(term_min) if term_min is not None else "niet ingesteld"
    menu.add(
        f"Term structure minimum [{term_min_str}]",
        partial(_edit_term_structure_min, config),
    )

    # Exit rules
    menu.add(
        f"Profit target [{config.exit_rules.profit_target_pct}%]",
        partial(_edit_profit_target, config),
    )
    menu.add(
        f"Stop loss [{config.exit_rules.stop_loss_pct}%]",
        partial(_edit_stop_loss, config),
    )
    menu.add(
        f"Max DIT [{config.exit_rules.max_days_in_trade}d]",
        partial(_edit_max_dit, config),
    )

    # Calendar-specific parameters
    menu.add(
        f"Near leg DTE [{config.calendar_near_dte}d]",
        partial(_edit_calendar_near_dte, config),
    )
    menu.add(
        f"Far leg DTE [{config.calendar_far_dte}d]",
        partial(_edit_calendar_far_dte, config),
    )

    # Position sizing
    menu.add(
        f"Max risico per trade [${config.position_sizing.max_risk_per_trade}]",
        partial(_edit_max_risk, config),
    )

    # Symbols
    menu.add(
        f"Symbolen [{', '.join(config.symbols)}]",
        partial(_edit_symbols, config),
    )

    menu.run()

    # Save calendar config
    try:
        save_backtest_config(config, calendar_config_path)
        print("\nConfiguratie opgeslagen naar config/backtest_calendar.yaml")
    except Exception as e:
        print(f"\nFout bij opslaan: {e}")


def _edit_iv_percentile_min(config: BacktestConfig) -> None:
    """Edit IV percentile minimum (for Iron Condor - high IV entry)."""
    current = config.entry_rules.iv_percentile_min
    new_value = prompt(f"Nieuwe IV percentile minimum [{current}]: ")
    if new_value:
        try:
            config.entry_rules.iv_percentile_min = float(new_value)
            print(f"IV percentile minimum: {config.entry_rules.iv_percentile_min}")
        except ValueError:
            print("Ongeldige waarde")


def _edit_iv_percentile_max(config: BacktestConfig) -> None:
    """Edit IV percentile maximum (for Calendar - low IV entry)."""
    current = config.entry_rules.iv_percentile_max or 40.0
    new_value = prompt(f"Nieuwe IV percentile maximum [{current}]: ")
    if new_value:
        try:
            config.entry_rules.iv_percentile_max = float(new_value)
            print(f"IV percentile maximum: {config.entry_rules.iv_percentile_max}")
        except ValueError:
            print("Ongeldige waarde")


def _edit_term_structure_min(config: BacktestConfig) -> None:
    """Edit term structure minimum (for Calendar - front >= back IV)."""
    current = config.entry_rules.term_structure_min
    current_str = str(current) if current is not None else "niet ingesteld"
    new_value = prompt(f"Nieuwe term structure minimum [{current_str}]: ")
    if new_value:
        try:
            config.entry_rules.term_structure_min = float(new_value)
            print(f"Term structure minimum: {config.entry_rules.term_structure_min}")
        except ValueError:
            print("Ongeldige waarde")


def _edit_calendar_near_dte(config: BacktestConfig) -> None:
    """Edit calendar near leg DTE."""
    current = config.calendar_near_dte
    new_value = prompt(f"Nieuwe near leg DTE [{current}]: ")
    if new_value:
        try:
            new_dte = int(new_value)
            if new_dte >= config.calendar_far_dte:
                print("Near leg DTE moet kleiner zijn dan far leg DTE")
                return
            config.calendar_near_dte = new_dte
            print(f"Near leg DTE: {config.calendar_near_dte} dagen")
        except ValueError:
            print("Ongeldige waarde")


def _edit_calendar_far_dte(config: BacktestConfig) -> None:
    """Edit calendar far leg DTE."""
    current = config.calendar_far_dte
    new_value = prompt(f"Nieuwe far leg DTE [{current}]: ")
    if new_value:
        try:
            new_dte = int(new_value)
            if new_dte <= config.calendar_near_dte:
                print("Far leg DTE moet groter zijn dan near leg DTE")
                return
            config.calendar_far_dte = new_dte
            print(f"Far leg DTE: {config.calendar_far_dte} dagen")
        except ValueError:
            print("Ongeldige waarde")


def _edit_start_date(config: BacktestConfig) -> None:
    """Edit start date for backtest period."""
    from datetime import date

    current = config.start_date
    new_value = prompt(f"Nieuwe startdatum (YYYY-MM-DD) [{current}]: ")
    if new_value:
        try:
            new_date = date.fromisoformat(new_value)
        except ValueError:
            print("Ongeldige datum, gebruik formaat YYYY-MM-DD")
            return

        end_date = date.fromisoformat(config.end_date)
        if new_date >= end_date:
            print("Startdatum moet voor de einddatum liggen")
            return

        config.start_date = new_date.isoformat()
        print(f"Startdatum ingesteld op {config.start_date}")


def _edit_end_date(config: BacktestConfig) -> None:
    """Edit end date for backtest period."""
    from datetime import date

    current = config.end_date
    new_value = prompt(f"Nieuwe einddatum (YYYY-MM-DD) [{current}]: ")
    if new_value:
        try:
            new_date = date.fromisoformat(new_value)
        except ValueError:
            print("Ongeldige datum, gebruik formaat YYYY-MM-DD")
            return

        start_date = date.fromisoformat(config.start_date)
        if new_date <= start_date:
            print("Einddatum moet na de startdatum liggen")
            return

        config.end_date = new_date.isoformat()
        print(f"Einddatum ingesteld op {config.end_date}")


def _edit_profit_target(config: BacktestConfig) -> None:
    """Edit profit target percentage."""
    current = config.exit_rules.profit_target_pct
    new_value = prompt(f"Nieuwe profit target % [{current}]: ")
    if new_value:
        try:
            config.exit_rules.profit_target_pct = float(new_value)
            print(f"Profit target: {config.exit_rules.profit_target_pct}%")
        except ValueError:
            print("Ongeldige waarde")


def _edit_stop_loss(config: BacktestConfig) -> None:
    """Edit stop loss percentage."""
    current = config.exit_rules.stop_loss_pct
    new_value = prompt(f"Nieuwe stop loss % [{current}]: ")
    if new_value:
        try:
            config.exit_rules.stop_loss_pct = float(new_value)
            print(f"Stop loss: {config.exit_rules.stop_loss_pct}%")
        except ValueError:
            print("Ongeldige waarde")


def _edit_max_dit(config: BacktestConfig) -> None:
    """Edit maximum days in trade."""
    current = config.exit_rules.max_days_in_trade
    new_value = prompt(f"Nieuwe max DIT [{current}]: ")
    if new_value:
        try:
            config.exit_rules.max_days_in_trade = int(new_value)
            print(f"Max DIT: {config.exit_rules.max_days_in_trade} dagen")
        except ValueError:
            print("Ongeldige waarde")


def _edit_max_risk(config: BacktestConfig) -> None:
    """Edit maximum risk per trade."""
    current = config.position_sizing.max_risk_per_trade
    new_value = prompt(f"Nieuwe max risico per trade [{current}]: ")
    if new_value:
        try:
            config.position_sizing.max_risk_per_trade = float(new_value)
            print(f"Max risico: ${config.position_sizing.max_risk_per_trade}")
        except ValueError:
            print("Ongeldige waarde")


def _edit_symbols(config: BacktestConfig) -> None:
    """Edit symbol list."""
    current = ", ".join(config.symbols)
    print(f"Huidige symbolen: {current}")
    new_value = prompt("Nieuwe symbolen (komma-gescheiden): ")
    if new_value:
        symbols = [s.strip().upper() for s in new_value.split(",") if s.strip()]
        if symbols:
            config.symbols = symbols
            print(f"Symbolen: {', '.join(config.symbols)}")
        else:
            print("Geen geldige symbolen opgegeven")


def view_last_results() -> None:
    """View the last backtest results."""
    global _LAST_RESULT

    if _LAST_RESULT is None:
        print("\nGeen backtest resultaten beschikbaar.")
        print("Voer eerst een backtest uit.")
        return

    print("\n")
    print_backtest_report(_LAST_RESULT)


def export_results() -> None:
    """Export last results to JSON."""
    global _LAST_RESULT

    if _LAST_RESULT is None:
        print("\nGeen backtest resultaten beschikbaar.")
        print("Voer eerst een backtest uit.")
        return

    # Default filename
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"backtest_results_{timestamp}.json"

    filename = prompt(f"Bestandsnaam [{default_name}]: ")
    if not filename:
        filename = default_name

    # Ensure .json extension
    if not filename.endswith(".json"):
        filename += ".json"

    # Export to exports directory
    base_dir = Path(__file__).resolve().parent.parent.parent
    export_dir = base_dir / "exports"
    export_dir.mkdir(exist_ok=True)

    export_path = export_dir / filename

    try:
        report = BacktestReport(_LAST_RESULT)
        report.export_json(export_path)
        print(f"\nResultaten geexporteerd naar: {export_path}")
    except Exception as e:
        print(f"\nFout bij exporteren: {e}")


def quick_backtest(
    iv_percentile_min: float = 60.0,
    symbols: Optional[list] = None,
) -> None:
    """Run a quick backtest with custom parameters (for scripting)."""
    config = BacktestConfig()
    config.entry_rules.iv_percentile_min = iv_percentile_min
    if symbols:
        config.symbols = symbols

    result = run_backtest(config=config)
    print_backtest_report(result)
    return result


__all__ = [
    "run_backtest_menu",
    "run_iron_condor_backtest",
    "run_calendar_backtest",
    "run_both_backtests",
    "configure_backtest_params",
    "configure_iron_condor_params",
    "configure_calendar_params",
    "view_last_results",
    "export_results",
    "quick_backtest",
]
