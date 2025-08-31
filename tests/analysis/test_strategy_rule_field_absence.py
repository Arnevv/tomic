import yaml
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parents[2] / "tomic" / "strike_selection_rules.yaml"


def _load_rules() -> dict:
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_ratio_spread_fields_absent():
    rules = _load_rules()
    cfg = rules.get("ratio_spread", {})
    assert "require_skew" not in cfg
    assert "allow_extra_wings" not in cfg


def test_backspread_put_fields_absent():
    rules = _load_rules()
    cfg = rules.get("backspread_put", {})
    assert "require_term_compression" not in cfg
