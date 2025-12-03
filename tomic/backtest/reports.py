"""Reporting and visualization for backtest results.

Provides console output, tables, and export functionality
for backtest results using Rich for formatting.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from tomic.backtest.results import (
    BacktestResult,
    PerformanceMetrics,
    SimulatedTrade,
    TradeStatus,
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class BacktestReport:
    """Generate and display backtest reports."""

    def __init__(self, result: BacktestResult):
        self.result = result
        self.console = Console() if RICH_AVAILABLE else None

    def print_summary(self) -> None:
        """Print a summary of the backtest results to console."""
        if RICH_AVAILABLE:
            self._print_rich_summary()
        else:
            self._print_plain_summary()

    def _print_rich_summary(self) -> None:
        """Print summary using Rich formatting."""
        console = self.console

        # Header
        console.print()
        console.print(
            Panel.fit(
                "[bold blue]BACKTEST RESULTS[/bold blue]",
                border_style="blue",
            )
        )

        # Configuration summary
        self._print_config_table()

        # Performance metrics
        self._print_metrics_comparison()

        # Exit reasons breakdown
        self._print_exit_reasons()

        # Per-symbol breakdown
        self._print_symbol_breakdown()

        # Validation messages
        self._print_validation()

        # Equity curve (ASCII)
        self._print_equity_curve_ascii()

    def _print_config_table(self) -> None:
        """Print configuration summary table."""
        config = self.result.config_summary

        table = Table(title="Configuration", show_header=False, box=None)
        table.add_column("Parameter", style="cyan")
        table.add_column("Value")

        table.add_row("Strategy", config.get("strategy_type", "N/A"))
        table.add_row("Symbols", ", ".join(config.get("symbols", [])))
        table.add_row("Date Range", config.get("date_range", "N/A"))

        entry_rules = config.get("entry_rules", {})
        table.add_row(
            "Entry: IV Percentile Min",
            str(entry_rules.get("iv_percentile_min", "N/A")),
        )

        exit_rules = config.get("exit_rules", {})
        table.add_row(
            "Exit: Profit Target",
            f"{exit_rules.get('profit_target_pct', 'N/A')}%",
        )
        table.add_row(
            "Exit: Stop Loss",
            f"{exit_rules.get('stop_loss_pct', 'N/A')}%",
        )
        table.add_row(
            "Exit: Max DIT",
            f"{exit_rules.get('max_days_in_trade', 'N/A')} days",
        )

        pos_sizing = config.get("position_sizing", {})
        table.add_row(
            "Max Risk/Trade",
            f"${pos_sizing.get('max_risk_per_trade', 'N/A')}",
        )

        self.console.print(table)
        self.console.print()

    def _print_metrics_comparison(self) -> None:
        """Print side-by-side comparison of in-sample vs out-of-sample."""
        table = Table(title="Performance Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("In-Sample", justify="right")
        table.add_column("Out-of-Sample", justify="right")
        table.add_column("Combined", justify="right", style="bold")

        in_m = self.result.in_sample_metrics or PerformanceMetrics()
        out_m = self.result.out_sample_metrics or PerformanceMetrics()
        comb_m = self.result.combined_metrics or PerformanceMetrics()

        # Add rows
        metrics_rows = [
            ("Total Trades", "total_trades", "{:.0f}"),
            ("Win Rate", "win_rate", "{:.1%}"),
            ("Total P&L", "total_pnl", "${:.2f}"),
            ("Avg P&L/Trade", "average_pnl", "${:.2f}"),
            ("Profit Factor", "profit_factor", "{:.2f}"),
            ("Average Winner", "average_winner", "${:.2f}"),
            ("Average Loser", "average_loser", "${:.2f}"),
            ("Expectancy", "expectancy", "${:.2f}"),
            ("SQN", "sqn", "{:.2f}"),
            ("Sharpe Ratio", "sharpe_ratio", "{:.2f}"),
            ("Sortino Ratio", "sortino_ratio", "{:.2f}"),
            ("Max Drawdown", "max_drawdown_pct", "{:.1f}%"),
            ("Ret/DD", "ret_dd", "{:.2f}"),
            ("CAGR", "cagr", "{:.1f}%"),
            ("Avg Days in Trade", "avg_days_in_trade", "{:.1f}"),
            ("Max Consec. Wins", "max_consecutive_wins", "{:.0f}"),
            ("Max Consec. Losses", "max_consecutive_losses", "{:.0f}"),
        ]

        for label, attr, fmt in metrics_rows:
            in_val = getattr(in_m, attr, None)
            out_val = getattr(out_m, attr, None)
            comb_val = getattr(comb_m, attr, None)

            # Handle None values (e.g., ret_dd when no drawdown)
            def format_val(val):
                if val is None:
                    return "N/A"
                return fmt.format(val)

            in_str = format_val(in_val)
            out_str = format_val(out_val)
            comb_str = format_val(comb_val)

            table.add_row(label, in_str, out_str, comb_str)

        self.console.print(table)

        # Degradation score
        degradation = self.result.degradation_score
        if degradation is None:
            self.console.print("\n[dim]Degradation Score: N/A (no out-of-sample data)[/dim]")
        else:
            color = "green" if degradation < 25 else "yellow" if degradation < 50 else "red"
            self.console.print(
                f"\n[{color}]Degradation Score: {degradation:.1f}%[/{color}]"
            )
        self.console.print()

    def _print_exit_reasons(self) -> None:
        """Print breakdown of exit reasons."""
        if not self.result.combined_metrics:
            return

        exits = self.result.combined_metrics.exits_by_reason
        if not exits:
            return

        table = Table(title="Exit Reasons Breakdown")
        table.add_column("Exit Reason", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Percentage", justify="right")

        total = sum(exits.values())
        for reason, count in sorted(exits.items(), key=lambda x: -x[1]):
            pct = (count / total * 100) if total > 0 else 0
            table.add_row(reason, str(count), f"{pct:.1f}%")

        self.console.print(table)
        self.console.print()

    def _print_symbol_breakdown(self) -> None:
        """Print per-symbol performance breakdown (compact version)."""
        if not self.result.combined_metrics:
            return

        by_symbol = self.result.combined_metrics.metrics_by_symbol
        if not by_symbol:
            return

        table = Table(title="Performance by Symbol")
        table.add_column("Symbol", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Total P&L", justify="right")
        table.add_column("Avg P&L", justify="right")

        for symbol, metrics in sorted(by_symbol.items()):
            pnl_color = "green" if metrics["total_pnl"] > 0 else "red"
            table.add_row(
                symbol,
                str(metrics["total_trades"]),
                f"{metrics['win_rate']:.1%}",
                f"[{pnl_color}]${metrics['total_pnl']:.2f}[/{pnl_color}]",
                f"${metrics['avg_pnl']:.2f}",
            )

        self.console.print(table)
        self.console.print()

    def print_symbol_performance_table(self) -> None:
        """Print detailed per-symbol performance table sorted by Total Profit.

        Shows: Symbol | Trades | Win Rate | Avg Winner | Avg Loser |
               Profit Factor | Sharpe | Total Profit
        """
        if not self.result.combined_metrics:
            print("Geen resultaten beschikbaar.")
            return

        by_symbol = self.result.combined_metrics.metrics_by_symbol
        if not by_symbol:
            print("Geen per-symbool data beschikbaar.")
            return

        if RICH_AVAILABLE:
            self._print_rich_symbol_table(by_symbol)
        else:
            self._print_plain_symbol_table(by_symbol)

    def _print_rich_symbol_table(self, by_symbol: Dict[str, Any]) -> None:
        """Print detailed symbol table with Rich formatting."""
        console = self.console

        console.print()
        console.print(
            Panel.fit(
                "[bold]Per-symbool performance overzicht[/bold]\n"
                "[dim]Gesorteerd op Total Profit (aflopend)[/dim]",
                border_style="blue",
            )
        )

        table = Table(show_header=True, header_style="bold")
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg Winner", justify="right")
        table.add_column("Avg Loser", justify="right")
        table.add_column("Profit Factor", justify="right")
        table.add_column("Sharpe", justify="right")
        table.add_column("Total Profit", justify="right", style="bold")

        # Sort by total_pnl descending
        sorted_symbols = sorted(
            by_symbol.items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True,
        )

        for symbol, m in sorted_symbols:
            pnl_color = "green" if m["total_pnl"] > 0 else "red"

            # Format profit factor (handle infinity)
            pf = m.get("profit_factor", 0)
            pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"

            # Format avg loser as negative
            avg_loser = m.get("avg_loser", 0)
            avg_loser_str = f"-${avg_loser:.2f}" if avg_loser > 0 else "-"

            table.add_row(
                symbol,
                str(m["total_trades"]),
                f"{m['win_rate']:.1%}",
                f"${m.get('avg_winner', 0):.2f}",
                avg_loser_str,
                pf_str,
                f"{m.get('sharpe_ratio', 0):.2f}",
                f"[{pnl_color}]${m['total_pnl']:,.2f}[/{pnl_color}]",
            )

        console.print(table)
        console.print()

    def _print_plain_symbol_table(self, by_symbol: Dict[str, Any]) -> None:
        """Print detailed symbol table without Rich (fallback)."""
        print("\n" + "=" * 90)
        print("Per-symbool performance overzicht (gesorteerd op Total Profit)")
        print("=" * 90)
        print(
            f"{'Symbol':<8} {'Trades':>7} {'Win Rate':>9} {'Avg Win':>10} "
            f"{'Avg Loss':>10} {'PF':>6} {'Sharpe':>7} {'Total Profit':>13}"
        )
        print("-" * 90)

        sorted_symbols = sorted(
            by_symbol.items(),
            key=lambda x: x[1]["total_pnl"],
            reverse=True,
        )

        for symbol, m in sorted_symbols:
            pf = m.get("profit_factor", 0)
            pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
            avg_loser = m.get("avg_loser", 0)
            avg_loser_str = f"-${avg_loser:.2f}" if avg_loser > 0 else "-"

            print(
                f"{symbol:<8} {m['total_trades']:>7} {m['win_rate']:>8.1%} "
                f"${m.get('avg_winner', 0):>8.2f} {avg_loser_str:>10} "
                f"{pf_str:>6} {m.get('sharpe_ratio', 0):>7.2f} "
                f"${m['total_pnl']:>11,.2f}"
            )

        print("=" * 90)

    def _print_validation(self) -> None:
        """Print validation messages."""
        if not self.result.validation_messages:
            self.console.print("[green]All validation checks passed.[/green]")
            return

        self.console.print("[bold]Validation Messages:[/bold]")
        for msg in self.result.validation_messages:
            if "Warning:" in msg:
                self.console.print(f"  [yellow]{msg}[/yellow]")
            else:
                self.console.print(f"  {msg}")
        self.console.print()

    def _print_equity_curve_ascii(self) -> None:
        """Print a simple ASCII equity curve."""
        curve = self.result.equity_curve
        if not curve or len(curve) < 2:
            return

        self.console.print("[bold]Equity Curve:[/bold]")

        # Get equity values
        equities = [p["equity"] for p in curve]
        min_eq = min(equities)
        max_eq = max(equities)
        range_eq = max_eq - min_eq if max_eq > min_eq else 1

        # Determine chart height and width
        height = 10
        width = min(60, len(equities))

        # Sample points if too many
        if len(equities) > width:
            step = len(equities) // width
            sampled = equities[::step][:width]
        else:
            sampled = equities

        # Build chart
        chart_lines = []
        for row in range(height, 0, -1):
            threshold = min_eq + (range_eq * row / height)
            line = ""
            for eq in sampled:
                if eq >= threshold:
                    line += "*"
                else:
                    line += " "
            chart_lines.append(f"  {line}")

        # Print with scale
        self.console.print(f"  ${max_eq:,.0f}")
        for line in chart_lines:
            self.console.print(line)
        self.console.print(f"  ${min_eq:,.0f}")
        self.console.print()

    def _print_plain_summary(self) -> None:
        """Print summary without Rich formatting."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)

        if self.result.combined_metrics:
            m = self.result.combined_metrics
            print(f"\nTotal Trades: {m.total_trades}")
            print(f"Win Rate: {m.win_rate:.1%}")
            print(f"Total P&L: ${m.total_pnl:.2f}")
            print(f"Sharpe Ratio: {m.sharpe_ratio:.2f}")
            print(f"Max Drawdown: {m.max_drawdown_pct:.1f}%")
            print(f"Ret/DD: {'N/A' if m.ret_dd is None else f'{m.ret_dd:.2f}'}")

        degradation = self.result.degradation_score
        if degradation is None:
            print("\nDegradation Score: N/A (no out-of-sample data)")
        else:
            print(f"\nDegradation Score: {degradation:.1f}%")

        if self.result.validation_messages:
            print("\nValidation Messages:")
            for msg in self.result.validation_messages:
                print(f"  {msg}")

        print("=" * 60)

    def export_json(self, path: Path) -> None:
        """Export results to JSON file."""
        data = {
            "config_summary": self.result.config_summary,
            "date_range": {
                "start": str(self.result.start_date),
                "end": str(self.result.end_date),
                "in_sample_end": str(self.result.in_sample_end_date),
            },
            "degradation_score": self.result.degradation_score,
            "is_valid": self.result.is_valid,
            "validation_messages": self.result.validation_messages,
            "metrics": {
                "in_sample": self._metrics_to_dict(self.result.in_sample_metrics),
                "out_sample": self._metrics_to_dict(self.result.out_sample_metrics),
                "combined": self._metrics_to_dict(self.result.combined_metrics),
            },
            "equity_curve": self.result.equity_curve,
            "trades": [self._trade_to_dict(t) for t in self.result.trades],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _metrics_to_dict(self, metrics: Optional[PerformanceMetrics]) -> Dict[str, Any]:
        """Convert PerformanceMetrics to dict."""
        if not metrics:
            return {}
        return {
            "total_trades": metrics.total_trades,
            "win_rate": metrics.win_rate,
            "total_pnl": metrics.total_pnl,
            "profit_factor": metrics.profit_factor,
            "average_winner": metrics.average_winner,
            "average_loser": metrics.average_loser,
            "expectancy": metrics.expectancy,
            "sqn": metrics.sqn,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "ret_dd": metrics.ret_dd,
            "cagr": metrics.cagr,
            "avg_days_in_trade": metrics.avg_days_in_trade,
            "exits_by_reason": metrics.exits_by_reason,
            "metrics_by_symbol": metrics.metrics_by_symbol,
        }

    def _trade_to_dict(self, trade: SimulatedTrade) -> Dict[str, Any]:
        """Convert SimulatedTrade to dict."""
        return {
            "entry_date": str(trade.entry_date),
            "exit_date": str(trade.exit_date) if trade.exit_date else None,
            "symbol": trade.symbol,
            "strategy_type": trade.strategy_type,
            "iv_at_entry": trade.iv_at_entry,
            "iv_at_exit": trade.iv_at_exit,
            "max_risk": trade.max_risk,
            "estimated_credit": trade.estimated_credit,
            "final_pnl": trade.final_pnl,
            "days_in_trade": trade.days_in_trade,
            "exit_reason": trade.exit_reason.value if trade.exit_reason else None,
            "status": trade.status.value,
        }


def print_backtest_report(result: BacktestResult) -> None:
    """Convenience function to print a backtest report."""
    report = BacktestReport(result)
    report.print_summary()


__all__ = ["BacktestReport", "print_backtest_report"]
