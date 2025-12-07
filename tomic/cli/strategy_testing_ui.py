"""CLI interface for unified strategy testing functionality.

Combines backtesting, what-if analysis, and parameter sweeps
into a single coherent interface that works with live configuration.

Supports multiple strategy types:
- Iron Condor: Credit strategy, enter on HIGH IV
- Calendar Spread: Debit strategy, enter on LOW IV
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.cli.external_validation_export import run_external_validation_export
from tomic.logutils import logger

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Strategy type constants
STRATEGY_IRON_CONDOR = "iron_condor"
STRATEGY_CALENDAR = "calendar"

STRATEGY_DISPLAY_NAMES = {
    STRATEGY_IRON_CONDOR: "Iron Condor",
    STRATEGY_CALENDAR: "Calendar Spread",
}


def _select_strategy_for_testing() -> Optional[str]:
    """Prompt user to select a strategy type for testing.

    Returns:
        Strategy type string ('iron_condor', 'calendar', 'both'), or None if cancelled.
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


# =============================================================================
# Configuration Loading
# =============================================================================

# Module-level cache for configuration to avoid repeated YAML parsing
_CONFIG_CACHE: Dict[str, Dict[str, Any]] = {}


def clear_config_cache() -> None:
    """Clear the configuration cache.

    Call this after modifying config files to ensure fresh values are loaded.
    """
    global _CONFIG_CACHE
    _CONFIG_CACHE.clear()


def load_live_config(strategy: str = STRATEGY_IRON_CONDOR, use_cache: bool = True) -> Dict[str, Any]:
    """Load all live configuration from YAML files.

    Args:
        strategy: Strategy type to load config for (iron_condor or calendar)
        use_cache: If True (default), use cached config if available

    Returns a merged dictionary with all parameters that affect strategy testing:
    - From strategies.yaml: min_risk_reward, min_rom, min_edge, min_pos, etc.
    - From criteria.yaml: acceptance criteria
    - From backtest.yaml or backtest_calendar.yaml: entry/exit rules
    - From volatility_rules.yaml: IV/skew entry criteria per strategy
    - From strike_selection_rules.yaml: DTE range, delta range per strategy
    """
    # Check cache first
    if use_cache and strategy in _CONFIG_CACHE:
        return _CONFIG_CACHE[strategy]

    from tomic.config import _load_yaml, _BASE_DIR

    config: Dict[str, Any] = {}
    config["strategy_type"] = strategy

    # Load strategies.yaml
    strategies_path = _BASE_DIR / "config" / "strategies.yaml"
    if strategies_path.exists():
        data = _load_yaml(strategies_path)
        config["strategies"] = data.get("strategies", {})
        config["strategy_defaults"] = data.get("default", {})

    # Load backtest config (strategy-specific)
    if strategy == STRATEGY_CALENDAR:
        backtest_path = _BASE_DIR / "config" / "backtest_calendar.yaml"
    else:
        backtest_path = _BASE_DIR / "config" / "backtest.yaml"

    if backtest_path.exists():
        config["backtest"] = _load_yaml(backtest_path)

    # Load criteria.yaml
    criteria_path = _BASE_DIR / "criteria.yaml"
    if criteria_path.exists():
        config["criteria"] = _load_yaml(criteria_path)

    # Load volatility_rules.yaml (list of strategy rules)
    volatility_path = _BASE_DIR / "tomic" / "volatility_rules.yaml"
    if volatility_path.exists():
        vol_rules = _load_yaml(volatility_path)
        # Convert list to dict keyed by strategy
        if isinstance(vol_rules, list):
            config["volatility_rules"] = {
                rule.get("key"): rule for rule in vol_rules if rule.get("key")
            }
        else:
            config["volatility_rules"] = vol_rules or {}

    # Load strike_selection_rules.yaml
    strike_path = _BASE_DIR / "tomic" / "strike_selection_rules.yaml"
    if strike_path.exists():
        strike_rules = _load_yaml(strike_path)
        config["strike_selection_rules"] = strike_rules or {}

    # Cache the result for subsequent calls
    if use_cache:
        _CONFIG_CACHE[strategy] = config

    return config


def get_strategy_param(
    config: Dict[str, Any],
    strategy: str,
    param: str,
    default: Any = None
) -> Any:
    """Get a parameter value for a strategy with fallback to defaults."""
    # First check strategy-specific
    strategies = config.get("strategies", {})
    if strategy in strategies and param in strategies[strategy]:
        return strategies[strategy][param]

    # Then check defaults
    defaults = config.get("strategy_defaults", {})
    if param in defaults:
        return defaults[param]

    return default


def get_testable_parameters(strategy: str = STRATEGY_IRON_CONDOR) -> List[Dict[str, Any]]:
    """Get list of parameters that can be tested for a strategy."""
    config = load_live_config(strategy)

    params = []

    # Strategy parameters from strategies.yaml
    strategy_params = [
        ("min_risk_reward", "Minimum Risk/Reward ratio", "scoring"),
        ("min_rom", "Minimum Return on Margin", "scoring"),
        ("min_edge", "Minimum Edge", "scoring"),
        ("min_pos", "Minimum Probability of Success", "scoring"),
        ("min_ev", "Minimum Expected Value", "scoring"),
    ]

    for param_key, description, category in strategy_params:
        current = get_strategy_param(config, strategy, param_key)
        if current is not None:
            params.append({
                "key": param_key,
                "description": description,
                "category": category,
                "current_value": current,
                "source": "strategies.yaml",
            })

    # Backtest parameters (strategy-specific)
    backtest = config.get("backtest", {})
    entry_rules = backtest.get("entry_rules", {})
    exit_rules = backtest.get("exit_rules", {})

    # Different entry params based on strategy
    if strategy == STRATEGY_CALENDAR:
        # Calendar uses IV percentile MAX (low IV entry)
        backtest_params = [
            ("iv_percentile_max", "IV Percentile maximum", "entry", entry_rules.get("iv_percentile_max", 40.0)),
            ("term_structure_min", "Term Structure minimum", "entry", entry_rules.get("term_structure_min", 0.0)),
            ("min_days_until_earnings", "Min dagen tot earnings", "entry", entry_rules.get("min_days_until_earnings", 10)),
            ("profit_target_pct", "Profit Target %", "exit", exit_rules.get("profit_target_pct", 10.0)),
            ("stop_loss_pct", "Stop Loss %", "exit", exit_rules.get("stop_loss_pct", 10.0)),
            ("max_days_in_trade", "Max Days in Trade", "exit", exit_rules.get("max_days_in_trade", 10)),
        ]
        config_source = "backtest_calendar.yaml"
    else:
        # Iron Condor uses IV percentile MIN (high IV entry)
        backtest_params = [
            ("iv_percentile_min", "IV Percentile minimum", "entry", entry_rules.get("iv_percentile_min", 60.0)),
            ("min_days_until_earnings", "Min dagen tot earnings", "entry", entry_rules.get("min_days_until_earnings", 10)),
            ("profit_target_pct", "Profit Target %", "exit", exit_rules.get("profit_target_pct", 50.0)),
            ("stop_loss_pct", "Stop Loss %", "exit", exit_rules.get("stop_loss_pct", 100.0)),
            ("max_days_in_trade", "Max Days in Trade", "exit", exit_rules.get("max_days_in_trade", 45)),
        ]
        config_source = "backtest.yaml"

    for param_key, description, category, current in backtest_params:
        if current is not None:
            params.append({
                "key": param_key,
                "description": description,
                "category": category,
                "current_value": current,
                "source": config_source,
            })

    # Strike selection parameters from strike_selection_rules.yaml
    strike_rules = config.get("strike_selection_rules", {})
    default_strike = strike_rules.get("default", {})
    strategy_strike = strike_rules.get(strategy, {})

    # DTE range
    dte_range = strategy_strike.get("dte_range") or default_strike.get("dte_range")
    if dte_range:
        params.append({
            "key": "dte_range",
            "description": "DTE Range [min, max]",
            "category": "strike_selection",
            "current_value": dte_range,
            "source": "strike_selection_rules.yaml",
        })

    # Delta range (for delta-based strategies)
    delta_range = strategy_strike.get("short_delta_range") or strategy_strike.get("delta_range")
    if delta_range:
        params.append({
            "key": "delta_range",
            "description": "Delta Range [min, max]",
            "category": "strike_selection",
            "current_value": delta_range,
            "source": "strike_selection_rules.yaml",
        })

    # Stddev range (for iron condors etc.)
    stddev_range = strategy_strike.get("stddev_range")
    if stddev_range:
        params.append({
            "key": "stddev_range",
            "description": "Std Dev Range",
            "category": "strike_selection",
            "current_value": stddev_range,
            "source": "strike_selection_rules.yaml",
        })

    # Volatility rules from volatility_rules.yaml
    vol_rules = config.get("volatility_rules", {})
    strategy_vol = vol_rules.get(strategy, {})
    criteria = strategy_vol.get("criteria", [])

    # Parse volatility criteria into testable parameters
    for criterion in criteria:
        if isinstance(criterion, str):
            # Parse criteria like "iv_rank >= 0.5"
            parsed = _parse_vol_criterion(criterion)
            if parsed:
                params.append({
                    "key": f"vol_{parsed['field']}",
                    "description": f"Vol Rule: {parsed['field']} {parsed['operator']} {parsed['value']}",
                    "category": "volatility",
                    "current_value": parsed["value"],
                    "source": "volatility_rules.yaml",
                    "operator": parsed["operator"],
                    "field": parsed["field"],
                })

    return params


def _parse_vol_criterion(criterion: str) -> Optional[Dict[str, Any]]:
    """Parse a volatility criterion string like 'iv_rank >= 0.5'."""
    import re
    # Match patterns like: field >= value, field <= value, field > value, field < value
    match = re.match(r"(\w+)\s*(>=|<=|>|<|==)\s*([\d.]+)", criterion.strip())
    if match:
        return {
            "field": match.group(1),
            "operator": match.group(2),
            "value": float(match.group(3)),
        }
    return None


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TestResult:
    """Result from a single backtest run."""

    config_label: str
    param_value: Any
    trades: int
    win_rate: float
    total_pnl: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    ret_dd: Optional[float]
    degradation: Optional[float]
    is_baseline: bool = False
    backtest_result: Optional[Any] = None  # Full BacktestResult for detailed views


@dataclass
class ComparisonResult:
    """Result comparing baseline vs what-if scenario."""

    baseline: TestResult
    whatif: TestResult
    param_name: str
    param_old_value: Any
    param_new_value: Any


# =============================================================================
# Main Menu
# =============================================================================


def run_strategy_testing_menu() -> None:
    """Run the unified strategy testing submenu."""
    menu = Menu("STRATEGY TESTING")
    menu.add("Live Config Validatie", run_live_config_validation)
    menu.add("What-If Analyse", run_whatif_analysis)
    menu.add("Parameter Sweep", run_parameter_sweep)
    menu.add("Custom Experiment", run_custom_experiment)
    menu.add("Resultaten Bekijken", view_results)
    menu.add("Test Configuratie", configure_test_settings)
    menu.add("Export voor Externe Validatie", run_external_validation_export)
    menu.run()


# =============================================================================
# Mode 1: Live Config Validation
# =============================================================================


def run_live_config_validation() -> None:
    """Test current live configuration against historical data."""
    print("\n" + "=" * 70)
    print("LIVE CONFIG VALIDATIE")
    print("=" * 70)
    print("\nTest je huidige productie-configuratie tegen historische data.")

    # Select strategy
    strategy = _select_strategy_for_testing()
    if strategy is None:
        return

    # Handle "both" strategy comparison
    if strategy == "both":
        _run_both_strategies_validation()
        return

    strategy_name = STRATEGY_DISPLAY_NAMES.get(strategy, strategy)

    # Show which config files are used
    if strategy == STRATEGY_CALENDAR:
        print("\nGebruikt: strategies.yaml, criteria.yaml, backtest_calendar.yaml,")
    else:
        print("\nGebruikt: strategies.yaml, criteria.yaml, backtest.yaml,")
    print("          volatility_rules.yaml, strike_selection_rules.yaml")

    # Load and show current config
    config = load_live_config(strategy)

    print("\n" + "-" * 50)
    print(f"HUIDIGE CONFIGURATIE ({strategy_name})")
    print("-" * 50)

    # Show key parameters grouped by category
    params = get_testable_parameters(strategy)

    # Group by category
    categories = {}
    for p in params:
        cat = p.get("category", "other")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)

    category_names = {
        "scoring": "SCORING (strategies.yaml)",
        "entry": "ENTRY RULES (backtest.yaml)",
        "exit": "EXIT RULES (backtest.yaml)",
        "strike_selection": "STRIKE SELECTIE (strike_selection_rules.yaml)",
        "volatility": "VOLATILITY REGELS (volatility_rules.yaml)",
    }

    for cat, cat_params in categories.items():
        cat_name = category_names.get(cat, cat.upper())
        print(f"\n  {cat_name}:")
        for p in cat_params:
            print(f"    {p['description']:35} = {p['current_value']}")

    print("\n" + "-" * 50)

    if not prompt_yes_no("\nBacktest starten met deze configuratie?"):
        print("Geannuleerd.")
        return

    # Run backtest with live config
    result = _run_backtest_with_config(
        strategy=strategy,
        overrides={},  # No overrides - use live config
        label="Live Config",
        show_progress=True,
    )

    if result:
        _print_single_result(result)

        # Store for later viewing
        _store_result("live_validation", result)


def _run_both_strategies_validation() -> None:
    """Run validation for both Iron Condor and Calendar strategies and compare."""
    print("\n" + "=" * 70)
    print("VERGELIJKING: IRON CONDOR vs CALENDAR")
    print("=" * 70)
    print("\nBeide strategieen worden gevalideerd met hun live configuratie.")
    print("Dit laat zien hoe ze presteren in verschillende marktomstandigheden.")

    # Show config summary for both
    for strat in [STRATEGY_IRON_CONDOR, STRATEGY_CALENDAR]:
        strat_name = STRATEGY_DISPLAY_NAMES.get(strat, strat)
        print(f"\n{'-' * 50}")
        print(f"{strat_name.upper()} CONFIGURATIE")
        print("-" * 50)

        params = get_testable_parameters(strat)
        # Show key entry/exit params
        for p in params:
            if p["category"] in ("entry", "exit"):
                print(f"  {p['description']:30} = {p['current_value']}")

    print("\n" + "-" * 50)

    if not prompt_yes_no("\nBeide backtests starten?"):
        print("Geannuleerd.")
        return

    # Run both strategies in parallel for better performance
    print("\n" + "=" * 60)
    print("BACKTESTS DRAAIEN PARALLEL...")
    print("=" * 60)

    ic_result = None
    cal_result = None

    def run_ic():
        return _run_backtest_with_config(
            strategy=STRATEGY_IRON_CONDOR,
            overrides={},
            label="Iron Condor (Live Config)",
            show_progress=False,
        )

    def run_cal():
        return _run_backtest_with_config(
            strategy=STRATEGY_CALENDAR,
            overrides={},
            label="Calendar Spread (Live Config)",
            show_progress=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ic_future = executor.submit(run_ic)
        cal_future = executor.submit(run_cal)

        # Wait for both to complete
        ic_result = ic_future.result()
        cal_result = cal_future.result()

    print("Beide backtests voltooid.")

    # Show comparison
    if ic_result and cal_result:
        _print_strategy_comparison(ic_result, cal_result)

        # Store for later viewing
        _store_result("live_validation_ic", ic_result)
        _store_result("live_validation_cal", cal_result)
    elif ic_result:
        print("\nCalendar backtest mislukt. Alleen Iron Condor resultaat:")
        _print_single_result(ic_result)
    elif cal_result:
        print("\nIron Condor backtest mislukt. Alleen Calendar resultaat:")
        _print_single_result(cal_result)
    else:
        print("\nBeide backtests mislukt.")


def _print_strategy_comparison(ic: TestResult, cal: TestResult) -> None:
    """Print a side-by-side comparison of Iron Condor vs Calendar results."""
    print("\n" + "=" * 80)
    print("VERGELIJKING: IRON CONDOR vs CALENDAR")
    print("=" * 80)

    # Header
    print(f"\n{'Metric':<20} {'IRON CONDOR':>18} {'CALENDAR':>18} {'VERSCHIL':>18}")
    print("-" * 80)

    # Helper for difference calculation
    def diff_str(ic_val: float, cal_val: float, fmt: str = ".1f") -> str:
        diff = ic_val - cal_val
        sign = "+" if diff >= 0 else ""
        return f"IC {sign}{diff:{fmt}}"

    # Rows
    print(f"{'Trades':<20} {ic.trades:>18} {cal.trades:>18} {diff_str(ic.trades, cal.trades, 'd'):>18}")
    print(f"{'Win Rate':<20} {ic.win_rate:>17.1f}% {cal.win_rate:>17.1f}% {diff_str(ic.win_rate, cal.win_rate):>18}")
    print(f"{'Total P&L':<20} ${ic.total_pnl:>16,.2f} ${cal.total_pnl:>16,.2f} {diff_str(ic.total_pnl, cal.total_pnl, ',.0f'):>18}")
    print(f"{'Sharpe':<20} {ic.sharpe:>18.2f} {cal.sharpe:>18.2f} {diff_str(ic.sharpe, cal.sharpe, '.2f'):>18}")
    print(f"{'Max Drawdown':<20} {ic.max_drawdown:>17.1f}% {cal.max_drawdown:>17.1f}% {diff_str(ic.max_drawdown, cal.max_drawdown):>18}")
    print(f"{'Profit Factor':<20} {ic.profit_factor:>18.2f} {cal.profit_factor:>18.2f} {diff_str(ic.profit_factor, cal.profit_factor, '.2f'):>18}")

    # Handle None values
    ic_ret_dd_str = f"{ic.ret_dd:>18.2f}" if ic.ret_dd is not None else f"{'N/A':>18}"
    cal_ret_dd_str = f"{cal.ret_dd:>18.2f}" if cal.ret_dd is not None else f"{'N/A':>18}"
    ret_dd_diff = diff_str(ic.ret_dd, cal.ret_dd, '.2f') if (ic.ret_dd is not None and cal.ret_dd is not None) else "N/A"
    print(f"{'Ret/DD':<20} {ic_ret_dd_str} {cal_ret_dd_str} {ret_dd_diff:>18}")

    # Analysis section
    print("\n" + "-" * 80)
    print("ANALYSE:")

    # Compare key metrics
    if ic.sharpe > cal.sharpe + 0.1:
        print("  Iron Condor heeft betere risk-adjusted returns (hogere Sharpe)")
    elif cal.sharpe > ic.sharpe + 0.1:
        print("  Calendar heeft betere risk-adjusted returns (hogere Sharpe)")
    else:
        print("  Beide strategieen hebben vergelijkbare risk-adjusted returns")

    if ic.win_rate > cal.win_rate + 5:
        print(f"  Iron Condor heeft hogere win rate (+{ic.win_rate - cal.win_rate:.1f}%)")
    elif cal.win_rate > ic.win_rate + 5:
        print(f"  Calendar heeft hogere win rate (+{cal.win_rate - ic.win_rate:.1f}%)")

    if ic.max_drawdown < cal.max_drawdown - 2:
        print("  Iron Condor heeft lagere drawdown (minder risico)")
    elif cal.max_drawdown < ic.max_drawdown - 2:
        print("  Calendar heeft lagere drawdown (minder risico)")

    # Combined performance insight
    print("\n" + "-" * 80)
    print("DIVERSIFICATIE INZICHT:")
    print("  Iron Condor: Beste in HOGE IV omgevingen (premium verkoop)")
    print("  Calendar:    Beste in LAGE IV omgevingen (vol expansie)")
    print("  Samen:       Potentieel stabielere returns door marktdiversificatie")


def _run_backtest_with_config(
    strategy: str,
    overrides: Dict[str, Any],
    label: str,
    show_progress: bool = True,
) -> Optional[TestResult]:
    """Run a backtest with specific configuration overrides."""
    from tomic.backtest.config import load_backtest_config, BacktestConfig
    from tomic.backtest.engine import BacktestEngine

    # Load base config
    try:
        config = load_backtest_config()
    except Exception:
        config = BacktestConfig()

    config.strategy_type = strategy

    # Load live strategy config for all parameters
    live_config = load_live_config()

    # Apply strike selection rules (DTE range)
    strike_rules = live_config.get("strike_selection_rules", {})
    default_strike = strike_rules.get("default", {})
    strategy_strike = strike_rules.get(strategy, {})

    dte_range = overrides.get("dte_range") or strategy_strike.get("dte_range") or default_strike.get("dte_range")
    if dte_range and len(dte_range) >= 2:
        # Use midpoint of DTE range as target_dte
        config.target_dte = (dte_range[0] + dte_range[1]) // 2
        # Store DTE range for filtering
        config.entry_rules.dte_min = dte_range[0]
        config.entry_rules.dte_max = dte_range[1]

    # Apply volatility rules to entry criteria
    vol_rules = live_config.get("volatility_rules", {})
    strategy_vol = vol_rules.get(strategy, {})
    criteria = strategy_vol.get("criteria", [])

    for criterion in criteria:
        if isinstance(criterion, str):
            parsed = _parse_vol_criterion(criterion)
            if parsed:
                field = parsed["field"]
                value = parsed["value"]
                op = parsed["operator"]

                # Check for overrides first
                override_key = f"vol_{field}"
                if override_key in overrides:
                    value = overrides[override_key]

                # Map volatility rules to entry_rules
                if field == "iv_rank" and op in (">=", ">"):
                    # iv_rank is 0-1 in rules, but entry_rules uses 0-100 scale
                    config.entry_rules.iv_rank_min = value * 100 if value < 1 else value
                elif field == "iv_percentile" and op in (">=", ">"):
                    # iv_percentile is 0-1 in rules, but entry_rules uses 0-100 scale
                    config.entry_rules.iv_percentile_min = value * 100 if value < 1 else value
                elif field == "skew" and op == "<=":
                    config.entry_rules.skew_max = value
                elif field == "skew" and op == ">=":
                    config.entry_rules.skew_min = value
                elif field == "iv_vs_hv20" and op == ">":
                    config.entry_rules.iv_hv_spread_min = value

    # Apply manual overrides to entry/exit rules (these take precedence)
    if "iv_percentile_min" in overrides:
        config.entry_rules.iv_percentile_min = overrides["iv_percentile_min"]
    if "profit_target_pct" in overrides:
        config.exit_rules.profit_target_pct = overrides["profit_target_pct"]
    if "stop_loss_pct" in overrides:
        config.exit_rules.stop_loss_pct = overrides["stop_loss_pct"]
    if "max_days_in_trade" in overrides:
        config.exit_rules.max_days_in_trade = int(overrides["max_days_in_trade"])

    # Get effective min_risk_reward (override or live config)
    min_rr = overrides.get(
        "min_risk_reward",
        get_strategy_param(live_config, strategy, "min_risk_reward", 1.0)
    )

    # Get stddev_range from overrides or config (override takes precedence)
    stddev_range = overrides.get("stddev_range") or strategy_strike.get("stddev_range")

    # Get delta_range from overrides or config
    delta_range = (
        overrides.get("delta_range")
        or strategy_strike.get("short_delta_range")
        or strategy_strike.get("delta_range")
    )

    # Store strategy-specific config
    strategy_overrides = {
        "min_risk_reward": min_rr,
        "min_rom": overrides.get(
            "min_rom",
            get_strategy_param(live_config, strategy, "min_rom")
        ),
        "min_edge": overrides.get(
            "min_edge",
            get_strategy_param(live_config, strategy, "min_edge")
        ),
        "min_pos": overrides.get(
            "min_pos",
            get_strategy_param(live_config, strategy, "min_pos")
        ),
        # Include strike selection for reference
        "dte_range": dte_range,
        "stddev_range": stddev_range,
        "delta_range": delta_range,
    }

    # Create engine with strategy config
    engine = BacktestEngine(config=config, strategy_config=strategy_overrides)

    print(f"\nBacktest: {label}")
    print(f"Periode: {config.start_date} tot {config.end_date}")

    # Run
    try:
        if show_progress and RICH_AVAILABLE:
            console = Console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initialiseren...", total=100)

                def update(msg: str, pct: float) -> None:
                    progress.update(task, description=msg, completed=pct)

                engine.progress_callback = update
                bt_result = engine.run()
        else:
            # Track last printed percentage to avoid duplicate output
            last_printed = [-1]

            def simple(msg: str, pct: float) -> None:
                # Print at 10% intervals (0, 10, 20, ..., 100)
                threshold = int(pct / 10) * 10
                if threshold > last_printed[0]:
                    print(f"[{int(pct)}%] {msg}")
                    last_printed[0] = threshold

            engine.progress_callback = simple
            bt_result = engine.run()

        # Convert to TestResult
        if bt_result and bt_result.combined_metrics:
            m = bt_result.combined_metrics
            return TestResult(
                config_label=label,
                param_value=None,
                trades=m.total_trades,
                win_rate=m.win_rate * 100,
                total_pnl=m.total_pnl,
                sharpe=m.sharpe_ratio,
                max_drawdown=m.max_drawdown_pct,
                profit_factor=m.profit_factor,
                ret_dd=m.ret_dd,
                degradation=bt_result.degradation_score or 0,
                backtest_result=bt_result,  # Keep full result for detailed views
            )
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        print(f"\nFout tijdens backtest: {e}")

    return None


def _print_single_result(result: TestResult) -> None:
    """Print a single backtest result."""
    print("\n" + "=" * 60)
    print(f"RESULTAAT: {result.config_label}")
    print("=" * 60)

    print(f"\n  Trades:         {result.trades}")
    print(f"  Win Rate:       {result.win_rate:.1f}%")
    print(f"  Total P&L:      ${result.total_pnl:,.2f}")
    print(f"  Sharpe Ratio:   {result.sharpe:.2f}")
    print(f"  Max Drawdown:   {result.max_drawdown:.1f}%")
    print(f"  Profit Factor:  {result.profit_factor:.2f}")
    ret_dd_str = f"{result.ret_dd:.2f}" if result.ret_dd is not None else "N/A"
    print(f"  Ret/DD:         {ret_dd_str}")
    degradation_str = f"{result.degradation:.1f}%" if result.degradation is not None else "N/A"
    print(f"  Degradation:    {degradation_str}")


# =============================================================================
# Mode 2: What-If Analysis
# =============================================================================


def _parse_parameter_value(value_str: str, current_value: Any) -> Any:
    """Parse a string value to match the type of the current value.

    Handles:
    - float: "1.5" -> 1.5
    - int: "45" -> 45
    - list of int: "20, 60" -> [20, 60]
    - list of float: "0.15, 0.35" -> [0.15, 0.35]

    Args:
        value_str: String input from user
        current_value: Current parameter value (used to determine target type)

    Returns:
        Parsed value in the correct type, or None if parsing fails.

    Raises:
        ValueError: If parsing fails with a specific error message.
    """
    value_str = value_str.strip()

    # Handle list types (e.g., dte_range, delta_range)
    if isinstance(current_value, list):
        # Split on comma and strip whitespace
        parts = [p.strip() for p in value_str.split(",")]
        if len(parts) < 2:
            raise ValueError(f"Verwacht minimaal 2 waarden gescheiden door komma (bijv. '{current_value[0]}, {current_value[1]}')")

        # Determine element type from current value
        if current_value and isinstance(current_value[0], int):
            try:
                return [int(p) for p in parts]
            except ValueError:
                raise ValueError("Alle waarden moeten gehele getallen zijn")
        else:
            try:
                return [float(p) for p in parts]
            except ValueError:
                raise ValueError("Alle waarden moeten getallen zijn")

    # Handle simple types
    if isinstance(current_value, float):
        try:
            return float(value_str)
        except ValueError:
            raise ValueError("Verwacht een decimaal getal")

    if isinstance(current_value, int):
        try:
            return int(value_str)
        except ValueError:
            raise ValueError("Verwacht een geheel getal")

    # Default: return as string
    return value_str


def run_whatif_analysis() -> None:
    """Test impact of changing a single parameter."""
    print("\n" + "=" * 70)
    print("WHAT-IF ANALYSE")
    print("=" * 70)
    print("\nTest de impact van het wijzigen van een enkele parameter.")

    # Select strategy
    strategy = _select_strategy_for_testing()
    if strategy is None:
        return

    strategy_name = STRATEGY_DISPLAY_NAMES.get(strategy, strategy)
    params = get_testable_parameters(strategy)

    # Show current config
    print("\n" + "-" * 50)
    print("HUIDIGE LIVE CONFIG")
    print("-" * 50)

    for i, p in enumerate(params, 1):
        print(f"  {i:2}. {p['description']:30} = {p['current_value']}")

    # Select parameter
    print("\n" + "-" * 50)
    choice = prompt("Welke parameter wil je testen? [nummer]: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(params):
            selected_param = params[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # Get new value
    current = selected_param["current_value"]
    print(f"\nParameter: {selected_param['description']}")
    print(f"Huidige waarde: {current}")

    new_value_str = prompt("Nieuwe waarde om te testen: ")
    if not new_value_str:
        return

    try:
        new_value = _parse_parameter_value(new_value_str, current)
        if new_value is None:
            print("Ongeldige waarde.")
            return
    except ValueError as e:
        print(f"Ongeldige waarde: {e}")
        return

    # Confirm
    print(f"\nVergelijking: {selected_param['key']}")
    print(f"  Baseline: {current}")
    print(f"  What-If:  {new_value}")

    if not prompt_yes_no("\nVergelijking starten?"):
        return

    # Run baseline and what-if in parallel for better performance
    print("\n" + "=" * 50)
    print("BASELINE & WHAT-IF DRAAIEN PARALLEL...")
    print("=" * 50)

    def run_baseline():
        return _run_backtest_with_config(
            strategy=strategy,
            overrides={},
            label=f"Baseline ({selected_param['key']}={current})",
            show_progress=False,
        )

    def run_whatif():
        return _run_backtest_with_config(
            strategy=strategy,
            overrides={selected_param["key"]: new_value},
            label=f"What-If ({selected_param['key']}={new_value})",
            show_progress=False,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        baseline_future = executor.submit(run_baseline)
        whatif_future = executor.submit(run_whatif)

        baseline = baseline_future.result()
        whatif = whatif_future.result()

    print("Beide backtests voltooid.")

    if not baseline:
        print("Baseline backtest mislukt.")
        return

    baseline.is_baseline = True
    baseline.param_value = current

    if not whatif:
        print("What-If backtest mislukt.")
        return

    whatif.param_value = new_value

    # Show comparison
    comparison = ComparisonResult(
        baseline=baseline,
        whatif=whatif,
        param_name=selected_param["key"],
        param_old_value=current,
        param_new_value=new_value,
    )

    _print_comparison(comparison)

    # Offer to apply
    if prompt_yes_no("\nWijziging doorvoeren naar live config?"):
        _apply_parameter_change(selected_param, new_value)


def _print_comparison(comparison: ComparisonResult) -> None:
    """Print a comparison between baseline and what-if."""
    b = comparison.baseline
    w = comparison.whatif

    print("\n" + "=" * 75)
    print(f"VERGELIJKING: {comparison.param_name}")
    print("=" * 75)

    # Calculate differences
    def diff_str(old: float, new: float, fmt: str = ".1f", pct: bool = False) -> str:
        diff = new - old
        sign = "+" if diff >= 0 else ""
        if pct:
            return f"{sign}{diff:{fmt}}%"
        return f"{sign}{diff:{fmt}}"

    def diff_pct(old: float, new: float) -> str:
        if old == 0:
            return "N/A"
        pct = ((new - old) / abs(old)) * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    # Header
    print(f"\n{'Metric':<20} {'BASELINE':>15} {'WHAT-IF':>15} {'VERSCHIL':>15}")
    print(f"{'':20} {f'({comparison.param_old_value})':>15} {f'({comparison.param_new_value})':>15}")
    print("-" * 75)

    # Rows
    print(f"{'Trades':<20} {b.trades:>15} {w.trades:>15} {diff_str(b.trades, w.trades, 'd'):>15}")
    print(f"{'Win Rate':<20} {b.win_rate:>14.1f}% {w.win_rate:>14.1f}% {diff_str(b.win_rate, w.win_rate):>15}")
    print(f"{'Total P&L':<20} ${b.total_pnl:>13,.2f} ${w.total_pnl:>13,.2f} {diff_pct(b.total_pnl, w.total_pnl):>15}")
    print(f"{'Sharpe':<20} {b.sharpe:>15.2f} {w.sharpe:>15.2f} {diff_str(b.sharpe, w.sharpe, '.2f'):>15}")
    print(f"{'Max Drawdown':<20} {b.max_drawdown:>14.1f}% {w.max_drawdown:>14.1f}% {diff_str(b.max_drawdown, w.max_drawdown):>15}")
    print(f"{'Profit Factor':<20} {b.profit_factor:>15.2f} {w.profit_factor:>15.2f} {diff_str(b.profit_factor, w.profit_factor, '.2f'):>15}")
    # Handle None values for ret_dd
    b_ret_dd_str = f"{b.ret_dd:>15.2f}" if b.ret_dd is not None else f"{'N/A':>15}"
    w_ret_dd_str = f"{w.ret_dd:>15.2f}" if w.ret_dd is not None else f"{'N/A':>15}"
    ret_dd_diff = diff_str(b.ret_dd, w.ret_dd, '.2f') if (b.ret_dd is not None and w.ret_dd is not None) else "N/A"
    print(f"{'Ret/DD':<20} {b_ret_dd_str} {w_ret_dd_str} {ret_dd_diff:>15}")
    # Handle None values for degradation
    b_deg_str = f"{b.degradation:>14.1f}%" if b.degradation is not None else f"{'N/A':>15}"
    w_deg_str = f"{w.degradation:>14.1f}%" if w.degradation is not None else f"{'N/A':>15}"
    deg_diff = diff_str(b.degradation, w.degradation) if (b.degradation is not None and w.degradation is not None) else "N/A"
    print(f"{'Degradation':<20} {b_deg_str} {w_deg_str} {deg_diff:>15}")

    # Analysis
    print("\n" + "-" * 75)
    print("ANALYSE:")

    trade_change = ((w.trades - b.trades) / b.trades * 100) if b.trades > 0 else 0
    sharpe_change = w.sharpe - b.sharpe

    if trade_change > 10:
        print(f"  + Meer trades ({trade_change:+.1f}%)")
    elif trade_change < -10:
        print(f"  - Minder trades ({trade_change:+.1f}%)")

    if sharpe_change > 0.1:
        print(f"  + Betere risk-adjusted returns (Sharpe {sharpe_change:+.2f})")
    elif sharpe_change < -0.1:
        print(f"  - Slechtere risk-adjusted returns (Sharpe {sharpe_change:+.2f})")

    if w.win_rate > b.win_rate + 1:
        print(f"  + Hogere win rate (+{w.win_rate - b.win_rate:.1f}%)")
    elif w.win_rate < b.win_rate - 1:
        print(f"  - Lagere win rate ({w.win_rate - b.win_rate:.1f}%)")

    if w.max_drawdown > b.max_drawdown + 1:
        print(f"  ! Hogere drawdown (+{w.max_drawdown - b.max_drawdown:.1f}%)")


def _apply_parameter_change(param: Dict[str, Any], new_value: Any, strategy: str = "iron_condor") -> None:
    """Apply a parameter change to the live configuration."""
    from pathlib import Path
    from tomic.config import _BASE_DIR

    try:
        import yaml
    except ImportError:
        print("PyYAML is vereist voor het opslaan van configuratie.")
        return

    source = param["source"]
    key = param["key"]

    if source == "strategies.yaml":
        path = _BASE_DIR / "config" / "strategies.yaml"
        _update_yaml_value(path, ["strategies", strategy, key], new_value)
    elif source == "backtest.yaml":
        path = _BASE_DIR / "config" / "backtest.yaml"
        if param["category"] == "entry":
            _update_yaml_value(path, ["entry_rules", key], new_value)
        else:
            _update_yaml_value(path, ["exit_rules", key], new_value)
    elif source == "backtest_calendar.yaml":
        path = _BASE_DIR / "config" / "backtest_calendar.yaml"
        if param["category"] == "entry":
            _update_yaml_value(path, ["entry_rules", key], new_value)
        else:
            _update_yaml_value(path, ["exit_rules", key], new_value)
    elif source == "strike_selection_rules.yaml":
        path = _BASE_DIR / "tomic" / "strike_selection_rules.yaml"
        _update_yaml_value(path, [strategy, key], new_value)
    elif source == "volatility_rules.yaml":
        path = _BASE_DIR / "tomic" / "volatility_rules.yaml"
        _update_volatility_rule(path, strategy, param, new_value)
    else:
        print(f"\n⚠ Onbekende bron: {source} - wijziging niet opgeslagen")
        return

    # Clear config cache so next load picks up the changes
    clear_config_cache()

    print(f"\n✓ Parameter '{key}' bijgewerkt naar {new_value} in {source}")


def _update_yaml_value(path: "Path", keys: List[str], value: Any) -> None:
    """Update a value in a YAML file."""
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Navigate to the right location
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    current[keys[-1]] = value

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _update_volatility_rule(path: "Path", strategy: str, param: Dict[str, Any], new_value: Any) -> None:
    """Update a volatility rule criterion in volatility_rules.yaml.

    The volatility_rules.yaml is a list of dictionaries with 'key' and 'criteria'.
    Criteria are strings like 'iv_rank >= 0.6'.
    """
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []

    if not isinstance(data, list):
        print("Onverwacht formaat in volatility_rules.yaml")
        return

    # Find the strategy entry
    strategy_entry = None
    for entry in data:
        if entry.get("key") == strategy:
            strategy_entry = entry
            break

    if not strategy_entry:
        print(f"Strategie '{strategy}' niet gevonden in volatility_rules.yaml")
        return

    # Get the field and operator from param
    field = param.get("field")
    operator = param.get("operator", ">=")

    if not field:
        print("Geen veld informatie beschikbaar voor volatility rule")
        return

    # Update or add the criterion
    criteria = strategy_entry.get("criteria", [])
    new_criterion = f"{field} {operator} {new_value}"

    # Find and replace existing criterion for this field
    updated = False
    for i, criterion in enumerate(criteria):
        if isinstance(criterion, str) and criterion.strip().startswith(field):
            criteria[i] = new_criterion
            updated = True
            break

    if not updated:
        criteria.append(new_criterion)

    strategy_entry["criteria"] = criteria

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


# =============================================================================
# Mode 3: Parameter Sweep
# =============================================================================


def run_parameter_sweep() -> None:
    """Find optimal value for a parameter by testing multiple values."""
    print("\n" + "=" * 70)
    print("PARAMETER SWEEP")
    print("=" * 70)
    print("\nVind de optimale waarde voor een parameter door meerdere waarden te testen.")

    # Select strategy
    strategy = _select_strategy_for_testing()
    if strategy is None:
        return

    strategy_name = STRATEGY_DISPLAY_NAMES.get(strategy, strategy)
    params = get_testable_parameters(strategy)

    # Show parameters
    print("\n" + "-" * 50)
    print("BESCHIKBARE PARAMETERS")
    print("-" * 50)

    for i, p in enumerate(params, 1):
        print(f"  {i:2}. {p['description']:30} [huidig: {p['current_value']}]")

    # Select parameter
    choice = prompt("\nWelke parameter wil je sweepen? [nummer]: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(params):
            selected_param = params[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # Get range
    current = selected_param["current_value"]
    print(f"\nParameter: {selected_param['description']}")
    print(f"Huidige waarde: {current}")

    # Suggest default ranges based on parameter
    key = selected_param["key"]
    if key == "min_risk_reward":
        default_range = "0.8, 1.0, 1.2, 1.4, 1.5, 1.6, 1.8, 2.0"
    elif key == "iv_percentile_min":
        default_range = "50, 55, 60, 65, 70, 75, 80"
    elif key == "profit_target_pct":
        default_range = "30, 40, 50, 60, 70, 80"
    elif key == "stop_loss_pct":
        default_range = "75, 100, 125, 150, 200"
    else:
        default_range = ""

    range_str = prompt(f"Waarden (komma-gescheiden) [{default_range}]: ") or default_range
    if not range_str:
        print("Geen waarden opgegeven.")
        return

    try:
        if isinstance(current, float):
            values = [float(v.strip()) for v in range_str.split(",")]
        elif isinstance(current, int):
            values = [int(v.strip()) for v in range_str.split(",")]
        else:
            values = [v.strip() for v in range_str.split(",")]
    except ValueError:
        print("Ongeldige waarden.")
        return

    # Confirm
    print(f"\nSweep: {selected_param['key']}")
    print(f"Waarden: {values}")
    print(f"Aantal tests: {len(values)}")

    if not prompt_yes_no("\nSweep starten?"):
        return

    # Run sweep - use parallel processing for better performance
    results: List[TestResult] = []

    # Determine number of workers - optimized for multi-core systems
    # Use up to 16 workers (or half of available cores) for parallel backtests
    cpu_count = os.cpu_count() or 4
    max_workers = min(16, cpu_count // 2 + 4, len(values))

    def run_single_backtest(value: Any) -> Optional[Tuple[Any, TestResult]]:
        """Run a single backtest for a parameter value."""
        try:
            result = _run_backtest_with_config(
                strategy=strategy,
                overrides={selected_param["key"]: value},
                label=f"{selected_param['key']}={value}",
                show_progress=False,
            )
            if result:
                result.param_value = value
                result.is_baseline = (value == current)
                return (value, result)
        except Exception as e:
            logger.error(f"Backtest failed for {selected_param['key']}={value}: {e}")
        return None

    # Run backtests in parallel
    if len(values) > 1 and max_workers > 1:
        print(f"\nDraait {len(values)} backtests parallel (max {max_workers} workers)...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_value = {
                executor.submit(run_single_backtest, value): value
                for value in values
            }

            # Process results as they complete
            completed = 0
            for future in as_completed(future_to_value):
                completed += 1
                value = future_to_value[future]
                print(f"  [{completed}/{len(values)}] {selected_param['key']}={value} voltooid")

                result_tuple = future.result()
                if result_tuple:
                    _, result = result_tuple
                    results.append(result)
    else:
        # Sequential fallback for single value
        for i, value in enumerate(values):
            print(f"\n[{i+1}/{len(values)}] Testen {selected_param['key']} = {value}")
            result_tuple = run_single_backtest(value)
            if result_tuple:
                _, result = result_tuple
                results.append(result)

    if not results:
        print("\nGeen resultaten verkregen.")
        return

    # Show results
    _print_sweep_results(results, selected_param, current)

    # Offer to apply best
    best = max(results, key=lambda r: r.sharpe)
    if best.param_value != current:
        if prompt_yes_no(f"\nWil je {selected_param['key']}={best.param_value} doorvoeren?"):
            _apply_parameter_change(selected_param, best.param_value)


def _print_sweep_results(
    results: List[TestResult],
    param: Dict[str, Any],
    current_value: Any,
) -> None:
    """Print parameter sweep results."""
    # Sort by Sharpe (descending)
    sorted_results = sorted(results, key=lambda r: r.sharpe, reverse=True)

    print("\n" + "=" * 90)
    print(f"SWEEP RESULTATEN: {param['key']} (gesorteerd op Sharpe)")
    print("=" * 90)

    # Header
    print(f"\n  {'Value':>8} {'Trades':>8} {'Win%':>8} {'P&L':>12} {'Sharpe':>8} {'MaxDD':>8} {'PF':>8} {'Ret/DD':>8}")
    print("-" * 90)

    # Find best Sharpe
    best_sharpe = max(r.sharpe for r in results)

    for r in sorted_results:
        marker = ""
        if r.sharpe == best_sharpe:
            marker = " *"  # Best
        if r.param_value == current_value:
            marker = " <"  # Current

        ret_dd_str = f"{r.ret_dd:>8.2f}" if r.ret_dd is not None else f"{'N/A':>8}"
        print(
            f"  {r.param_value:>8} "
            f"{r.trades:>8} "
            f"{r.win_rate:>7.1f}% "
            f"${r.total_pnl:>10,.0f} "
            f"{r.sharpe:>8.2f} "
            f"{r.max_drawdown:>7.1f}% "
            f"{r.profit_factor:>8.2f} "
            f"{ret_dd_str}"
            f"{marker}"
        )

    print("\n  * = beste Sharpe    < = huidige config")

    # Recommendations
    best = sorted_results[0]
    current_result = next((r for r in results if r.param_value == current_value), None)

    if current_result and best.param_value != current_value:
        print("\n" + "-" * 90)
        print("AANBEVELING:")
        improvement = ((best.sharpe - current_result.sharpe) / current_result.sharpe) * 100
        print(f"  {param['key']}={best.param_value} geeft {improvement:+.1f}% betere Sharpe ratio")
        print(f"  ({current_result.sharpe:.2f} -> {best.sharpe:.2f})")


# =============================================================================
# Mode 4: Custom Experiment
# =============================================================================


def run_custom_experiment() -> None:
    """Run a custom backtest with manual configuration."""
    print("\n" + "=" * 70)
    print("CUSTOM EXPERIMENT")
    print("=" * 70)
    print("\nVrij experimenteren met losse configuratie.")

    # Import backtest UI with strategy selection
    from tomic.cli.backtest_ui import (
        _select_strategy,
        run_iron_condor_backtest,
        run_calendar_backtest,
        run_both_backtests,
        STRATEGY_IRON_CONDOR as BT_IC,
        STRATEGY_CALENDAR as BT_CAL,
    )

    strategy = _select_strategy()

    if strategy is None:
        return
    elif strategy == BT_IC:
        run_iron_condor_backtest()
    elif strategy == BT_CAL:
        run_calendar_backtest()
    elif strategy == "both":
        run_both_backtests()


# =============================================================================
# Results Storage
# =============================================================================


_STORED_RESULTS: Dict[str, List[TestResult]] = {}
_SYMBOL_STRATEGY_METRICS: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}  # category -> symbol -> strategy -> metrics
_RESULTS_FILE = Path("tomic/data/test_results.json")


def _test_result_to_dict(result: TestResult) -> Dict[str, Any]:
    """Convert TestResult to a JSON-serializable dict."""
    data = {
        "config_label": result.config_label,
        "param_value": result.param_value,
        "trades": result.trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "sharpe": result.sharpe,
        "max_drawdown": result.max_drawdown,
        "profit_factor": result.profit_factor,
        "ret_dd": result.ret_dd,
        "degradation": result.degradation,
        "is_baseline": result.is_baseline,
        # Note: full backtest_result is not serialized (too complex)
    }

    # Extract per-symbol-per-strategy metrics if backtest_result is available
    if result.backtest_result is not None and result.backtest_result.trades:
        symbol_strategy_metrics = _extract_symbol_strategy_metrics(result.backtest_result.trades)
        if symbol_strategy_metrics:
            data["symbol_strategy_metrics"] = symbol_strategy_metrics

    return data


def _extract_symbol_strategy_metrics(trades: List[Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Extract per-symbol-per-strategy metrics from trades for persistence."""
    from collections import defaultdict

    # Group by symbol and strategy
    by_symbol: Dict[str, Dict[str, List[Any]]] = defaultdict(lambda: {"iron_condor": [], "calendar": []})

    for trade in trades:
        if hasattr(trade, 'status') and trade.status.value == "closed":
            by_symbol[trade.symbol][trade.strategy_type].append(trade)

    # Calculate metrics for each group
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for symbol, strategies in by_symbol.items():
        result[symbol] = {}
        for strategy_type, strategy_trades in strategies.items():
            if strategy_trades:
                winners = [t for t in strategy_trades if t.final_pnl > 0]
                total_pnl = sum(t.final_pnl for t in strategy_trades)
                result[symbol][strategy_type] = {
                    "trades": len(strategy_trades),
                    "win_rate": len(winners) / len(strategy_trades),
                    "total_pnl": total_pnl,
                    "avg_pnl": total_pnl / len(strategy_trades),
                }

    return result


def _dict_to_test_result(d: Dict[str, Any]) -> TestResult:
    """Convert a dict back to TestResult."""
    return TestResult(
        config_label=d["config_label"],
        param_value=d["param_value"],
        trades=d["trades"],
        win_rate=d["win_rate"],
        total_pnl=d["total_pnl"],
        sharpe=d["sharpe"],
        max_drawdown=d["max_drawdown"],
        profit_factor=d["profit_factor"],
        ret_dd=d.get("ret_dd"),
        degradation=d.get("degradation"),
        is_baseline=d.get("is_baseline", False),
        backtest_result=None,  # Cannot restore full backtest result
    )


def _save_results() -> None:
    """Persist stored results to JSON file."""
    global _STORED_RESULTS, _SYMBOL_STRATEGY_METRICS
    if not _STORED_RESULTS:
        return

    # Convert to serializable format
    data = {
        "version": 2,
        "saved_at": datetime.now().isoformat(),
        "results": {
            category: [_test_result_to_dict(r) for r in results]
            for category, results in _STORED_RESULTS.items()
        },
        "symbol_strategy_metrics": _SYMBOL_STRATEGY_METRICS,
    }

    # Ensure directory exists
    _RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    logger.info(f"Test resultaten opgeslagen naar {_RESULTS_FILE}")


def _load_results() -> bool:
    """Load stored results from JSON file.

    Returns:
        True if results were loaded, False if no file exists.
    """
    global _STORED_RESULTS, _SYMBOL_STRATEGY_METRICS

    if not _RESULTS_FILE.exists():
        return False

    try:
        with open(_RESULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert back to TestResult objects
        _STORED_RESULTS = {
            category: [_dict_to_test_result(d) for d in results]
            for category, results in data.get("results", {}).items()
        }

        # Load symbol-strategy metrics (version 2+)
        _SYMBOL_STRATEGY_METRICS = data.get("symbol_strategy_metrics", {})

        # Also extract from individual results if available (backward compatibility)
        for category, results_dicts in data.get("results", {}).items():
            for d in results_dicts:
                if "symbol_strategy_metrics" in d:
                    if category not in _SYMBOL_STRATEGY_METRICS:
                        _SYMBOL_STRATEGY_METRICS[category] = {}
                    # Merge metrics
                    for symbol, strategies in d["symbol_strategy_metrics"].items():
                        if symbol not in _SYMBOL_STRATEGY_METRICS[category]:
                            _SYMBOL_STRATEGY_METRICS[category][symbol] = {}
                        _SYMBOL_STRATEGY_METRICS[category][symbol].update(strategies)

        saved_at = data.get("saved_at", "onbekend")
        logger.info(f"Test resultaten geladen van {_RESULTS_FILE} (opgeslagen: {saved_at})")
        return True

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Kon test resultaten niet laden: {e}")
        return False


def _clear_persisted_results() -> None:
    """Clear persisted results file."""
    global _STORED_RESULTS, _SYMBOL_STRATEGY_METRICS
    _STORED_RESULTS = {}
    _SYMBOL_STRATEGY_METRICS = {}
    if _RESULTS_FILE.exists():
        _RESULTS_FILE.unlink()
        print("Opgeslagen resultaten gewist.")
    else:
        print("Geen opgeslagen resultaten om te wissen.")


def _store_result(category: str, result: TestResult) -> None:
    """Store a result for later viewing.

    Also updates backtest_ui._LAST_RESULT so the result can be viewed
    via the backtest menu's "Resultaten bekijken" submenu.
    Results are automatically persisted to disk.
    """
    global _SYMBOL_STRATEGY_METRICS

    if category not in _STORED_RESULTS:
        _STORED_RESULTS[category] = []
    _STORED_RESULTS[category].append(result)

    # Share with backtest_ui for cross-menu access
    if result.backtest_result is not None:
        import tomic.cli.backtest_ui as backtest_ui
        backtest_ui._LAST_RESULT = result.backtest_result

        # Extract and store symbol-strategy metrics for persistence
        if result.backtest_result.trades:
            metrics = _extract_symbol_strategy_metrics(result.backtest_result.trades)
            if metrics:
                if category not in _SYMBOL_STRATEGY_METRICS:
                    _SYMBOL_STRATEGY_METRICS[category] = {}
                # Merge with existing
                for symbol, strategies in metrics.items():
                    if symbol not in _SYMBOL_STRATEGY_METRICS[category]:
                        _SYMBOL_STRATEGY_METRICS[category][symbol] = {}
                    _SYMBOL_STRATEGY_METRICS[category][symbol].update(strategies)

    # Persist to disk
    _save_results()


def view_results() -> None:
    """View stored test results via submenu."""
    global _STORED_RESULTS

    # Try to load from disk if memory is empty
    if not _STORED_RESULTS:
        _load_results()

    if not _STORED_RESULTS:
        print("\nGeen opgeslagen resultaten.")
        print("Voer eerst een test uit.")
        return

    menu = Menu("RESULTATEN BEKIJKEN")
    menu.add("Samenvatting", _view_results_summary)
    menu.add("Per-symbool overzicht", _view_results_symbol_table)
    menu.add("Per-symbool per strategie (IC/Cal)", _view_results_by_strategy)
    menu.add("Volledig rapport", _view_results_full_report)
    menu.add("Resultaten wissen", _clear_persisted_results)
    menu.run()


def _view_results_summary() -> None:
    """Show summary of all stored results."""
    print("\n" + "=" * 70)
    print("OPGESLAGEN RESULTATEN")
    print("=" * 70)

    for category, results in _STORED_RESULTS.items():
        print(f"\n{category}:")
        for r in results:
            print(f"  - {r.config_label}: Sharpe {r.sharpe:.2f}, P&L ${r.total_pnl:,.0f}")


def _view_results_symbol_table() -> None:
    """Show per-symbol performance table for the last result."""
    # Find the most recent result with a backtest_result
    last_result = None
    for results in _STORED_RESULTS.values():
        for r in reversed(results):
            if r.backtest_result is not None:
                last_result = r
                break
        if last_result:
            break

    if not last_result or not last_result.backtest_result:
        print("\nGeen gedetailleerde resultaten beschikbaar.")
        return

    from tomic.backtest.reports import BacktestReport
    report = BacktestReport(last_result.backtest_result)
    report.print_symbol_performance_table()


def _view_results_full_report() -> None:
    """Show full backtest report for the last result."""
    last_result = None
    for results in _STORED_RESULTS.values():
        for r in reversed(results):
            if r.backtest_result is not None:
                last_result = r
                break
        if last_result:
            break

    if not last_result or not last_result.backtest_result:
        print("\nGeen gedetailleerde resultaten beschikbaar.")
        return

    from tomic.backtest.reports import print_backtest_report
    print_backtest_report(last_result.backtest_result)


def _view_results_by_strategy() -> None:
    """Show per-symbol performance split by strategy type (IC vs Calendar)."""
    # Collect all backtest results from stored results
    ic_result = None
    cal_result = None

    # Look for separate IC and Calendar results first (from memory)
    if "live_validation_ic" in _STORED_RESULTS:
        for r in reversed(_STORED_RESULTS["live_validation_ic"]):
            if r.backtest_result is not None:
                ic_result = r.backtest_result
                break

    if "live_validation_cal" in _STORED_RESULTS:
        for r in reversed(_STORED_RESULTS["live_validation_cal"]):
            if r.backtest_result is not None:
                cal_result = r.backtest_result
                break

    # If found in memory, use the full backtest results
    if ic_result is not None or cal_result is not None:
        _print_strategy_comparison_table(ic_result, cal_result)
        return

    # If not found in memory, try to get from a combined result with trades
    for category, results in _STORED_RESULTS.items():
        for r in reversed(results):
            if r.backtest_result is not None and r.backtest_result.trades:
                # Check if trades have mixed strategy types
                strategy_types = {t.strategy_type for t in r.backtest_result.trades}
                if len(strategy_types) > 1 or strategy_types:
                    # Use this result and split by strategy type
                    _print_strategy_breakdown_from_trades(r.backtest_result.trades)
                    return

    # Fallback: Use persisted symbol-strategy metrics
    if _SYMBOL_STRATEGY_METRICS:
        _print_strategy_breakdown_from_persisted_metrics()
        return

    print("\nGeen gedetailleerde resultaten beschikbaar.")
    print("Voer eerst een backtest uit met 'Beide' strategieen.")


def _print_strategy_breakdown_from_trades(trades: List[Any]) -> None:
    """Print per-symbol breakdown from mixed trades."""
    from collections import defaultdict

    # Split trades by symbol and strategy
    by_symbol: Dict[str, Dict[str, List[Any]]] = defaultdict(lambda: {"iron_condor": [], "calendar": []})

    for trade in trades:
        if trade.status.value == "closed":
            by_symbol[trade.symbol][trade.strategy_type].append(trade)

    if not by_symbol:
        print("\nGeen gesloten trades beschikbaar.")
        return

    _print_combined_strategy_table(by_symbol)


def _print_strategy_comparison_table(ic_result: Optional[Any], cal_result: Optional[Any]) -> None:
    """Print comparison table from separate IC and Calendar results."""
    from collections import defaultdict

    # Build per-symbol metrics from both results
    by_symbol: Dict[str, Dict[str, List[Any]]] = defaultdict(lambda: {"iron_condor": [], "calendar": []})

    if ic_result and ic_result.trades:
        for trade in ic_result.trades:
            if trade.status.value == "closed":
                by_symbol[trade.symbol]["iron_condor"].append(trade)

    if cal_result and cal_result.trades:
        for trade in cal_result.trades:
            if trade.status.value == "closed":
                by_symbol[trade.symbol]["calendar"].append(trade)

    if not by_symbol:
        print("\nGeen gesloten trades beschikbaar.")
        return

    _print_combined_strategy_table(by_symbol)


def _print_strategy_breakdown_from_persisted_metrics() -> None:
    """Print per-symbol breakdown from persisted metrics (no trades in memory)."""
    # Combine metrics from all categories
    combined_by_symbol: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for category, symbols in _SYMBOL_STRATEGY_METRICS.items():
        for symbol, strategies in symbols.items():
            if symbol not in combined_by_symbol:
                combined_by_symbol[symbol] = {"iron_condor": None, "calendar": None}

            for strategy_type, metrics in strategies.items():
                # Use the most recent metrics for this symbol/strategy
                combined_by_symbol[symbol][strategy_type] = metrics

    if not combined_by_symbol:
        print("\nGeen opgeslagen per-symbool metrics beschikbaar.")
        return

    # Build symbol_data for the table
    symbol_data = []
    for symbol in sorted(combined_by_symbol.keys()):
        ic_metrics = combined_by_symbol[symbol].get("iron_condor") or {
            "trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0
        }
        cal_metrics = combined_by_symbol[symbol].get("calendar") or {
            "trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0
        }

        # Calculate total
        total_trades = ic_metrics["trades"] + cal_metrics["trades"]
        total_pnl = ic_metrics["total_pnl"] + cal_metrics["total_pnl"]

        total_metrics = {
            "trades": total_trades,
            "win_rate": 0.0,  # Can't calculate without individual trade data
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / total_trades if total_trades > 0 else 0.0,
        }

        symbol_data.append({
            "symbol": symbol,
            "ic": ic_metrics,
            "cal": cal_metrics,
            "total": total_metrics,
        })

    # Sort by total P&L descending
    symbol_data.sort(key=lambda x: x["total"]["total_pnl"], reverse=True)

    print("\n" + "=" * 100)
    print("PER-SYMBOOL STRATEGIE OVERZICHT (van opgeslagen resultaten)")
    print("=" * 100)

    if RICH_AVAILABLE:
        _print_rich_strategy_table(symbol_data)
    else:
        _print_plain_strategy_table(symbol_data)


def _calculate_metrics_for_trades(trades: List[Any]) -> Dict[str, Any]:
    """Calculate basic metrics for a list of trades."""
    if not trades:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
        }

    winners = [t for t in trades if t.final_pnl > 0]
    total_pnl = sum(t.final_pnl for t in trades)

    return {
        "trades": len(trades),
        "win_rate": len(winners) / len(trades) if trades else 0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / len(trades) if trades else 0,
    }


def _print_combined_strategy_table(by_symbol: Dict[str, Dict[str, List[Any]]]) -> None:
    """Print combined table showing IC, Calendar, and Total per symbol."""
    print("\n" + "=" * 100)
    print("PER-SYMBOOL STRATEGIE OVERZICHT")
    print("=" * 100)

    # Calculate totals per symbol
    symbol_data = []
    for symbol in sorted(by_symbol.keys()):
        ic_trades = by_symbol[symbol]["iron_condor"]
        cal_trades = by_symbol[symbol]["calendar"]
        all_trades = ic_trades + cal_trades

        ic_metrics = _calculate_metrics_for_trades(ic_trades)
        cal_metrics = _calculate_metrics_for_trades(cal_trades)
        total_metrics = _calculate_metrics_for_trades(all_trades)

        symbol_data.append({
            "symbol": symbol,
            "ic": ic_metrics,
            "cal": cal_metrics,
            "total": total_metrics,
        })

    # Sort by total P&L descending
    symbol_data.sort(key=lambda x: x["total"]["total_pnl"], reverse=True)

    if RICH_AVAILABLE:
        _print_rich_strategy_table(symbol_data)
    else:
        _print_plain_strategy_table(symbol_data)


def _print_rich_strategy_table(symbol_data: List[Dict[str, Any]]) -> None:
    """Print strategy comparison table with Rich formatting."""
    console = Console()

    console.print()
    console.print(
        Panel(
            "[bold]Per-symbool strategie vergelijking[/bold]\n"
            "[dim]IC = Iron Condor | Cal = Calendar | Gesorteerd op Total P&L[/dim]",
            border_style="blue",
        )
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("IC #", justify="right")
    table.add_column("IC Win%", justify="right")
    table.add_column("IC P&L", justify="right")
    table.add_column("Cal #", justify="right")
    table.add_column("Cal Win%", justify="right")
    table.add_column("Cal P&L", justify="right")
    table.add_column("Total #", justify="right")
    table.add_column("Total P&L", justify="right", style="bold")

    # Totals
    total_ic_trades = 0
    total_ic_pnl = 0.0
    total_cal_trades = 0
    total_cal_pnl = 0.0
    total_all_trades = 0
    total_all_pnl = 0.0

    for row in symbol_data:
        ic = row["ic"]
        cal = row["cal"]
        total = row["total"]

        # Accumulate totals
        total_ic_trades += ic["trades"]
        total_ic_pnl += ic["total_pnl"]
        total_cal_trades += cal["trades"]
        total_cal_pnl += cal["total_pnl"]
        total_all_trades += total["trades"]
        total_all_pnl += total["total_pnl"]

        # Colors
        ic_color = "green" if ic["total_pnl"] > 0 else "red" if ic["total_pnl"] < 0 else "white"
        cal_color = "green" if cal["total_pnl"] > 0 else "red" if cal["total_pnl"] < 0 else "white"
        total_color = "green" if total["total_pnl"] > 0 else "red" if total["total_pnl"] < 0 else "white"

        table.add_row(
            row["symbol"],
            str(ic["trades"]) if ic["trades"] > 0 else "-",
            f"{ic['win_rate']:.0%}" if ic["trades"] > 0 else "-",
            f"[{ic_color}]${ic['total_pnl']:,.0f}[/{ic_color}]" if ic["trades"] > 0 else "-",
            str(cal["trades"]) if cal["trades"] > 0 else "-",
            f"{cal['win_rate']:.0%}" if cal["trades"] > 0 else "-",
            f"[{cal_color}]${cal['total_pnl']:,.0f}[/{cal_color}]" if cal["trades"] > 0 else "-",
            str(total["trades"]),
            f"[{total_color}]${total['total_pnl']:,.0f}[/{total_color}]",
        )

    # Add totals row
    ic_total_color = "green" if total_ic_pnl > 0 else "red"
    cal_total_color = "green" if total_cal_pnl > 0 else "red"
    all_total_color = "green" if total_all_pnl > 0 else "red"

    table.add_row(
        "[bold]TOTAAL[/bold]",
        f"[bold]{total_ic_trades}[/bold]",
        "",
        f"[bold {ic_total_color}]${total_ic_pnl:,.0f}[/bold {ic_total_color}]",
        f"[bold]{total_cal_trades}[/bold]",
        "",
        f"[bold {cal_total_color}]${total_cal_pnl:,.0f}[/bold {cal_total_color}]",
        f"[bold]{total_all_trades}[/bold]",
        f"[bold {all_total_color}]${total_all_pnl:,.0f}[/bold {all_total_color}]",
        style="on grey23",
    )

    console.print(table)
    console.print()


def _print_plain_strategy_table(symbol_data: List[Dict[str, Any]]) -> None:
    """Print strategy comparison table without Rich (fallback)."""
    header = (
        f"{'Symbol':<8} {'IC #':>5} {'IC Win%':>8} {'IC P&L':>10} "
        f"{'Cal #':>5} {'Cal Win%':>8} {'Cal P&L':>10} "
        f"{'Total #':>7} {'Total P&L':>12}"
    )
    print(header)
    print("-" * 100)

    total_ic_trades = 0
    total_ic_pnl = 0.0
    total_cal_trades = 0
    total_cal_pnl = 0.0
    total_all_trades = 0
    total_all_pnl = 0.0

    for row in symbol_data:
        ic = row["ic"]
        cal = row["cal"]
        total = row["total"]

        total_ic_trades += ic["trades"]
        total_ic_pnl += ic["total_pnl"]
        total_cal_trades += cal["trades"]
        total_cal_pnl += cal["total_pnl"]
        total_all_trades += total["trades"]
        total_all_pnl += total["total_pnl"]

        ic_str = f"{ic['trades']:>5} {ic['win_rate']:>7.0%} ${ic['total_pnl']:>9,.0f}" if ic["trades"] > 0 else "    -        -          -"
        cal_str = f"{cal['trades']:>5} {cal['win_rate']:>7.0%} ${cal['total_pnl']:>9,.0f}" if cal["trades"] > 0 else "    -        -          -"

        print(f"{row['symbol']:<8} {ic_str} {cal_str} {total['trades']:>7} ${total['total_pnl']:>11,.0f}")

    print("-" * 100)
    print(
        f"{'TOTAAL':<8} {total_ic_trades:>5}          ${total_ic_pnl:>9,.0f} "
        f"{total_cal_trades:>5}          ${total_cal_pnl:>9,.0f} "
        f"{total_all_trades:>7} ${total_all_pnl:>11,.0f}"
    )
    print()


def configure_test_settings() -> None:
    """Configure test settings (period, symbols, etc.)."""
    from tomic.cli.backtest_ui import _configure_with_strategy_choice
    _configure_with_strategy_choice()


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    "run_strategy_testing_menu",
    "run_live_config_validation",
    "run_whatif_analysis",
    "run_parameter_sweep",
    "run_custom_experiment",
    "run_external_validation_export",
    "load_live_config",
    "get_testable_parameters",
]
