from __future__ import annotations

import csv
import json
from math import isclose
from pathlib import Path

import pytest

from tomic.analysis.iv_backfill import (
    IVBackfillValidationError,
    build_iv_backfill_report,
    parse_iv_backfill_csv,
)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "Date",
        "IV30",
        "IV30 20-Day MA",
        "OHLC 20-Day Vol",
        "OHLC 52-Week Vol",
        "Options Volume",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_parse_iv_backfill_csv_normalizes_dates_and_iv(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    write_csv(
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
                "IV30": "50%",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
        ],
    )

    result = parse_iv_backfill_csv(csv_path)

    assert [row.date for row in result.rows] == ["2024-01-02", "2024-01-03"]
    assert isclose(result.rows[0].atm_iv, 0.455)
    assert isclose(result.rows[1].atm_iv, 0.5)
    assert result.duplicate_dates == []
    assert result.row_errors == []


def test_parse_iv_backfill_csv_records_duplicates_and_errors(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    write_csv(
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
                "Date": "2024-01-03",
                "IV30": "",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
        ],
    )

    result = parse_iv_backfill_csv(csv_path)

    assert [row.date for row in result.rows] == ["2024-01-02"]
    assert result.duplicate_dates == ["2024-01-02"]
    assert result.row_errors == ["Row 4: missing IV30 value for 2024-01-03"]


def test_parse_iv_backfill_csv_requires_expected_headers(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("Date,IV30\n2024-01-02,40\n")

    with pytest.raises(IVBackfillValidationError):
        parse_iv_backfill_csv(path)


def test_build_iv_backfill_report_highlights_updates_and_support_gaps(tmp_path: Path) -> None:
    csv_path = tmp_path / "input.csv"
    write_csv(
        csv_path,
        [
            {
                "Date": "2024-01-01",
                "IV30": "45",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "2024-01-02",
                "IV30": "65",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
            {
                "Date": "2024-01-03",
                "IV30": "50",
                "IV30 20-Day MA": "",
                "OHLC 20-Day Vol": "",
                "OHLC 52-Week Vol": "",
                "Options Volume": "",
            },
        ],
    )

    summary_dir = tmp_path / "iv"
    summary_dir.mkdir()
    (summary_dir / "AAPL.json").write_text(
        json.dumps(
            [
                {"date": "2023-12-31", "atm_iv": 0.4},
                {"date": "2024-01-02", "atm_iv": 0.5},
            ]
        ),
        encoding="utf-8",
    )

    hv_dir = tmp_path / "hv"
    hv_dir.mkdir()
    (hv_dir / "AAPL.json").write_text(
        json.dumps(
            [
                {"date": "2024-01-01", "hv20": 0.3},
                {"date": "2024-01-02", "hv20": 0.32},
            ]
        ),
        encoding="utf-8",
    )

    spot_dir = tmp_path / "spot"
    spot_dir.mkdir()
    (spot_dir / "AAPL.json").write_text(
        json.dumps(
            [
                {"date": "2024-01-01", "close": 100},
                {"date": "2024-01-03", "close": 102},
            ]
        ),
        encoding="utf-8",
    )

    parse_result = parse_iv_backfill_csv(csv_path)
    report = build_iv_backfill_report(
        "AAPL",
        parse_result,
        summary_dir=summary_dir,
        hv_dir=hv_dir,
        spot_dir=spot_dir,
        diff_threshold=0.03,
    )

    assert [row.date for row in report.new_rows] == ["2024-01-01", "2024-01-03"]
    assert [upd.date for upd in report.updated_rows] == ["2024-01-02"]
    assert isclose(report.updated_rows[0].abs_diff, 0.15)
    assert report.unchanged_dates == []
    assert report.existing_only_dates == ["2023-12-31"]
    assert report.support_status.missing_hv_dates == ["2024-01-03"]
    assert report.support_status.missing_spot_dates == ["2024-01-02"]
    assert report.date_range == ("2024-01-01", "2024-01-03")
