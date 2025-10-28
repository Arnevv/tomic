import textwrap
import importlib
import textwrap

import pytest

from tomic import config
from tomic.core.config import strike_selection as selection_config


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


def test_load_selection_config_with_strategies_yaml(tmp_path):
    pytest.importorskip("yaml")
    yaml_path = tmp_path / "strike_selection_rules.yaml"
    _write_yaml_with_strategies(yaml_path)

    cfg = selection_config.reload(yaml_path)
    rules = cfg.for_strategy("s1").model_dump()
    assert rules["enabled"] is False
    assert rules["flags"] == ["C"]
    assert rules["nested"]["threshold"]["min"] == 10

    fallback = cfg.for_strategy("unknown").model_dump()
    assert fallback["enabled"] is True


def test_load_selection_config_with_flat_yaml(tmp_path):
    pytest.importorskip("yaml")
    yaml_path = tmp_path / "strike_selection_rules.yaml"
    _write_flat_yaml(yaml_path)

    cfg = selection_config.reload(yaml_path)
    rules = cfg.for_strategy("s1").model_dump()
    assert rules["enabled"] is False
    assert rules["flags"] == ["C"]
    assert rules["nested"]["threshold"]["min"] == 10

    fallback = cfg.for_strategy("unknown").model_dump()
    assert fallback["enabled"] is True


