import importlib
from datetime import datetime
from pathlib import Path

import pytest


@pytest.fixture()
def services_module(monkeypatch, tmp_path):
    log_mod = importlib.import_module("tomic.logutils")

    if not hasattr(log_mod, "summarize_evaluations"):
        monkeypatch.setattr(log_mod, "summarize_evaluations", lambda captured: {}, raising=False)

    pipeline_mod = importlib.import_module("tomic.services.pipeline_refresh")
    if not hasattr(pipeline_mod, "RefreshProposal"):
        monkeypatch.setattr(pipeline_mod, "RefreshProposal", pipeline_mod.Proposal, raising=False)

    mod = importlib.import_module("tomic.core.portfolio.services")
    fixed_now = datetime(2024, 1, 2, 3, 4, 5)

    class DummyDateTime:
        @classmethod
        def now(cls):
            return fixed_now

    monkeypatch.setattr(mod, "datetime", DummyDateTime)

    values = {
        "EXPORT_DIR": str(tmp_path / "exports"),
        "IB_FETCH_ONLY": True,
        "IB_CLIENT_ID": 42,
        "DEFAULT_ORDER_TYPE": "LMT",
        "DEFAULT_TIME_IN_FORCE": "DAY",
        "IB_ACCOUNT_ALIAS": "paper",
    }

    monkeypatch.setattr(
        mod,
        "cfg",
        type(
            "CfgProxy",
            (),
            {
                "get": staticmethod(lambda key, default=None: values.get(key, default)),
            },
        ),
    )

    return mod


def _make_proposal():
    proposal_cls = importlib.import_module("tomic.services.strategy_pipeline").StrategyProposal
    return proposal_cls(strategy="test", legs=[{"symbol": "SPY"}])


def test_prepare_order_fetch_only(monkeypatch, services_module, tmp_path):
    mod = services_module
    proposal = _make_proposal()

    captured = {}

    def fake_prepare_order_instructions(*args, **kwargs):
        captured["call"] = {"args": args, "kwargs": kwargs}
        return {"order": "instructions"}

    monkeypatch.setattr(mod, "prepare_order_instructions", fake_prepare_order_instructions)

    dump_calls = []

    class FakeOrderSubmissionService:
        @staticmethod
        def dump_order_log(instructions, directory):
            dump_calls.append((instructions, directory))
            return Path(directory) / "order-log.json"

        def __call__(self, *args, **kwargs):
            return self

    monkeypatch.setattr(mod, "OrderSubmissionService", FakeOrderSubmissionService)

    log_path, order_ids, client_id, fetch_only = mod.prepare_order(proposal, symbol="SPY")

    assert captured["call"]["kwargs"]["symbol"] == "SPY"
    assert captured["call"]["kwargs"]["account"] == "paper"
    assert log_path.name == "order-log.json"
    assert order_ids == ()
    assert client_id == 42
    assert fetch_only is True

    assert dump_calls
    _, dump_dir = dump_calls[0]
    assert dump_dir.name == "20240102"


def test_prepare_order_places_orders(monkeypatch, services_module, tmp_path):
    mod = services_module
    proposal = _make_proposal()

    calls = {"place": None, "disconnect": False}

    monkeypatch.setattr(mod, "prepare_order_instructions", lambda *a, **k: {"id": 1})

    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    def fake_get(key, default=None):
        overrides = {
            "EXPORT_DIR": str(export_dir),
            "IB_FETCH_ONLY": False,
            "IB_HOST": "127.0.0.1",
            "IB_PAPER_MODE": True,
            "IB_PORT": 4001,
            "IB_CLIENT_ID": 7,
            "IB_ORDER_CLIENT_ID": 13,
            "DOWNLOAD_TIMEOUT": 9,
        }
        return overrides.get(key, default)

    monkeypatch.setattr(mod, "cfg", type("CfgProxy", (), {"get": staticmethod(fake_get)}))

    class FakeApp:
        def __init__(self):
            self.disconnected = False

        def disconnect(self):
            self.disconnected = True
            calls["disconnect"] = True

    class FakeOrderSubmissionService:
        dump_calls = []

        @staticmethod
        def dump_order_log(instructions, directory):
            FakeOrderSubmissionService.dump_calls.append((instructions, directory))
            return Path(directory) / "placed.json"

        def __call__(self):
            return self

        def place_orders(self, instructions, host, port, client_id, timeout):
            calls["place"] = {
                "instructions": instructions,
                "host": host,
                "port": port,
                "client_id": client_id,
                "timeout": timeout,
            }
            return FakeApp(), [101, 202]

    monkeypatch.setattr(mod, "OrderSubmissionService", FakeOrderSubmissionService)

    log_path, order_ids, client_id, fetch_only = mod.prepare_order(proposal, symbol="TSLA")

    assert log_path.name == "placed.json"
    assert order_ids == (101, 202)
    assert client_id == 13
    assert fetch_only is False

    assert calls["place"]["host"] == "127.0.0.1"
    assert calls["place"]["port"] == 4001
    assert calls["place"]["client_id"] == 13
    assert calls["place"]["timeout"] == 9
    assert calls["disconnect"] is True


def test_prepare_order_wraps_errors(monkeypatch, services_module):
    mod = services_module
    proposal = _make_proposal()

    monkeypatch.setattr(
        mod,
        "prepare_order_instructions",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad order")),
    )

    with pytest.raises(mod.OrderSubmissionError) as exc:
        mod.prepare_order(proposal, symbol="SPY")
    assert "bad order" in str(exc.value)


def test_submit_order_returns_dataclass(monkeypatch, services_module):
    mod = services_module
    expected = (Path("/tmp/log"), (1, 2), 99, False)
    monkeypatch.setattr(mod, "prepare_order", lambda *a, **k: expected)

    proposal = _make_proposal()
    result = mod.submit_order(proposal, symbol="QQQ")

    assert result.log_path == expected[0]
    assert result.order_ids == expected[1]
    assert result.client_id == 99
    assert result.fetch_only is False
