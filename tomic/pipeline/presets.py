"""Preset management for pipeline configurations.

Allows saving and loading complete pipeline configurations as presets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil

from tomic.logutils import logger


@dataclass
class Preset:
    """A saved pipeline configuration preset."""
    name: str
    description: str
    strategy_key: str
    created_at: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    backtest_results: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "Preset":
        """Create preset from dictionary."""
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            strategy_key=data.get("strategy_key", "iron_condor"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            parameters=data.get("parameters", {}),
            backtest_results=data.get("backtest_results"),
        )

    def to_dict(self) -> Dict:
        """Convert preset to dictionary."""
        return asdict(self)


class PresetManager:
    """Manages saving, loading, and organizing presets."""

    def __init__(self, presets_dir: Optional[Path] = None):
        """Initialize the preset manager.

        Args:
            presets_dir: Directory to store presets. Defaults to config/presets/
        """
        if presets_dir is None:
            base_path = Path(__file__).resolve().parent.parent.parent
            presets_dir = base_path / "config" / "presets"

        self.presets_dir = Path(presets_dir)
        self.presets_dir.mkdir(parents=True, exist_ok=True)

    def save(self, preset: Preset) -> Path:
        """Save a preset to disk.

        Args:
            preset: The preset to save.

        Returns:
            Path to the saved preset file.
        """
        # Create safe filename
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in preset.name
        )
        filename = f"{safe_name}_{preset.strategy_key}.json"
        filepath = self.presets_dir / filename

        # Backup existing if present
        if filepath.exists():
            backup_path = filepath.with_suffix(".json.bak")
            shutil.copy(filepath, backup_path)

        # Save
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(preset.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Preset saved: {filepath}")
        return filepath

    def load(self, name: str, strategy_key: Optional[str] = None) -> Optional[Preset]:
        """Load a preset by name.

        Args:
            name: Preset name or filename.
            strategy_key: Optional strategy filter.

        Returns:
            The loaded preset, or None if not found.
        """
        # Try exact filename first
        if name.endswith(".json"):
            filepath = self.presets_dir / name
            if filepath.exists():
                return self._load_file(filepath)

        # Search by name
        for preset in self.list_all():
            if preset.name == name:
                if strategy_key is None or preset.strategy_key == strategy_key:
                    return preset

        return None

    def _load_file(self, filepath: Path) -> Optional[Preset]:
        """Load a preset from a specific file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return Preset.from_dict(data)
        except Exception as e:
            logger.error(f"Error loading preset {filepath}: {e}")
            return None

    def list_all(self) -> List[Preset]:
        """List all saved presets."""
        presets = []
        for filepath in sorted(self.presets_dir.glob("*.json")):
            if filepath.suffix == ".json" and not filepath.name.endswith(".bak"):
                preset = self._load_file(filepath)
                if preset:
                    presets.append(preset)
        return presets

    def list_for_strategy(self, strategy_key: str) -> List[Preset]:
        """List presets for a specific strategy."""
        return [p for p in self.list_all() if p.strategy_key == strategy_key]

    def delete(self, name: str) -> bool:
        """Delete a preset by name.

        Returns True if deleted, False if not found.
        """
        for filepath in self.presets_dir.glob("*.json"):
            preset = self._load_file(filepath)
            if preset and preset.name == name:
                filepath.unlink()
                logger.info(f"Preset deleted: {filepath}")
                return True
        return False

    def create_from_registry(
        self,
        name: str,
        description: str,
        strategy_key: str,
        registry: "ParameterRegistry",
    ) -> Preset:
        """Create a preset from current registry state.

        Args:
            name: Name for the preset.
            description: Description.
            strategy_key: Strategy to capture.
            registry: The parameter registry to read from.

        Returns:
            The created preset (not yet saved).
        """
        from tomic.pipeline.parameter_registry import ParameterRegistry

        strategy_config = registry.get_strategy(strategy_key)
        if not strategy_config:
            raise ValueError(f"Unknown strategy: {strategy_key}")

        # Collect all parameters
        parameters = {}
        for phase_key, phase_params in strategy_config.phases.items():
            parameters[phase_key.value] = {
                name: source.value
                for name, source in phase_params.parameters.items()
            }

        return Preset(
            name=name,
            description=description,
            strategy_key=strategy_key,
            created_at=datetime.now().isoformat(),
            parameters=parameters,
        )

    def apply_to_registry(
        self,
        preset: Preset,
        registry: "ParameterRegistry",
    ) -> Dict[str, bool]:
        """Apply a preset's parameters to the registry.

        Args:
            preset: The preset to apply.
            registry: The registry to update.

        Returns:
            Dict mapping parameter names to success status.
        """
        from tomic.pipeline.parameter_registry import PipelinePhase

        results = {}
        strategy_key = preset.strategy_key

        for phase_name, params in preset.parameters.items():
            try:
                phase = PipelinePhase(phase_name)
            except ValueError:
                continue

            for param_name, value in params.items():
                success = registry.update_parameter(
                    strategy_key, phase, param_name, value
                )
                results[f"{phase_name}.{param_name}"] = success

        return results


# Singleton instance
_preset_manager: Optional[PresetManager] = None


def get_preset_manager() -> PresetManager:
    """Get the global preset manager instance."""
    global _preset_manager
    if _preset_manager is None:
        _preset_manager = PresetManager()
    return _preset_manager
