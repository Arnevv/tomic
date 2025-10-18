from __future__ import annotations

import json
from pathlib import Path

import pytest

from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.exports.cli_support import (
    export_proposal_csv,
    export_proposal_json,
    proposal_journal_text,
    load_spot_from_metrics,
    spot_from_chain,
    refresh_spot_price,
)
from tomic.services.strategy_pipeline import StrategyProposal


class DummyRuntime:
    class _Cfg:
        def model_dump(self, **kwargs):
            return {"version": 1}

    def load(self):
        return self._Cfg()


@pytest.fixture
def sample_proposal() -> StrategyProposal:
    return StrategyProposal(
        strategy="test",
        legs=[
            {
                "expiry": "2099-01-01",
                "strike": 100.0,
                "type": "CALL",
                "position": -1,
                "bid": 1.0,
                "ask": 2.0,
                "mid": 1.5,
            }
        ],
        credit=1.0,
        margin=10.0,
        pos=0.1,
        rom=0.2,
        ev=0.3,
        edge=0.05,
        score=0.8,
    )


def test_export_proposal_csv_writes_metadata(tmp_path, sample_proposal):
    session = ControlPanelSession(symbol="ABC", strategy="Wheel")
    result = export_proposal_csv(
        session,
        sample_proposal,
        export_dir=tmp_path,
        runtime_config_module=DummyRuntime(),
    )
    assert result.exists()
    first_line = result.read_text().splitlines()[0]
    assert first_line.startswith("# meta:")


def test_export_proposal_json_includes_portfolio_context(tmp_path, sample_proposal, monkeypatch):
    session = ControlPanelSession(symbol="ABC", strategy="Wheel")
    positions_path = tmp_path / "positions.json"
    account_path = tmp_path / "account.json"
    earnings_path = tmp_path / "earnings.json"

    positions_path.write_text(json.dumps([{"symbol": "ABC"}]))
    account_path.write_text(json.dumps({"FullInitMarginReq": "42"}))
    earnings_path.write_text(json.dumps({"ABC": ["2099-01-01"]}))

    monkeypatch.setattr(
        "tomic.exports.cli_support.compute_portfolio_greeks",
        lambda positions: {"Delta": 1.0, "Theta": 2.0, "Vega": 3.0},
    )

    result = export_proposal_json(
        session,
        sample_proposal,
        export_dir=tmp_path,
        earnings_path=earnings_path,
        positions_file=positions_path,
        account_info_file=account_path,
        runtime_config_module=DummyRuntime(),
    )
    data = json.loads(result.read_text())
    assert data["data"]["portfolio_context_available"] is True
    assert data["data"]["portfolio_context"]["net_delta"] == 1.0


def test_proposal_journal_text_returns_string(sample_proposal):
    session = ControlPanelSession(symbol="XYZ", strategy="Wheel")
    text = proposal_journal_text(session, sample_proposal)
    assert isinstance(text, str)
    assert "XYZ" in text or text == ""


def test_load_spot_from_metrics_reads_latest(tmp_path):
    path = tmp_path / "other_data_ABC_001.csv"
    with path.open("w", newline="") as handle:
        handle.write("SpotPrice\n123.45\n")
    value = load_spot_from_metrics(tmp_path, "abc")
    assert value is not None
    assert abs(value - 123.45) < 1e-6


def test_spot_from_chain_detects_price():
    chain = [{"underlying_price": "123.45"}]
    value = spot_from_chain(chain)
    assert value is not None
    assert abs(value - 123.45) < 1e-6


def test_refresh_spot_price_uses_cache(tmp_path):
    history_dir = tmp_path / "history"
    meta_file = tmp_path / "meta.json"

    class Factory:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            factory = self

            class Client:
                def connect(self):
                    return None

                def fetch_spot_price(self, symbol):
                    factory.calls += 1
                    return 111.11

                def disconnect(self):
                    return None

            return Client()

    factory = Factory()
    price = refresh_spot_price(
        "ABC",
        price_history_dir=history_dir,
        price_meta_file=meta_file,
        polygon_client_factory=factory,
    )
    assert abs(price - 111.11) < 1e-6
    assert factory.calls == 1

    class FailingFactory:
        def __call__(self):  # pragma: no cover - should not be called
            raise AssertionError("Factory should not be used when cache is fresh")

    cached = refresh_spot_price(
        "ABC",
        price_history_dir=history_dir,
        price_meta_file=meta_file,
        polygon_client_factory=FailingFactory(),
    )
    assert abs(cached - 111.11) < 1e-6
