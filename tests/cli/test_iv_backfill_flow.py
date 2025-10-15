from __future__ import annotations

import csv
import json
from math import isclose
from pathlib import Path
from typing import Iterator

import pytest
from pytest import CaptureFixture

from tomic.cli import iv_backfill_flow


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = ["Date", "IV30", "IV30 20-Day MA", "OHLC 20-Day Vol", "OHLC 52-Week Vol", "Options Volume"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_read_iv_csv_parses_dates_and_iv(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    _write_csv(
        csv_path,
        [
            {
                "Date": "2024-01-02",
                "IV30": "45.5",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "01/03/2024",
                "IV30": "50",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
        ],
    )

    result = iv_backfill_flow.read_iv_csv(csv_path)

    assert [row["date"] for row in result.records] == ["2024-01-02", "2024-01-03"]
    assert isclose(result.records[0]["atm_iv"], 0.455)
    assert isclose(result.records[1]["atm_iv"], 0.50)
    assert result.duplicates == []
    assert result.invalid_dates == []
    assert result.empty_rows == 0


def test_read_iv_csv_flags_duplicates_and_invalid_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    _write_csv(
        csv_path,
        [
            {
                "Date": "2024-01-02",
                "IV30": "45.5",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "2024-01-02",
                "IV30": "46",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "03-01-2024",
                "IV30": "",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "bad-date",
                "IV30": "42",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
        ],
    )

    result = iv_backfill_flow.read_iv_csv(csv_path)

    assert [row["date"] for row in result.records] == ["2024-01-02"]
    assert result.duplicates == ["2024-01-02"]
    assert result.invalid_dates == ["bad-date"]
    # One row was dropped due to missing IV30 value
    assert result.empty_rows == 1


def test_read_iv_csv_requires_expected_headers(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("Date,Other\n2024-01-02,40\n")

    with pytest.raises(ValueError, match="Ontbrekende kolommen"):
        iv_backfill_flow.read_iv_csv(path)


def test_run_iv_backfill_flow_previews_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    csv_path = tmp_path / "input.csv"
    _write_csv(
        csv_path,
        [
            {"Date": "2024-01-01", "IV30": "45", "IV30 20-Day MA": "", "OHLC 20-Day Vol": "", "OHLC 52-Week Vol": "", "Options Volume": ""},
            {"Date": "2024-01-02", "IV30": "65", "IV30 20-Day MA": "", "OHLC 20-Day Vol": "", "OHLC 52-Week Vol": "", "Options Volume": ""},
        ],
    )

    summary_dir = tmp_path / "summary"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    summary_dir.mkdir()
    hv_dir.mkdir()
    spot_dir.mkdir()

    summary_file = summary_dir / "AAPL.json"
    summary_file.write_text(json.dumps([{"date": "2023-12-31", "atm_iv": 0.40}, {"date": "2024-01-02", "atm_iv": 0.40}]), encoding="utf-8")

    (hv_dir / "AAPL.json").write_text(json.dumps([{"date": "2024-01-01", "hv20": 0.3}]), encoding="utf-8")
    (spot_dir / "AAPL.json").write_text(json.dumps([{"date": "2024-01-01", "close": 100}]), encoding="utf-8")

    responses: Iterator[str] = iter(["AAPL", str(csv_path)])
    monkeypatch.setattr(iv_backfill_flow, "prompt", lambda _: next(responses))
    monkeypatch.setattr(iv_backfill_flow, "prompt_yes_no", lambda _: True)

    paths = {
        "IV_SUMMARY_DIR": str(summary_dir),
        "HV_DIR": str(hv_dir),
        "SPOT_DIR": str(spot_dir),
    }

    def fake_get(key: str, default: str | None = None) -> str | None:
        return paths.get(key, default)

    monkeypatch.setattr(iv_backfill_flow.cfg, "get", fake_get)

    iv_backfill_flow.run_iv_backfill_flow()

    captured = capsys.readouterr().out
    assert "Voorbeeld wijzigingen:" in captured
    assert "Samenvatting:" in captured
    assert "⚠️ HV ontbreekt" in captured
    assert "⚠️ Spotdata ontbreekt" in captured
    assert "✅ IV backfill opgeslagen" in captured
    assert "Backup aangemaakt" in captured

    merged = json.loads(summary_file.read_text(encoding="utf-8"))
    assert [row["date"] for row in merged] == ["2023-12-31", "2024-01-01", "2024-01-02"]
    assert isclose(merged[-1]["atm_iv"], 0.65)

    backup = summary_file.with_suffix(".json.bak")
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8")) == [
        {"date": "2023-12-31", "atm_iv": 0.40},
        {"date": "2024-01-02", "atm_iv": 0.40},
    ]
