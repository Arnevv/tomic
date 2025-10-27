from __future__ import annotations

import json
import importlib
from datetime import date
from pathlib import Path

import pytest

from tomic.api.earnings_importer import (
    parse_earnings_csv,
    update_next_earnings,
)


def test_parse_csv_formats(tmp_path: Path) -> None:
    csv_path = tmp_path / "mc.csv"
    csv_path.write_text(
        "Symbol,Next Earnings ,Notes\n"
        "AAPL,10/30/2025,Quarterly\n"
        "msft,2025-11-01,Inline\n",
        encoding="utf-8",
    )

    result = parse_earnings_csv(str(csv_path))

    assert result == {
        "AAPL": "2025-10-30",
        "MSFT": "2025-11-01",
    }


def test_replace_and_insert_logic() -> None:
    today = date(2025, 9, 1)
    json_data = {
        "AAPL": ["2025-09-15", "2025-10-05", "2025-10-20", "2025-11-01"],
        "MSFT": ["2025-01-01", "2025-02-01"],
    }
    csv_map = {
        "AAPL": "2025-10-12",
        "MSFT": "2025-04-10",
        "TSLA": "2025-08-08",
    }

    updated, changes = update_next_earnings(json_data, csv_map, today=today, dry_run=True)

    assert updated["AAPL"] == ["2025-10-12", "2025-11-01"]
    assert updated["MSFT"] == ["2025-01-01", "2025-02-01", "2025-04-10"]
    assert updated["TSLA"] == ["2025-08-08"]

    change_map = {entry["symbol"]: entry for entry in changes}
    assert change_map["AAPL"]["action"] == "replaced_closest_future"
    assert change_map["AAPL"]["removed_same_month"] >= 2
    assert change_map["MSFT"]["action"] == "inserted_as_next"
    assert change_map["TSLA"]["action"] == "created_symbol"


def test_no_change_when_csv_matches_existing_future() -> None:
    today = date(2025, 10, 1)
    json_data = {
        "AAPL": ["2025-10-30", "2026-01-15"],
    }
    csv_map = {
        "AAPL": "2025-10-30",
    }

    updated, changes = update_next_earnings(json_data, csv_map, today=today, dry_run=True)

    assert updated["AAPL"] == ["2025-10-30", "2026-01-15"]
    assert changes == []


def test_cli_dry_run_and_confirm_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_cfg_path = tmp_path / "runtime.yaml"
    monkeypatch.setenv("TOMIC_RUNTIME_CONFIG", str(runtime_cfg_path))
    runtime_config = importlib.import_module("tomic.core.config")
    importlib.reload(runtime_config)

    csv_path = tmp_path / "mc.csv"
    csv_path.write_text("Symbol,Next Earnings\nAAPL,2025-10-30\n", encoding="utf-8")

    json_path = tmp_path / "earnings.json"
    json_path.write_text(json.dumps({"AAPL": ["2025-09-15"]}), encoding="utf-8")

    cli_module = importlib.import_module("tomic.cli.import_earnings")
    monkeypatch.setattr(cli_module, "setup_logging", lambda stdout=True: None)

    # Dry-run should not modify the JSON file.
    exit_code = cli_module.main(
        [
            "--csv",
            str(csv_path),
            "--json",
            str(json_path),
            "--today",
            "2025-09-01",
        ]
    )
    assert exit_code == 0
    data_after_dry = json.loads(json_path.read_text(encoding="utf-8"))
    assert data_after_dry["AAPL"] == ["2025-09-15"]

    # Apply run should update JSON and create a backup.
    exit_code = cli_module.main(
        [
            "--csv",
            str(csv_path),
            "--json",
            str(json_path),
            "--today",
            "2025-09-01",
            "--apply",
        ]
    )
    assert exit_code == 0
    data_final = json.loads(json_path.read_text(encoding="utf-8"))
    assert data_final["AAPL"] == ["2025-10-30"]

    backups = list(json_path.parent.glob("earnings.json.*.bak"))
    assert backups, "Backup bestand ontbreekt"

    out = capsys.readouterr().out
    assert "Wijzigingen opgeslagen" in out
