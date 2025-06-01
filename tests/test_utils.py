# ruff: noqa: E402
import json
import sys
import types
from types import SimpleNamespace

# Provide minimal stubs for the ``ibapi`` package so ``market_utils`` can be imported
stub = types.ModuleType("ibapi.contract")


class Contract:  # noqa: D401 - simple stub
    """Stub contract object."""

    pass


stub.Contract = Contract  # type: ignore[attr-defined]
sys.modules.setdefault("ibapi.contract", stub)

from tomic.analysis.vol_snapshot import store_volatility_snapshot, snapshot_symbols
from tomic.api.market_utils import (
    count_incomplete,
    calculate_hv30,
    calculate_atr14,
)
from tomic.cli.strategy_dashboard import determine_strategy_type, collapse_legs
from tomic.analysis.performance_analyzer import compute_pnl


def test_store_volatility_snapshot_roundtrip(tmp_path):
    path = tmp_path / "data.json"
    record = {
        "date": "2025-05-31",
        "symbol": "ABC",
        "spot": 10.0,
        "iv30": 0.3,
        "hv30": 0.2,
        "iv_rank": 50,
        "skew": 0.1,
    }
    store_volatility_snapshot(record, path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == [record]

    updated = record.copy()
    updated["iv30"] = 0.4
    store_volatility_snapshot(updated, path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == [updated]


def test_store_volatility_snapshot_skips_incomplete(tmp_path):
    path = tmp_path / "snap.json"
    record = {
        "date": "2025-05-31",
        "symbol": "ABC",
        "spot": 10.0,
        "iv30": 0.3,
        "hv30": None,
        "iv_rank": 50,
        "skew": 0.1,
    }
    store_volatility_snapshot(record, path)
    assert not path.exists()


def test_snapshot_symbols(tmp_path):
    path = tmp_path / "vol.json"
    calls: list[str] = []

    def fetcher(sym: str) -> dict:
        calls.append(sym)
        return {
            "spot_price": 10.0,
            "implied_volatility": 0.3,
            "hv30": 0.2,
            "iv_rank": 40,
            "skew": 0.05,
        }

    snapshot_symbols(["AAA", "BBB"], fetcher, path)
    assert set(calls) == {"AAA", "BBB"}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert {d["symbol"] for d in data} == {"AAA", "BBB"}


def test_count_incomplete():
    records = [
        {
            "bid": 1,
            "ask": 2,
            "iv": 0.2,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
        },
        {
            "bid": 1,
            "ask": None,
            "iv": 0.2,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
        },
        {"bid": 1},
    ]
    assert count_incomplete(records) == 2


def test_calculate_hv30_and_atr14():
    Bar = SimpleNamespace
    bars = [Bar(close=100, high=101, low=99) for _ in range(31)]
    assert calculate_hv30(bars) == 0.0
    assert calculate_atr14(bars) == 2.0
    assert calculate_hv30(bars[:1]) is None
    assert calculate_atr14(bars[:10]) is None


def test_compute_pnl_negative():
    trade = {"EntryPrice": 3, "ExitPrice": 5}
    assert compute_pnl(trade) == -200


def test_determine_strategy_type_other():
    legs = [{"right": "C", "position": 1}, {"right": "C", "position": 2}]
    assert determine_strategy_type(legs) == "Other"


def test_collapse_legs_partial():
    legs = [{"conId": 1, "position": 2}, {"conId": 1, "position": -1}]
    result = collapse_legs(legs)
    assert result == [{"conId": 1, "position": 1}]
