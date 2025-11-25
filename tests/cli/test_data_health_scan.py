from __future__ import annotations

import json
from datetime import date, timedelta

from tomic.cli import data_health_scan as mod


def test_gap_percentage_calculation():
    """Test that gap percentage is calculated correctly."""
    # Create a window with 5 actual dates over a longer period
    # Jan 2024: 2,3,4,5 (Tue-Fri) + 8,9,10,11,12 (Mon-Fri) = 9 trading days
    # (1 Jan is New Year's Day - market closed)
    window = mod.SeriesWindow(
        start=date(2024, 1, 2),  # Tuesday
        end=date(2024, 1, 12),   # Friday
        actual_count=5,
    )
    # Expected: 9 trading days, actual: 5, missing: 4 -> 44.4%
    assert window.expected_count == 9
    gap = window.gap_pct
    assert gap is not None
    assert abs(gap - 44.4) < 0.1


def test_gap_percentage_no_gaps():
    """Test that 0% gap is returned when all days present."""
    window = mod.SeriesWindow(
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),  # Tue-Fri = 4 trading days
        actual_count=4,
    )
    assert window.gap_pct == 0.0


def test_format_window_shows_gap():
    """Test that _format_window includes gap percentage when gaps exist."""
    window = mod.SeriesWindow(
        start=date(2024, 1, 2),
        end=date(2024, 1, 12),
        actual_count=5,
    )
    formatted = mod._format_window(window)
    assert "2024-01-02" in formatted
    assert "2024-01-12" in formatted
    assert "44.4%" in formatted


def test_format_window_no_gap_suffix():
    """Test that _format_window omits gap percentage when no gaps."""
    window = mod.SeriesWindow(
        start=date(2024, 1, 2),
        end=date(2024, 1, 5),
        actual_count=4,
    )
    formatted = mod._format_window(window)
    assert "%" not in formatted


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
