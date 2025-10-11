from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tomic.services.market_snapshot import (
    MarketRow,
    MarketSnapshotService,
    _build_factsheet,
    _read_metrics,
)


def _loader(path: Path):
    return json.loads(path.read_text())


def test_read_metrics_returns_row(tmp_path):
    summary_dir = tmp_path / "summary"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for directory in (summary_dir, hv_dir, spot_dir):
        directory.mkdir()

    (summary_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "atm_iv": 0.4,
                    "iv_rank (HV)": 62,
                    "iv_percentile (HV)": 75,
                    "term_m1_m2": 1.1,
                    "term_m1_m3": 1.2,
                    "skew": 3.5,
                }
            ]
        )
    )
    (hv_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "hv20": 0.2,
                    "hv30": 0.25,
                    "hv90": 0.28,
                    "hv252": 0.3,
                }
            ]
        )
    )
    (spot_dir / "AAA.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-05-02",
                    "close": 123.4,
                }
            ]
        )
    )

    row = _read_metrics(
        "AAA",
        summary_dir,
        hv_dir,
        spot_dir,
        {"AAA": ["2024-05-10", "2024-04-01"]},
        loader=_loader,
        today_fn=lambda: date(2024, 5, 1),
    )

    assert isinstance(row, MarketRow)
    assert row.symbol == "AAA"
    assert row.iv_rank == 0.62
    assert row.iv_percentile == 0.75
    assert row.next_earnings == date(2024, 5, 10)


def test_build_factsheet_parses_dates():
    factsheet = _build_factsheet(
        {
            "symbol": "AAA",
            "strategy": "short_put_spread",
            "spot": 101.2,
            "iv": 0.4,
            "hv20": 0.2,
            "hv30": 0.25,
            "hv90": 0.3,
            "hv252": 0.31,
            "term_m1_m2": 1.1,
            "term_m1_m3": 1.3,
            "iv_rank": 48,
            "iv_percentile": 60,
            "skew": 3.5,
            "criteria": "some,criteria",
            "next_earnings": "2024-06-01",
        },
        today_fn=lambda: date(2024, 5, 20),
    )

    assert factsheet.symbol == "AAA"
    assert factsheet.strategy == "short_put_spread"
    assert factsheet.iv_rank == 0.48
    assert factsheet.iv_percentile == 0.60
    assert factsheet.next_earnings == date(2024, 6, 1)
    assert factsheet.days_until_earnings == 12


def test_load_snapshot_returns_serializable_rows(tmp_path):
    summary_dir = tmp_path / "summary"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for directory in (summary_dir, hv_dir, spot_dir):
        directory.mkdir()

    def write(symbol: str, summary_iv: float, percentile: float):
        (summary_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "atm_iv": summary_iv,
                        "iv_rank (HV)": 55,
                        "iv_percentile (HV)": percentile,
                        "term_m1_m2": 1.1,
                        "term_m1_m3": 1.2,
                        "skew": 3.0,
                    }
                ]
            )
        )
        (hv_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "hv20": 0.2,
                        "hv30": 0.25,
                        "hv90": 0.28,
                        "hv252": 0.3,
                    }
                ]
            )
        )
        (spot_dir / f"{symbol}.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-05-02",
                        "close": 120.0,
                    }
                ]
            )
        )

    write("AAA", 0.4, 70)
    write("BBB", 0.3, 40)

    earnings = tmp_path / "earnings.json"
    earnings.write_text(json.dumps({"AAA": ["2024-06-01"], "BBB": ["2024-07-01"]}))

    config = {
        "DEFAULT_SYMBOLS": ["AAA", "BBB"],
        "IV_DAILY_SUMMARY_DIR": str(summary_dir),
        "HISTORICAL_VOLATILITY_DIR": str(hv_dir),
        "PRICE_HISTORY_DIR": str(spot_dir),
        "EARNINGS_DATES_FILE": str(earnings),
    }

    service = MarketSnapshotService(config, loader=_loader, today_fn=lambda: date(2024, 5, 20))
    snapshot = service.load_snapshot()

    assert snapshot["generated_at"] == "2024-05-20"
    rows = snapshot["rows"]
    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["iv_percentile"] == 0.70
    assert rows[0]["next_earnings"] == "2024-06-01"

    filtered = service.load_snapshot({"symbols": ["BBB"]})
    assert [row["symbol"] for row in filtered["rows"]] == ["BBB"]
