"""CLI interface for unified pipeline configuration.

Provides a single view of all pipeline parameters organized by
strategy and phase, with editing and preset management.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import partial
from typing import Optional, List, Dict, Any

from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.pipeline import (
    ParameterRegistry,
    PipelinePhase,
    StrategyConfig,
    get_registry,
    PresetManager,
    Preset,
    get_preset_manager,
)
from tomic.logutils import logger

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Phase display order and colors
PHASE_CONFIG = {
    PipelinePhase.MARKET_SELECTION: {"icon": "🎯", "color": "cyan"},
    PipelinePhase.STRIKE_SELECTION: {"icon": "📍", "color": "yellow"},
    PipelinePhase.SCORING: {"icon": "📊", "color": "green"},
    PipelinePhase.EXIT: {"icon": "🚪", "color": "red"},
    PipelinePhase.PORTFOLIO: {"icon": "💼", "color": "magenta"},
}


def run_pipeline_config_menu() -> None:
    """Run the pipeline configuration submenu."""
    menu = Menu("⚙️  PIPELINE CONFIGURATIE")
    menu.add("Strategie overzicht bekijken", show_strategy_overview)
    menu.add("Alle strategieen vergelijken", compare_all_strategies)
    menu.add("Parameter aanpassen", edit_parameter)
    menu.add("Quick backtest na wijziging", quick_backtest_current)
    menu.add("Preset opslaan", save_preset)
    menu.add("Preset laden", load_preset)
    menu.add("Presets bekijken", list_presets)
    menu.add("Config bestanden tonen", show_config_files)
    menu.add("Configuratie herladen", reload_config)
    menu.run()


def show_strategy_overview() -> None:
    """Show complete configuration for a single strategy."""
    registry = get_registry()
    strategies = registry.list_strategies()

    print("\n" + "=" * 70)
    print("STRATEGIE SELECTEREN")
    print("=" * 70)

    for i, key in enumerate(strategies, 1):
        config = registry.get_strategy(key)
        print(f"{i:2}. {config.strategy_name} ({key})")

    choice = prompt("\nKies strategie nummer: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(strategies):
            strategy_key = strategies[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    _display_strategy_config(strategy_key)

    # Submenu
    while True:
        print("\n[a] Parameter aanpassen  [b] Quick backtest  [s] Preset opslaan  [Enter] Terug")
        action = prompt("Actie: ").lower()

        if not action:
            break
        elif action == "a":
            _edit_strategy_parameter(strategy_key)
            _display_strategy_config(strategy_key)  # Refresh view
        elif action == "b":
            _run_quick_backtest(strategy_key)
        elif action == "s":
            _save_strategy_preset(strategy_key)


def _display_strategy_config(strategy_key: str) -> None:
    """Display complete configuration for a strategy."""
    registry = get_registry()
    config = registry.get_strategy(strategy_key)

    if not config:
        print(f"Strategie niet gevonden: {strategy_key}")
        return

    if RICH_AVAILABLE:
        _display_strategy_rich(config)
    else:
        _display_strategy_plain(config)


def _display_strategy_rich(config: StrategyConfig) -> None:
    """Display strategy config using Rich."""
    console = Console()

    # Header
    header = f"[bold white]{config.strategy_name}[/bold white] ({config.strategy_key})"
    if config.greeks_description:
        header += f"\n[dim]{config.greeks_description}[/dim]"

    console.print(Panel(header, title="Strategie Configuratie", expand=False))

    # Create tables for each phase
    for phase in PipelinePhase:
        phase_params = config.phases.get(phase)
        if not phase_params or not phase_params.parameters:
            continue

        phase_config = PHASE_CONFIG.get(phase, {"icon": "•", "color": "white"})

        table = Table(
            title=f"{phase_config['icon']} {phase.display_name}",
            title_style=f"bold {phase_config['color']}",
            box=box.ROUNDED,
            expand=True,
        )
        table.add_column("Parameter", style="cyan", no_wrap=True)
        table.add_column("Waarde", style="bold")
        table.add_column("Bron", style="dim", no_wrap=True)

        for name, source in sorted(phase_params.items()):
            # Format value
            value_str = _format_value(source.value)

            table.add_row(
                name,
                value_str,
                source.file_name,
            )

        console.print(table)
        console.print()


def _display_strategy_plain(config: StrategyConfig) -> None:
    """Display strategy config in plain text."""
    print("\n" + "=" * 70)
    print(f"STRATEGIE: {config.strategy_name} ({config.strategy_key})")
    if config.greeks_description:
        print(f"Greeks: {config.greeks_description}")
    print("=" * 70)

    for phase in PipelinePhase:
        phase_params = config.phases.get(phase)
        if not phase_params or not phase_params.parameters:
            continue

        phase_config = PHASE_CONFIG.get(phase, {"icon": "•"})
        print(f"\n{phase_config['icon']} {phase.display_name}")
        print("-" * 50)

        for name, source in sorted(phase_params.items()):
            value_str = _format_value(source.value)
            print(f"  {name:30} = {value_str:20} [{source.file_name}]")


def _format_value(value: Any) -> str:
    """Format a parameter value for display."""
    if isinstance(value, bool):
        return "✓" if value else "✗"
    elif isinstance(value, float):
        return f"{value:.4g}"
    elif isinstance(value, list):
        return str(value)
    elif value is None:
        return "[niet ingesteld]"
    return str(value)


def compare_all_strategies() -> None:
    """Show comparison table of all strategies."""
    registry = get_registry()

    print("\n" + "=" * 70)
    print("STRATEGIEEN VERGELIJKING")
    print("=" * 70)

    # Key parameters to compare
    key_params = [
        ("Entry: IV Rank", "market_selection", "criterion_1"),
        ("Entry: IV Pct", "market_selection", "criterion_2"),
        ("Strike: Method", "strike_selection", "method"),
        ("Strike: DTE", "strike_selection", "dte_range"),
        ("Min ROM", "scoring", "min_rom"),
        ("Min Edge", "scoring", "min_edge"),
        ("Min POS", "scoring", "min_pos"),
        ("Min R/R", "scoring", "min_risk_reward"),
    ]

    if RICH_AVAILABLE:
        console = Console()
        table = Table(title="Strategieen Vergelijking", box=box.ROUNDED)
        table.add_column("Strategie", style="bold cyan")

        for label, _, _ in key_params:
            table.add_column(label, justify="center")

        for strategy_key in registry.list_strategies():
            config = registry.get_strategy(strategy_key)
            row = [config.strategy_name[:15]]

            for _, phase_name, param_name in key_params:
                try:
                    phase = PipelinePhase(phase_name)
                    phase_params = config.phases.get(phase)
                    if phase_params:
                        source = phase_params.parameters.get(param_name)
                        if source:
                            row.append(_format_value(source.value)[:15])
                        else:
                            row.append("-")
                    else:
                        row.append("-")
                except Exception:
                    row.append("-")

            table.add_row(*row)

        console.print(table)
    else:
        # Plain text version
        strategies = registry.list_strategies()
        print(f"\n{'Strategie':<18}", end="")
        for label, _, _ in key_params:
            print(f"{label:<12}", end="")
        print()
        print("-" * (18 + len(key_params) * 12))

        for strategy_key in strategies:
            config = registry.get_strategy(strategy_key)
            print(f"{config.strategy_name[:16]:<18}", end="")

            for _, phase_name, param_name in key_params:
                try:
                    phase = PipelinePhase(phase_name)
                    phase_params = config.phases.get(phase)
                    if phase_params:
                        source = phase_params.parameters.get(param_name)
                        if source:
                            print(f"{_format_value(source.value)[:10]:<12}", end="")
                        else:
                            print(f"{'-':<12}", end="")
                    else:
                        print(f"{'-':<12}", end="")
                except Exception:
                    print(f"{'-':<12}", end="")
            print()


def edit_parameter() -> None:
    """Edit a parameter with strategy selection."""
    registry = get_registry()
    strategies = registry.list_strategies()

    print("\n" + "=" * 70)
    print("PARAMETER AANPASSEN")
    print("=" * 70)

    # Select strategy
    for i, key in enumerate(strategies, 1):
        config = registry.get_strategy(key)
        print(f"{i:2}. {config.strategy_name}")

    choice = prompt("\nKies strategie: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(strategies):
            strategy_key = strategies[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    _edit_strategy_parameter(strategy_key)


def _edit_strategy_parameter(strategy_key: str) -> None:
    """Edit a parameter for a specific strategy."""
    registry = get_registry()
    config = registry.get_strategy(strategy_key)

    if not config:
        print(f"Strategie niet gevonden: {strategy_key}")
        return

    # List phases with parameters
    available_phases = [
        phase for phase in PipelinePhase
        if phase in config.phases and config.phases[phase].parameters
    ]

    print("\n" + "-" * 50)
    print("Kies fase:")
    for i, phase in enumerate(available_phases, 1):
        phase_config = PHASE_CONFIG.get(phase, {"icon": "•"})
        print(f"{i}. {phase_config['icon']} {phase.display_name}")

    choice = prompt("\nFase nummer: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(available_phases):
            phase = available_phases[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # List parameters in phase
    phase_params = config.phases[phase]
    param_list = list(phase_params.parameters.items())

    print(f"\nParameters in {phase.display_name}:")
    for i, (name, source) in enumerate(param_list, 1):
        print(f"{i:2}. {name:30} = {_format_value(source.value)}")

    choice = prompt("\nParameter nummer: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(param_list):
            param_name, source = param_list[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # Get new value
    print(f"\nHuidige waarde: {_format_value(source.value)}")
    print(f"Bron bestand: {source.file_name}")
    print(f"YAML pad: {source.yaml_path}")

    new_value_str = prompt("\nNieuwe waarde (Enter = annuleren): ")
    if not new_value_str:
        return

    # Parse new value
    try:
        new_value = _parse_value(new_value_str, type(source.value), original_value=source.value)
    except ValueError as e:
        print(f"Ongeldige waarde: {e}")
        return

    # Confirm
    print(f"\nWijziging: {_format_value(source.value)} -> {_format_value(new_value)}")
    if not prompt_yes_no("Opslaan?"):
        print("Geannuleerd.")
        return

    # Update
    success = registry.update_parameter(strategy_key, phase, param_name, new_value)

    if success:
        print(f"\n✓ Parameter '{param_name}' succesvol aangepast in {source.file_name}")
    else:
        print(f"\n✗ Fout bij opslaan van parameter")


# Pattern to match criterion strings like "iv_rank >= 0.5" or "skew <= 2.0"
_CRITERION_PATTERN = re.compile(r'^(\w+)\s*(>=|<=|>|<|==|!=)\s*(-?[\d.]+)$')


def _is_criterion(value: Any) -> bool:
    """Check if a value is a criterion string (e.g., 'iv_rank >= 0.5')."""
    if not isinstance(value, str):
        return False
    return bool(_CRITERION_PATTERN.match(value.strip()))


def _update_criterion_value(original: str, new_value_str: str) -> str:
    """Update the numeric part of a criterion string.

    If new_value_str is just a number, replace only the number in the criterion.
    If new_value_str is a full criterion, return it as-is.
    """
    new_value_str = new_value_str.strip()

    # If the new value is already a full criterion, return it
    if _CRITERION_PATTERN.match(new_value_str):
        return new_value_str

    # Try to parse as a number
    try:
        # Parse the number (handles both int and float)
        if '.' in new_value_str:
            new_num = float(new_value_str)
        else:
            new_num = int(new_value_str)

        # Extract the variable and operator from the original
        match = _CRITERION_PATTERN.match(original.strip())
        if match:
            var_name, operator, _ = match.groups()
            # Format with appropriate precision
            if isinstance(new_num, float):
                return f"{var_name} {operator} {new_num}"
            else:
                return f"{var_name} {operator} {new_num}"
    except ValueError:
        pass

    # If we can't parse it, return the new value as-is
    return new_value_str


def _parse_value(value_str: str, target_type: type, original_value: Any = None) -> Any:
    """Parse a string value to the target type.

    Args:
        value_str: The new value string entered by the user
        target_type: The expected type based on the current value
        original_value: The original value (used for criterion preservation)
    """
    value_str = value_str.strip()

    # Special handling for criterion strings - preserve the variable and operator
    if original_value is not None and _is_criterion(original_value):
        return _update_criterion_value(original_value, value_str)

    if target_type == bool or value_str.lower() in ("true", "false", "ja", "nee", "yes", "no"):
        return value_str.lower() in ("true", "ja", "yes", "1")

    if target_type == list or value_str.startswith("["):
        # Parse list
        import ast
        return ast.literal_eval(value_str)

    if target_type == float or "." in value_str:
        return float(value_str)

    if target_type == int:
        return int(value_str)

    return value_str


def quick_backtest_current() -> None:
    """Run a quick backtest with current configuration."""
    registry = get_registry()

    # Select strategy
    strategies = registry.list_strategies()
    print("\n" + "=" * 70)
    print("QUICK BACKTEST")
    print("=" * 70)

    for i, key in enumerate(strategies, 1):
        config = registry.get_strategy(key)
        print(f"{i:2}. {config.strategy_name}")

    choice = prompt("\nKies strategie: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(strategies):
            strategy_key = strategies[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    _run_quick_backtest(strategy_key)


def _run_quick_backtest(strategy_key: str) -> None:
    """Run a quick backtest for a strategy."""
    from tomic.backtest.engine import run_backtest
    from tomic.backtest.config import load_backtest_config, BacktestConfig
    from tomic.backtest.reports import print_backtest_report

    print(f"\nQuick backtest voor {strategy_key}...")

    try:
        config = load_backtest_config()
        config.strategy_type = strategy_key
    except Exception:
        config = BacktestConfig()
        config.strategy_type = strategy_key

    # Show config
    print(f"Symbolen: {', '.join(config.symbols)}")
    print(f"Periode: {config.start_date} tot {config.end_date}")

    if not prompt_yes_no("\nBacktest starten?"):
        return

    print("\nBacktest wordt uitgevoerd...\n")

    try:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn

        console = Console()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Initialiseren...", total=100)

            def update(msg: str, pct: float) -> None:
                progress.update(task, description=msg, completed=pct)

            result = run_backtest(config=config, progress_callback=update)
    except ImportError:
        def simple(msg: str, pct: float) -> None:
            if pct % 25 == 0:
                print(f"[{pct:.0f}%] {msg}")

        result = run_backtest(config=config, progress_callback=simple)

    print("\n")
    print_backtest_report(result)

    # Offer to adjust parameters
    if prompt_yes_no("\nWil je parameters aanpassen op basis van de resultaten?"):
        _edit_strategy_parameter(strategy_key)


def save_preset() -> None:
    """Save current configuration as a preset."""
    registry = get_registry()
    strategies = registry.list_strategies()

    print("\n" + "=" * 70)
    print("PRESET OPSLAAN")
    print("=" * 70)

    for i, key in enumerate(strategies, 1):
        config = registry.get_strategy(key)
        print(f"{i:2}. {config.strategy_name}")

    choice = prompt("\nKies strategie: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(strategies):
            strategy_key = strategies[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    _save_strategy_preset(strategy_key)


def _save_strategy_preset(strategy_key: str) -> None:
    """Save preset for a specific strategy."""
    registry = get_registry()
    preset_manager = get_preset_manager()

    name = prompt("Preset naam: ")
    if not name:
        print("Naam is verplicht.")
        return

    description = prompt("Beschrijving (optioneel): ")

    # Create preset
    try:
        preset = preset_manager.create_from_registry(
            name=name,
            description=description,
            strategy_key=strategy_key,
            registry=registry,
        )

        # Save
        filepath = preset_manager.save(preset)
        print(f"\n✓ Preset opgeslagen: {filepath.name}")

    except Exception as e:
        print(f"\n✗ Fout bij opslaan: {e}")


def load_preset() -> None:
    """Load a preset and apply to configuration."""
    preset_manager = get_preset_manager()
    presets = preset_manager.list_all()

    if not presets:
        print("\nGeen presets gevonden.")
        print("Maak eerst een preset aan met 'Preset opslaan'.")
        return

    print("\n" + "=" * 70)
    print("PRESET LADEN")
    print("=" * 70)

    for i, preset in enumerate(presets, 1):
        print(f"{i:2}. {preset.name} ({preset.strategy_key}) - {preset.created_at[:10]}")
        if preset.description:
            print(f"      {preset.description}")

    choice = prompt("\nKies preset nummer: ")
    if not choice:
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(presets):
            preset = presets[idx]
        else:
            print("Ongeldige keuze.")
            return
    except ValueError:
        print("Ongeldige invoer.")
        return

    # Show what will be changed
    print(f"\nPreset: {preset.name}")
    print(f"Strategie: {preset.strategy_key}")
    print(f"Parameters: {sum(len(p) for p in preset.parameters.values())}")

    if not prompt_yes_no("\nPreset toepassen? Dit overschrijft huidige waarden."):
        return

    # Apply
    registry = get_registry()
    results = preset_manager.apply_to_registry(preset, registry)

    success = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)

    print(f"\n✓ {success} parameters toegepast")
    if failed > 0:
        print(f"✗ {failed} parameters konden niet worden toegepast")

    # Reload to verify
    registry.reload()
    print("\nConfiguratie herladen.")


def list_presets() -> None:
    """List all saved presets."""
    preset_manager = get_preset_manager()
    presets = preset_manager.list_all()

    if not presets:
        print("\nGeen presets gevonden.")
        return

    print("\n" + "=" * 70)
    print("OPGESLAGEN PRESETS")
    print("=" * 70)

    if RICH_AVAILABLE:
        console = Console()
        table = Table(title="Presets", box=box.ROUNDED)
        table.add_column("Naam", style="cyan")
        table.add_column("Strategie")
        table.add_column("Datum")
        table.add_column("Beschrijving")

        for preset in presets:
            table.add_row(
                preset.name,
                preset.strategy_key,
                preset.created_at[:10],
                preset.description[:40] if preset.description else "-",
            )

        console.print(table)
    else:
        for preset in presets:
            print(f"\n{preset.name}")
            print(f"  Strategie: {preset.strategy_key}")
            print(f"  Datum: {preset.created_at[:10]}")
            if preset.description:
                print(f"  {preset.description}")

    # Option to delete
    if prompt_yes_no("\nWil je een preset verwijderen?"):
        choice = prompt("Preset naam: ")
        if choice:
            if preset_manager.delete(choice):
                print(f"✓ Preset '{choice}' verwijderd.")
            else:
                print(f"✗ Preset '{choice}' niet gevonden.")


def show_config_files() -> None:
    """Show overview of all configuration files."""
    registry = get_registry()

    print("\n" + "=" * 70)
    print("CONFIGURATIE BESTANDEN")
    print("=" * 70)

    files = [
        ("criteria", "Centrale regels, scoring weights, alerts", "criteria.yaml"),
        ("volatility_rules", "Strategie selectie op basis van volatiliteit", "tomic/volatility_rules.yaml"),
        ("strike_selection", "Strike selectie methodes en ranges", "tomic/strike_selection_rules.yaml"),
        ("strategies", "Per-strategie instellingen (ROM, edge, delta)", "config/strategies.yaml"),
        ("backtest", "Backtest configuratie (entry/exit regels)", "config/backtest.yaml"),
    ]

    for key, description, rel_path in files:
        path = registry.get_file_path(key)
        exists = path.exists() if path else False
        status = "✓" if exists else "✗"

        print(f"\n{status} {rel_path}")
        print(f"   {description}")
        if path and exists:
            import os
            mtime = os.path.getmtime(path)
            mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            print(f"   Laatst gewijzigd: {mtime_str}")


def reload_config() -> None:
    """Reload all configuration from disk."""
    from tomic.pipeline.parameter_registry import reload_registry

    print("\nConfiguratie wordt herladen...")
    reload_registry()
    print("✓ Configuratie herladen van schijf.")


__all__ = [
    "run_pipeline_config_menu",
    "show_strategy_overview",
    "compare_all_strategies",
    "edit_parameter",
    "quick_backtest_current",
    "save_preset",
    "load_preset",
    "list_presets",
    "show_config_files",
    "reload_config",
]
