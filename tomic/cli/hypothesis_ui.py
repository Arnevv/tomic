"""CLI interface for hypothesis testing functionality.

Provides menu handlers for creating, running, and analyzing
trading hypotheses.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.hypothesis import (
    Hypothesis,
    HypothesisEngine,
    HypothesisStore,
    HypothesisComparator,
    ScorecardBuilder,
    get_store,
)
from tomic.logutils import logger

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.panel import Panel

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def run_hypothesis_menu() -> None:
    """Run the hypothesis testing submenu."""
    menu = Menu("HYPOTHESE TESTING")
    menu.add("Nieuwe hypothese aanmaken & runnen", create_and_run_hypothesis)
    menu.add("Bestaande hypothese runnen", run_existing_hypothesis)
    menu.add("Hypotheses bekijken", list_hypotheses)
    menu.add("Hypotheses vergelijken", compare_hypotheses_menu)
    menu.add("Symbol scorecard", show_symbol_scorecard)
    menu.add("IV threshold scan", run_iv_threshold_scan)
    menu.add("Symbol vergelijking", run_symbol_comparison)
    menu.add("Hypothese verwijderen", delete_hypothesis)
    menu.run()


def create_and_run_hypothesis() -> None:
    """Create a new hypothesis and run it."""
    print("\n" + "=" * 60)
    print("NIEUWE HYPOTHESE AANMAKEN")
    print("=" * 60)

    # Get basic info
    name = prompt("Hypothese naam: ")
    if not name:
        print("Naam is verplicht.")
        return

    description = prompt("Beschrijving (optioneel): ")

    # Get symbols
    symbols_str = prompt("Symbol(s) [SPY]: ") or "SPY"
    symbols = [s.strip().upper() for s in symbols_str.split(",")]

    # Get strategy
    print("\nStrategieen: iron_condor, short_put_spread, short_call_spread")
    strategy = prompt("Strategie [iron_condor]: ") or "iron_condor"

    # Get entry parameters
    iv_min_str = prompt("IV Percentile minimum [60]: ") or "60"
    try:
        iv_percentile_min = float(iv_min_str)
    except ValueError:
        iv_percentile_min = 60.0

    # Get exit parameters
    profit_str = prompt("Profit target % [50]: ") or "50"
    try:
        profit_target_pct = float(profit_str)
    except ValueError:
        profit_target_pct = 50.0

    stop_str = prompt("Stop loss % [100]: ") or "100"
    try:
        stop_loss_pct = float(stop_str)
    except ValueError:
        stop_loss_pct = 100.0

    max_dit_str = prompt("Max dagen in trade [45]: ") or "45"
    try:
        max_days_in_trade = int(max_dit_str)
    except ValueError:
        max_days_in_trade = 45

    # Get date range
    start_date = prompt("Start datum [2024-01-01]: ") or "2024-01-01"
    end_date = prompt("Eind datum [2025-11-21]: ") or "2025-11-21"

    # Show summary
    print("\n" + "-" * 40)
    print("CONFIGURATIE SAMENVATTING")
    print("-" * 40)
    print(f"Naam: {name}")
    print(f"Symbolen: {', '.join(symbols)}")
    print(f"Strategie: {strategy}")
    print(f"IV percentile min: {iv_percentile_min}%")
    print(f"Profit target: {profit_target_pct}%")
    print(f"Stop loss: {stop_loss_pct}%")
    print(f"Max DIT: {max_days_in_trade} dagen")
    print(f"Periode: {start_date} tot {end_date}")

    if not prompt_yes_no("\nHypothese aanmaken en runnen?"):
        print("Geannuleerd.")
        return

    # Create and run
    engine = HypothesisEngine()

    print("\nHypothese wordt uitgevoerd...\n")

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

            hypothesis = engine.create_and_run(
                name=name,
                description=description,
                symbols=symbols,
                strategy_type=strategy,
                iv_percentile_min=iv_percentile_min,
                profit_target_pct=profit_target_pct,
                stop_loss_pct=stop_loss_pct,
                max_days_in_trade=max_days_in_trade,
                start_date=start_date,
                end_date=end_date,
                progress_callback=update_progress,
            )
    else:
        def simple_progress(message: str, percent: float) -> None:
            if percent % 20 == 0:
                print(f"[{percent:.0f}%] {message}")

        hypothesis = engine.create_and_run(
            name=name,
            description=description,
            symbols=symbols,
            strategy_type=strategy,
            iv_percentile_min=iv_percentile_min,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=stop_loss_pct,
            max_days_in_trade=max_days_in_trade,
            start_date=start_date,
            end_date=end_date,
            progress_callback=simple_progress,
        )

    print("\n")
    _print_hypothesis_result(hypothesis)


def run_existing_hypothesis() -> None:
    """Run an existing hypothesis from the store."""
    store = get_store()
    hypotheses = store.list_all()

    if not hypotheses:
        print("\nGeen hypotheses gevonden.")
        return

    # Show list
    print("\n" + "=" * 60)
    print("BESTAANDE HYPOTHESES")
    print("=" * 60)

    for i, hyp in enumerate(hypotheses[:20], 1):
        status_icon = {
            "draft": "[DRAFT]",
            "completed": "[OK]",
            "failed": "[FAIL]",
            "running": "[...]",
        }.get(hyp.status.value, "[?]")
        print(f"{i:2}. {status_icon} {hyp.name} ({hyp.id})")

    # Select hypothesis
    choice = prompt("\nKies nummer om te runnen (of Enter om terug te gaan): ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(hypotheses):
            hypothesis = hypotheses[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # Run it
    print(f"\nHypothese '{hypothesis.name}' wordt uitgevoerd...")

    engine = HypothesisEngine()

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

            hypothesis = engine.run(hypothesis, progress_callback=update_progress)
    else:
        hypothesis = engine.run(hypothesis)

    print("\n")
    _print_hypothesis_result(hypothesis)


def list_hypotheses() -> None:
    """List all stored hypotheses."""
    store = get_store()
    hypotheses = store.list_all()

    if not hypotheses:
        print("\nGeen hypotheses gevonden.")
        return

    print("\n")

    if RICH_AVAILABLE:
        console = Console()
        table = Table(title="Opgeslagen Hypotheses")

        table.add_column("ID", style="dim")
        table.add_column("Naam")
        table.add_column("Symbol(s)")
        table.add_column("Status")
        table.add_column("Trades")
        table.add_column("Win %")
        table.add_column("Sharpe")
        table.add_column("Score")

        for hyp in hypotheses[:30]:
            metrics = hyp.get_summary_metrics()
            status_style = {
                "draft": "yellow",
                "completed": "green",
                "failed": "red",
                "running": "blue",
            }.get(hyp.status.value, "white")

            table.add_row(
                hyp.id,
                hyp.name[:25],
                ", ".join(hyp.config.symbols)[:15],
                f"[{status_style}]{hyp.status.value}[/{status_style}]",
                metrics.get("trades", "-"),
                metrics.get("win_rate", "-"),
                metrics.get("sharpe", "-"),
                metrics.get("score", "-"),
            )

        console.print(table)
    else:
        print("=" * 80)
        print(f"{'ID':<10} {'Naam':<25} {'Symbols':<12} {'Status':<10} {'Score':<8}")
        print("=" * 80)

        for hyp in hypotheses[:30]:
            metrics = hyp.get_summary_metrics()
            print(
                f"{hyp.id:<10} {hyp.name[:25]:<25} "
                f"{', '.join(hyp.config.symbols)[:12]:<12} "
                f"{hyp.status.value:<10} {metrics.get('score', '-'):<8}"
            )

    # Show stats
    stats = store.get_stats()
    print(f"\nTotaal: {stats['total_hypotheses']} hypotheses "
          f"({stats['completed']} voltooid, {stats['draft']} draft, {stats['failed']} mislukt)")


def compare_hypotheses_menu() -> None:
    """Compare multiple hypotheses."""
    store = get_store()
    completed = store.list_completed()

    if len(completed) < 2:
        print("\nMinstens 2 voltooide hypotheses nodig voor vergelijking.")
        return

    print("\n" + "=" * 60)
    print("HYPOTHESE VERGELIJKING")
    print("=" * 60)

    # Options
    print("\n1. Laatste N hypotheses vergelijken")
    print("2. Specifieke hypotheses kiezen")
    print("3. Batch vergelijken")

    choice = prompt("\nKeuze [1]: ") or "1"

    comparator = HypothesisComparator()

    if choice == "1":
        n_str = prompt("Aantal hypotheses [5]: ") or "5"
        try:
            n = int(n_str)
        except ValueError:
            n = 5
        comparison = comparator.compare_last_n(n)

    elif choice == "2":
        # Show list and let user select
        print("\nVoltooide hypotheses:")
        for i, hyp in enumerate(completed[:20], 1):
            print(f"{i:2}. {hyp.name} ({hyp.id})")

        ids_str = prompt("\nKies nummers (komma-gescheiden): ")
        if not ids_str:
            return

        try:
            indices = [int(x.strip()) - 1 for x in ids_str.split(",")]
            selected = [completed[i] for i in indices if 0 <= i < len(completed)]
        except (ValueError, IndexError):
            print("Ongeldige invoer.")
            return

        comparison = comparator.compare(selected)

    elif choice == "3":
        batches = store.list_batches()
        if not batches:
            print("\nGeen batches gevonden.")
            return

        print("\nBeschikbare batches:")
        for i, batch in enumerate(batches, 1):
            print(f"{i:2}. {batch.name} ({len(batch.hypothesis_ids)} hypotheses)")

        batch_choice = prompt("\nKies batch nummer: ")
        try:
            idx = int(batch_choice) - 1
            if 0 <= idx < len(batches):
                comparison = comparator.compare_batch(batches[idx].name)
            else:
                print("Ongeldige keuze.")
                return
        except ValueError:
            print("Ongeldige invoer.")
            return
    else:
        print("Ongeldige keuze.")
        return

    # Print comparison
    _print_comparison(comparison)


def show_symbol_scorecard() -> None:
    """Show the symbol scorecard."""
    store = get_store()
    completed = store.list_completed()

    if not completed:
        print("\nGeen voltooide hypotheses gevonden.")
        print("Run eerst enkele hypotheses om een scorecard te genereren.")
        return

    # Get unique symbols
    symbols = set()
    for hyp in completed:
        symbols.update(hyp.config.symbols)

    print("\n" + "=" * 60)
    print("SYMBOL SCORECARD")
    print("=" * 60)

    builder = ScorecardBuilder()
    scorecard = builder.build()

    if not scorecard.scores:
        print("\nGeen scores beschikbaar.")
        return

    if RICH_AVAILABLE:
        console = Console()
        table = Table(title=f"Symbol Voorspelbaarheid ({len(completed)} hypotheses)")

        table.add_column("Rank", style="bold")
        table.add_column("Symbol")
        table.add_column("Score", style="cyan")
        table.add_column("Best Win%")
        table.add_column("Best Sharpe")
        table.add_column("Degradation")
        table.add_column("Best IV")
        table.add_column("Best Strategy")

        for rank, score in enumerate(scorecard.get_ranked_symbols(), 1):
            # Score bar
            bar_length = int(score.predictability_score / 10)
            bar = "#" * bar_length + "-" * (10 - bar_length)

            table.add_row(
                str(rank),
                score.symbol,
                f"{score.predictability_score:.0f} [{bar}]",
                f"{score.best_win_rate:.1f}%",
                f"{score.best_sharpe:.2f}",
                f"{score.avg_degradation:.1f}%",
                f">={score.best_iv_threshold:.0f}%" if score.best_iv_threshold else "-",
                score.best_strategy or "-",
            )

        console.print(table)

        # Recommendations
        recs = scorecard.get_recommendations()
        if recs.get("top_symbols"):
            print("\nAanbevelingen:")
            for rec in recs["top_symbols"]:
                print(f"  - {rec['symbol']}: Score {rec['score']:.0f}, "
                      f"beste strategie: {rec.get('best_strategy', 'iron_condor')}, "
                      f"IV threshold: >={rec.get('best_iv_threshold', 60):.0f}%")

    else:
        print("\n" + "-" * 70)
        print(f"{'Rank':<6} {'Symbol':<8} {'Score':<8} {'Win%':<8} {'Sharpe':<8} {'IV':<8}")
        print("-" * 70)

        for rank, score in enumerate(scorecard.get_ranked_symbols(), 1):
            print(
                f"{rank:<6} {score.symbol:<8} {score.predictability_score:<8.0f} "
                f"{score.best_win_rate:<8.1f} {score.best_sharpe:<8.2f} "
                f"{score.best_iv_threshold or 60:<8.0f}"
            )


def run_iv_threshold_scan() -> None:
    """Run an IV threshold scan for a symbol."""
    print("\n" + "=" * 60)
    print("IV THRESHOLD SCAN")
    print("=" * 60)

    symbol = prompt("Symbol [SPY]: ").upper() or "SPY"

    iv_str = prompt("IV waarden (komma-gescheiden) [50,60,70,80]: ") or "50,60,70,80"
    try:
        iv_values = [float(x.strip()) for x in iv_str.split(",")]
    except ValueError:
        print("Ongeldige IV waarden.")
        return

    start_date = prompt("Start datum [2024-01-01]: ") or "2024-01-01"
    end_date = prompt("Eind datum [2025-11-21]: ") or "2025-11-21"

    print(f"\nScan voor {symbol} met IV thresholds: {iv_values}")

    if not prompt_yes_no("Scan starten?"):
        return

    engine = HypothesisEngine()

    print("\nScan wordt uitgevoerd...\n")

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

            batch = engine.run_iv_threshold_scan(
                symbol=symbol,
                iv_values=iv_values,
                start_date=start_date,
                end_date=end_date,
                progress_callback=update_progress,
            )
    else:
        def simple_progress(message: str, percent: float) -> None:
            print(f"[{percent:.0f}%] {message}")

        batch = engine.run_iv_threshold_scan(
            symbol=symbol,
            iv_values=iv_values,
            start_date=start_date,
            end_date=end_date,
            progress_callback=simple_progress,
        )

    print(f"\nBatch '{batch.name}' voltooid met {len(batch.hypothesis_ids)} hypotheses.")

    # Show comparison
    comparator = HypothesisComparator()
    comparison = comparator.compare_batch(batch.name)
    _print_comparison(comparison)


def run_symbol_comparison() -> None:
    """Run a comparison across multiple symbols."""
    print("\n" + "=" * 60)
    print("SYMBOL VERGELIJKING")
    print("=" * 60)

    symbols_str = prompt("Symbols (komma-gescheiden) [SPY,QQQ,IWM]: ") or "SPY,QQQ,IWM"
    symbols = [s.strip().upper() for s in symbols_str.split(",")]

    iv_str = prompt("IV percentile minimum [60]: ") or "60"
    try:
        iv_percentile_min = float(iv_str)
    except ValueError:
        iv_percentile_min = 60.0

    start_date = prompt("Start datum [2024-01-01]: ") or "2024-01-01"
    end_date = prompt("Eind datum [2025-11-21]: ") or "2025-11-21"

    print(f"\nVergelijking voor: {', '.join(symbols)}")

    if not prompt_yes_no("Vergelijking starten?"):
        return

    engine = HypothesisEngine()

    print("\nVergelijking wordt uitgevoerd...\n")

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

            batch = engine.run_symbol_comparison(
                symbols=symbols,
                iv_percentile_min=iv_percentile_min,
                start_date=start_date,
                end_date=end_date,
                progress_callback=update_progress,
            )
    else:
        def simple_progress(message: str, percent: float) -> None:
            print(f"[{percent:.0f}%] {message}")

        batch = engine.run_symbol_comparison(
            symbols=symbols,
            iv_percentile_min=iv_percentile_min,
            start_date=start_date,
            end_date=end_date,
            progress_callback=simple_progress,
        )

    print(f"\nBatch '{batch.name}' voltooid.")

    # Show comparison
    comparator = HypothesisComparator()
    comparison = comparator.compare_batch(batch.name)
    _print_comparison(comparison)


def delete_hypothesis() -> None:
    """Delete a hypothesis from the store."""
    store = get_store()
    hypotheses = store.list_all()

    if not hypotheses:
        print("\nGeen hypotheses om te verwijderen.")
        return

    print("\n" + "=" * 60)
    print("HYPOTHESE VERWIJDEREN")
    print("=" * 60)

    for i, hyp in enumerate(hypotheses[:20], 1):
        print(f"{i:2}. {hyp.name} ({hyp.id})")

    choice = prompt("\nKies nummer om te verwijderen: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(hypotheses):
            hypothesis = hypotheses[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    if prompt_yes_no(f"\nWeet je zeker dat je '{hypothesis.name}' wilt verwijderen?"):
        store.delete(hypothesis.id)
        print(f"Hypothese '{hypothesis.name}' verwijderd.")


def _print_hypothesis_result(hypothesis: Hypothesis) -> None:
    """Print results for a single hypothesis."""
    if not hypothesis.is_completed:
        print(f"Hypothese status: {hypothesis.status.value}")
        if hypothesis.error_message:
            print(f"Fout: {hypothesis.error_message}")
        return

    metrics = hypothesis.get_summary_metrics()

    if RICH_AVAILABLE:
        console = Console()

        # Summary panel
        summary = f"""[bold]{hypothesis.name}[/bold]
{hypothesis.config.description or 'Geen beschrijving'}

[cyan]Configuratie:[/cyan]
  Symbols: {', '.join(hypothesis.config.symbols)}
  Strategie: {hypothesis.config.strategy_type}
  IV min: {hypothesis.config.iv_percentile_min}%
  Profit target: {hypothesis.config.profit_target_pct}%

[cyan]Resultaten:[/cyan]
  Trades: {metrics.get('trades', '-')}
  Win rate: {metrics.get('win_rate', '-')}
  Sharpe ratio: {metrics.get('sharpe', '-')}
  Total P&L: {metrics.get('total_pnl', '-')}
  Profit factor: {metrics.get('profit_factor', '-')}
  Max drawdown: {metrics.get('max_drawdown', '-')}
  Degradation: {metrics.get('degradation', '-')}

[bold green]Score: {metrics.get('score', 'N/A')}[/bold green]"""

        console.print(Panel(summary, title="Hypothese Resultaat"))

    else:
        print("=" * 60)
        print(f"HYPOTHESE: {hypothesis.name}")
        print("=" * 60)
        print(f"Symbols: {', '.join(hypothesis.config.symbols)}")
        print(f"IV min: {hypothesis.config.iv_percentile_min}%")
        print("-" * 40)
        print(f"Trades: {metrics.get('trades', '-')}")
        print(f"Win rate: {metrics.get('win_rate', '-')}")
        print(f"Sharpe: {metrics.get('sharpe', '-')}")
        print(f"Total P&L: {metrics.get('total_pnl', '-')}")
        print(f"Degradation: {metrics.get('degradation', '-')}")
        print("-" * 40)
        print(f"SCORE: {metrics.get('score', 'N/A')}")


def _print_comparison(comparison) -> None:
    """Print a hypothesis comparison."""
    if not comparison.hypotheses:
        print("\nGeen hypotheses om te vergelijken.")
        return

    table_data = comparison.to_table_data()

    if not table_data:
        print("\nGeen resultaten beschikbaar.")
        return

    if RICH_AVAILABLE:
        console = Console()
        table = Table(title="Hypothese Vergelijking")

        table.add_column("#", style="bold")
        table.add_column("Naam")
        table.add_column("Symbol(s)")
        table.add_column("Trades")
        table.add_column("Win %", style="cyan")
        table.add_column("Sharpe", style="cyan")
        table.add_column("P&L")
        table.add_column("PF")
        table.add_column("DD")
        table.add_column("Degr.")
        table.add_column("Score", style="bold green")

        for row in table_data:
            # Highlight winner
            style = "bold" if row["rank"] == 1 else None
            table.add_row(
                str(row["rank"]),
                row["name"][:20],
                row["symbol"][:10],
                str(row["trades"]),
                row["win_rate"],
                row["sharpe"],
                row["total_pnl"],
                row["profit_factor"],
                row["max_dd"],
                row["degradation"],
                row["score"],
                style=style,
            )

        console.print(table)

        # Winner
        winner = comparison.get_winner()
        if winner:
            print(f"\nWinnaar: {winner.name}")

    else:
        print("\n" + "=" * 100)
        print("HYPOTHESE VERGELIJKING")
        print("=" * 100)
        print(f"{'#':<3} {'Naam':<20} {'Symbol':<8} {'Trades':<7} {'Win%':<7} "
              f"{'Sharpe':<7} {'P&L':<10} {'Score':<7}")
        print("-" * 100)

        for row in table_data:
            print(
                f"{row['rank']:<3} {row['name'][:20]:<20} {row['symbol'][:8]:<8} "
                f"{row['trades']:<7} {row['win_rate']:<7} {row['sharpe']:<7} "
                f"{row['total_pnl']:<10} {row['score']:<7}"
            )


__all__ = [
    "run_hypothesis_menu",
    "create_and_run_hypothesis",
    "list_hypotheses",
    "compare_hypotheses_menu",
    "show_symbol_scorecard",
    "run_iv_threshold_scan",
    "run_symbol_comparison",
]
