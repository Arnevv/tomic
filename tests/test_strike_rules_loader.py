import textwrap
import importlib
from tomic import config, loader
import pytest


def _write_yaml_with_strategies(path):
    path.write_text(
        textwrap.dedent(
            """
            default:
              enabled: true
              flags:
                - A
                - B
              nested:
                threshold:
                  min: 5
            strategies:
              s1:
                enabled: false
                flags:
                  - C
                nested:
                  threshold:
                    min: 10
            """
        )
    )


def _write_flat_yaml(path):
    path.write_text(
        textwrap.dedent(
            """
            default:
              enabled: true
              flags:
                - A
                - B
              nested:
                threshold:
                  min: 5
            s1:
              enabled: false
              flags:
                - C
              nested:
                threshold:
                  min: 10
            """
        )
    )


def test_yaml_loader_parses_nested_structures(tmp_path):
    pytest.importorskip("yaml")
    yaml_path = tmp_path / "strike_selection_rules.yaml"
    _write_yaml_with_strategies(yaml_path)

    data = config._load_yaml(yaml_path)
    assert data["default"]["enabled"] is True
    assert data["default"]["flags"] == ["A", "B"]
    assert data["default"]["nested"]["threshold"]["min"] == 5
    assert data["strategies"]["s1"]["enabled"] is False


def test_load_strike_config_with_strategies_yaml(tmp_path):
    pytest.importorskip("yaml")
    yaml_path = tmp_path / "strike_selection_rules.yaml"
    _write_yaml_with_strategies(yaml_path)

    data = config._load_yaml(yaml_path)
    result = loader.load_strike_config("s1", data)
    assert result["enabled"] is False
    assert result["flags"] == ["C"]
    assert result["nested"]["threshold"]["min"] == 10

    result = loader.load_strike_config("unknown", data)
    assert result["enabled"] is True


def test_load_strike_config_with_flat_yaml(tmp_path):
    pytest.importorskip("yaml")
    yaml_path = tmp_path / "strike_selection_rules.yaml"
    _write_flat_yaml(yaml_path)

    data = config._load_yaml(yaml_path)
    result = loader.load_strike_config("s1", data)
    assert result["enabled"] is False
    assert result["flags"] == ["C"]
    assert result["nested"]["threshold"]["min"] == 10

    result = loader.load_strike_config("unknown", data)
    assert result["enabled"] is True


