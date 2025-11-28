"""Tests for the Presets module."""

import pytest
from pathlib import Path
import tempfile
import shutil
import json

from tomic.pipeline.presets import (
    Preset,
    PresetManager,
    get_preset_manager,
)
from tomic.pipeline.parameter_registry import (
    get_registry,
    PipelinePhase,
)


class TestPreset:
    """Tests for Preset dataclass."""

    def test_from_dict(self):
        """Test creating preset from dictionary."""
        data = {
            "name": "test_preset",
            "description": "A test preset",
            "strategy_key": "iron_condor",
            "created_at": "2024-01-01T00:00:00",
            "parameters": {"market_selection": {"criterion_1": "iv_rank >= 0.5"}},
        }

        preset = Preset.from_dict(data)

        assert preset.name == "test_preset"
        assert preset.description == "A test preset"
        assert preset.strategy_key == "iron_condor"
        assert preset.parameters["market_selection"]["criterion_1"] == "iv_rank >= 0.5"

    def test_to_dict(self):
        """Test converting preset to dictionary."""
        preset = Preset(
            name="test",
            description="desc",
            strategy_key="calendar",
            created_at="2024-01-01",
            parameters={"scoring": {"min_rom": 0.1}},
        )

        data = preset.to_dict()

        assert data["name"] == "test"
        assert data["strategy_key"] == "calendar"
        assert data["parameters"]["scoring"]["min_rom"] == 0.1

    def test_from_dict_with_defaults(self):
        """Test from_dict uses defaults for missing fields."""
        data = {"name": "minimal"}
        preset = Preset.from_dict(data)

        assert preset.name == "minimal"
        assert preset.strategy_key == "iron_condor"  # default
        assert preset.description == ""  # default
        assert preset.parameters == {}  # default


class TestPresetManager:
    """Tests for PresetManager class."""

    @pytest.fixture
    def temp_presets_dir(self):
        """Create a temporary directory for presets."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_save_and_load(self, temp_presets_dir):
        """Test saving and loading a preset."""
        manager = PresetManager(temp_presets_dir)

        preset = Preset(
            name="my_preset",
            description="Test preset",
            strategy_key="iron_condor",
            created_at="2024-01-01T00:00:00",
            parameters={"scoring": {"min_rom": 0.15}},
        )

        # Save
        filepath = manager.save(preset)
        assert filepath.exists()
        assert filepath.suffix == ".json"

        # Load
        loaded = manager.load("my_preset")
        assert loaded is not None
        assert loaded.name == "my_preset"
        assert loaded.parameters["scoring"]["min_rom"] == 0.15

    def test_list_all(self, temp_presets_dir):
        """Test listing all presets."""
        manager = PresetManager(temp_presets_dir)

        # Create some presets
        for name in ["preset_a", "preset_b", "preset_c"]:
            preset = Preset(
                name=name,
                description="",
                strategy_key="iron_condor",
                created_at="2024-01-01",
                parameters={},
            )
            manager.save(preset)

        presets = manager.list_all()
        assert len(presets) == 3
        names = [p.name for p in presets]
        assert "preset_a" in names
        assert "preset_b" in names
        assert "preset_c" in names

    def test_list_for_strategy(self, temp_presets_dir):
        """Test listing presets for specific strategy."""
        manager = PresetManager(temp_presets_dir)

        # Create presets for different strategies
        manager.save(Preset("ic_1", "", "iron_condor", "2024-01-01", {}))
        manager.save(Preset("ic_2", "", "iron_condor", "2024-01-01", {}))
        manager.save(Preset("cal_1", "", "calendar", "2024-01-01", {}))

        ic_presets = manager.list_for_strategy("iron_condor")
        assert len(ic_presets) == 2

        cal_presets = manager.list_for_strategy("calendar")
        assert len(cal_presets) == 1

    def test_delete(self, temp_presets_dir):
        """Test deleting a preset."""
        manager = PresetManager(temp_presets_dir)

        preset = Preset("to_delete", "", "iron_condor", "2024-01-01", {})
        manager.save(preset)

        # Verify exists
        assert manager.load("to_delete") is not None

        # Delete
        result = manager.delete("to_delete")
        assert result is True

        # Verify gone
        assert manager.load("to_delete") is None

    def test_delete_nonexistent(self, temp_presets_dir):
        """Test deleting non-existent preset returns False."""
        manager = PresetManager(temp_presets_dir)
        result = manager.delete("nonexistent")
        assert result is False

    def test_load_by_filename(self, temp_presets_dir):
        """Test loading preset by filename."""
        manager = PresetManager(temp_presets_dir)

        preset = Preset("test", "", "iron_condor", "2024-01-01", {})
        filepath = manager.save(preset)

        # Load by filename
        loaded = manager.load(filepath.name)
        assert loaded is not None
        assert loaded.name == "test"

    def test_safe_filename(self, temp_presets_dir):
        """Test that unsafe characters in name are sanitized."""
        manager = PresetManager(temp_presets_dir)

        preset = Preset("test/with\\bad:chars", "", "iron_condor", "2024-01-01", {})
        filepath = manager.save(preset)

        # Should not contain unsafe characters
        assert "/" not in filepath.name
        assert "\\" not in filepath.name
        assert ":" not in filepath.name

    def test_backup_on_overwrite(self, temp_presets_dir):
        """Test that backup is created when overwriting."""
        manager = PresetManager(temp_presets_dir)

        # Save initial preset
        preset = Preset("test", "v1", "iron_condor", "2024-01-01", {"v": 1})
        filepath = manager.save(preset)

        # Overwrite
        preset.description = "v2"
        preset.parameters = {"v": 2}
        manager.save(preset)

        # Backup should exist
        backup = filepath.with_suffix(".json.bak")
        assert backup.exists()

        # Load backup to verify it's the old version
        with open(backup) as f:
            backup_data = json.load(f)
        assert backup_data["description"] == "v1"


class TestPresetManagerWithRegistry:
    """Tests for PresetManager integration with ParameterRegistry."""

    @pytest.fixture
    def temp_presets_dir(self):
        """Create a temporary directory for presets."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_create_from_registry(self, temp_presets_dir):
        """Test creating preset from current registry state."""
        manager = PresetManager(temp_presets_dir)
        registry = get_registry()

        preset = manager.create_from_registry(
            name="snapshot_test",
            description="Test snapshot",
            strategy_key="iron_condor",
            registry=registry,
        )

        assert preset.name == "snapshot_test"
        assert preset.strategy_key == "iron_condor"
        assert len(preset.parameters) > 0

        # Should have market_selection parameters
        assert "market_selection" in preset.parameters or any(
            "market" in k for k in preset.parameters.keys()
        )

    def test_create_from_registry_unknown_strategy(self, temp_presets_dir):
        """Test that unknown strategy raises error."""
        manager = PresetManager(temp_presets_dir)
        registry = get_registry()

        with pytest.raises(ValueError, match="Unknown strategy"):
            manager.create_from_registry(
                name="test",
                description="",
                strategy_key="unknown_strategy",
                registry=registry,
            )


class TestPresetManagerSingleton:
    """Tests for singleton behavior."""

    def test_get_preset_manager_returns_same_instance(self):
        """Test that get_preset_manager returns same instance."""
        m1 = get_preset_manager()
        m2 = get_preset_manager()
        assert m1 is m2
