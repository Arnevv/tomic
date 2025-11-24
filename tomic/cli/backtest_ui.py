"""CLI interface for backtesting functionality.

Provides menu handlers for running and configuring backtests
within the TOMIC control panel.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.backtest.config import (
    BacktestConfig,
    load_backtest_config,
    save_backtest_config,
)
from tomic.backtest.engine import BacktestEngine, run_backtest
from tomic.backtest.reports import BacktestReport, print_backtest_report
from tomic.logutils import logger

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Store last result for viewing
_LAST_RESULT = None


def run_backtest_menu() -> None:
    """Run the backtesting submenu."""
    menu = Menu("📈 BACKTESTING")
    menu.add("Iron Condor Backtest uitvoeren", run_iron_condor_backtest)
    menu.add("Parameters configureren", configure_backtest_params)
    menu.add("Laatste resultaten bekijken", view_last_results)
    menu.add("Resultaten exporteren (JSON)", export_results)
    menu.run()


def run_iron_condor_backtest() -> None:
    """Run a full Iron Condor backtest."""
    global _LAST_RESULT

    print("\n" + "=" * 60)
    print("IRON CONDOR BACKTEST")
    print("=" * 60)

    # Load configuration
    try:
        config = load_backtest_config()
    except Exception as e:
        print(f"Fout bij laden configuratie: {e}")
        print("Gebruik standaard configuratie...")
        config = BacktestConfig()

    # Show configuration summary
    print(f"\nStrategie: {config.strategy_type}")
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

    print("\nBacktest wordt uitgevoerd...\n")

    # Run backtest with progress feedback
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
                result = run_backtest(config=config, progress_callback=update_progress)
            except Exception as e:
                logger.error(f"Backtest fout: {e}")
                print(f"\nFout tijdens backtest: {e}")
                return
    else:
        # Simple progress without Rich
        def simple_progress(message: str, percent: float) -> None:
            if percent % 20 == 0:  # Print every 20%
                print(f"[{percent:.0f}%] {message}")

        try:
            result = run_backtest(config=config, progress_callback=simple_progress)
        except Exception as e:
            logger.error(f"Backtest fout: {e}")
            print(f"\nFout tijdens backtest: {e}")
            return

    # Store result
    _LAST_RESULT = result

    # Print results
    print("\n")
    print_backtest_report(result)

    # Prompt to export
    if prompt_yes_no("\nResultaten exporteren naar JSON?"):
        export_results()


def configure_backtest_params() -> None:
    """Interactive configuration of backtest parameters."""
    print("\n" + "=" * 60)
    print("BACKTEST CONFIGURATIE")
    print("=" * 60)

    # Load current config
    try:
        config = load_backtest_config()
    except Exception:
        config = BacktestConfig()

    menu = Menu("Configuratie Opties", exit_text="Terug (wijzigingen opslaan)")

    # Entry rules
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


def _edit_iv_percentile_min(config: BacktestConfig) -> None:
    """Edit IV percentile minimum."""
    current = config.entry_rules.iv_percentile_min
    new_value = prompt(f"Nieuwe IV percentile minimum [{current}]: ")
    if new_value:
        try:
            config.entry_rules.iv_percentile_min = float(new_value)
            print(f"IV percentile minimum: {config.entry_rules.iv_percentile_min}")
        except ValueError:
            print("Ongeldige waarde")


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
    "configure_backtest_params",
    "view_last_results",
    "export_results",
    "quick_backtest",
]
