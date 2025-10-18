from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tomic.earnings.import_flow import (
    build_import_plan,
    preview_changes,
    summarise_changes,
    apply_import,
)


class StubRuntime:
    def __init__(self, overrides: dict[str, object]):
        self._overrides = overrides

    def load(self):
        return self

    def get(self, path: str, default: object | None = None) -> object | None:
        return self._overrides.get(path, default)


def test_import_plan_and_apply(tmp_path, monkeypatch):
    csv_path = tmp_path / "earnings.csv"
    csv_path.write_text("Symbol,Next Earnings\nABC,2099-02-01\n")

    json_path = tmp_path / "earnings.json"
    json_path.write_text(json.dumps({"ABC": ["2099-01-01"]}))

    overrides = {
        "earnings_import.symbol_col": "Symbol",
        "earnings_import.next_col_candidates": ["Next Earnings"],
        "earnings_import.today_override": "2099-01-01",
        "data.earnings_json_path": str(json_path),
    }
    runtime = StubRuntime(overrides)
    cfg_stub = SimpleNamespace(get=lambda key, default=None: default)

    plan = build_import_plan(csv_path, runtime_config_module=runtime, cfg_module=cfg_stub)
    assert plan.csv_map
    assert plan.json_path == json_path

    changes = preview_changes(plan)
    assert len(changes) == 1
    summary = summarise_changes(changes)
    assert summary["total"] == 1

    updated, backup_path = apply_import(plan)
    assert isinstance(updated, dict)
    saved = json.loads(json_path.read_text())
    assert saved["ABC"][0] == "2099-02-01"
    assert backup_path is None or isinstance(backup_path, Path)
