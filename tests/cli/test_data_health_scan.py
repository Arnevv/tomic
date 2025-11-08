from __future__ import annotations

import json
from datetime import date, timedelta

from tomic.cli import data_health_scan as mod


def test_scan_reports_missing_and_mismatch(tmp_path, monkeypatch, capsys):
    today = date.today()

    spot_dir = tmp_path / "spot"
    hv_dir = tmp_path / "hv"
    iv_dir = tmp_path / "iv"
    for directory in (spot_dir, hv_dir, iv_dir):
        directory.mkdir()

    earnings_file = tmp_path / "earnings.json"

    with (spot_dir / "AAPL.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "date": (today - timedelta(days=2)).isoformat(),
                    "close": 100.0,
                },
                {
                    "date": (today - timedelta(days=1)).isoformat(),
                    "close": 101.0,
                },
            ],
            handle,
        )
    with (spot_dir / "MSFT.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "date": (today - timedelta(days=4)).isoformat(),
                    "close": 200.0,
                },
                {
                    "date": (today - timedelta(days=3)).isoformat(),
                    "close": 201.0,
                },
            ],
            handle,
        )

    with (hv_dir / "AAPL.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {"date": (today - timedelta(days=2)).isoformat(), "hv20": 0.2},
                {"date": (today - timedelta(days=1)).isoformat(), "hv20": 0.21},
            ],
            handle,
        )
    with (hv_dir / "MSFT.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {"date": (today - timedelta(days=4)).isoformat(), "hv20": 0.3},
                {"date": today.isoformat(), "hv20": 0.31},
            ],
            handle,
        )

    with (iv_dir / "AAPL.json").open("w", encoding="utf-8") as handle:
        json.dump(
            [
                {"date": (today - timedelta(days=2)).isoformat(), "atm_iv": 0.4},
                {"date": (today - timedelta(days=1)).isoformat(), "atm_iv": 0.41},
            ],
            handle,
        )

    with earnings_file.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "AAPL": [(today + timedelta(days=30)).isoformat()],
                "MSFT": [],
            },
            handle,
        )

    def fake_cfg_get(key: str, default=None):
        mapping = {
            "PRICE_HISTORY_DIR": str(spot_dir),
            "HISTORICAL_VOLATILITY_DIR": str(hv_dir),
            "IV_DAILY_SUMMARY_DIR": str(iv_dir),
            "EARNINGS_DATES_FILE": str(earnings_file),
            "DATA_HEALTH_THRESHOLDS": {
                "spot_max_age_days": 30,
                "hv_max_age_days": 30,
                "iv_max_age_days": 30,
                "earnings_max_age_days": 365,
            },
        }
        return mapping.get(key, default)

    monkeypatch.setattr(mod, "cfg_get", fake_cfg_get)

    mod.main(["--symbols", "AAPL,MSFT"])

    output = capsys.readouterr().out
    assert "Symbol" in output
    assert "AAPL" in output
    assert "MSFT" in output
    assert "missing_iv" in output
    assert "missing_earnings" in output
    assert "hv_after_spot" in output
