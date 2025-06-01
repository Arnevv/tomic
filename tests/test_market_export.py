# ruff: noqa: E402
import csv
import sys
import types
from types import SimpleNamespace

# Stub pandas so market_export can be imported without the real dependency
sys.modules.setdefault("pandas", types.ModuleType("pandas"))
contract_stub = types.ModuleType("ibapi.contract")


class Contract:  # noqa: D401 - simple stub
    """Stub contract object."""

    pass


contract_stub.Contract = Contract  # type: ignore[attr-defined]
sys.modules.setdefault("ibapi.contract", contract_stub)
combined_stub = types.ModuleType("tomic.api.combined_app")
combined_stub.CombinedApp = object
sys.modules.setdefault("tomic.api.combined_app", combined_stub)

from tomic.api.market_export import _write_option_chain, _HEADERS_CHAIN


def test_write_option_chain_skips_invalid(tmp_path):
    market_data = {
        1: {
            "expiry": "20240101",
            "right": "C",
            "strike": 100,
            "bid": 1.0,
            "ask": 1.2,
            "iv": 0.25,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
        },
        2: {
            "expiry": "20240101",
            "right": "P",
            "strike": 90,
            "bid": 0.8,
            "ask": 1.0,
            "iv": 0.3,
            "delta": -0.4,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
        },
    }
    invalid_contracts = {2}
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=invalid_contracts,
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == _HEADERS_CHAIN
    assert len(rows) == 2
    assert len(rows[0]) == len(_HEADERS_CHAIN)
    assert rows[1][2] == "100"  # strike of valid contract


def test_write_option_chain_negative_bid(tmp_path):
    """parity deviation should be empty when bid or ask is negative."""

    market_data = {
        1: {
            "expiry": "20240101",
            "right": "C",
            "strike": 100,
            "bid": -1.0,
            "ask": 1.2,
            "iv": 0.25,
            "delta": 0.5,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.1,
        },
        2: {
            "expiry": "20240101",
            "right": "P",
            "strike": 100,
            "bid": 0.8,
            "ask": 1.0,
            "iv": 0.3,
            "delta": -0.4,
            "gamma": 0.1,
            "vega": 0.2,
            "theta": -0.05,
        },
    }
    app = SimpleNamespace(
        market_data=market_data,
        invalid_contracts=set(),
        spot_price=100.0,
    )

    _write_option_chain(app, "ABC", str(tmp_path), "123")

    path = tmp_path / "option_chain_ABC_123.csv"
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    assert rows[1][-1] == ""
    assert rows[2][-1] == ""
