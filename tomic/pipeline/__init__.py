"""Pipeline configuration module.

Provides unified access to all pipeline parameters across multiple config files.
"""

from tomic.pipeline.parameter_registry import (
    ParameterRegistry,
    PipelinePhase,
    StrategyConfig,
    ParameterSource,
    get_registry,
)
from tomic.pipeline.presets import (
    PresetManager,
    Preset,
    get_preset_manager,
)

__all__ = [
    "ParameterRegistry",
    "PipelinePhase",
    "StrategyConfig",
    "ParameterSource",
    "get_registry",
    "PresetManager",
    "Preset",
    "get_preset_manager",
]
