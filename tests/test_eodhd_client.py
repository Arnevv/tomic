"""Tests for EODHD earnings client."""

import importlib
import json
from types import SimpleNamespace

import pytest


def test_fetch_earnings_parses_response(monkeypatch):
    """Test that earnings response is correctly parsed."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    sample_response = {
        "type": "Earnings",
        "earnings": [
            {
                "code": "AAPL.US",
                "report_date": "2024-01-25",
                "date": "2023-12-31",
                "before_after_market": "AfterMarket",
                "actual": 2.18,
                "estimate": 2.10,
            },
            {
                "code": "AAPL.US",
                "report_date": "2024-05-02",
                "date": "2024-03-31",
                "before_after_market": "AfterMarket",
                "actual": 1.53,
                "estimate": 1.50,
            },
        ],
    }

    def fake_get(url, params=None, timeout=30):
        resp = SimpleNamespace(status_code=200, text="")
        resp.raise_for_status = lambda: None
        resp.json = lambda: sample_response
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=30):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.EODHDClient(api_key="test_key")
    client.connect()
    earnings = client.fetch_earnings(symbols=["AAPL"])
    client.disconnect()

    assert len(earnings) == 2
    assert earnings[0]["code"] == "AAPL.US"
    assert earnings[0]["report_date"] == "2024-01-25"


def test_fetch_all_symbols_earnings_groups_by_symbol(monkeypatch):
    """Test that multiple symbols are correctly grouped."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    sample_response = {
        "type": "Earnings",
        "earnings": [
            {"code": "AAPL.US", "report_date": "2024-01-25"},
            {"code": "AAPL.US", "report_date": "2024-05-02"},
            {"code": "MSFT.US", "report_date": "2024-01-30"},
            {"code": "MSFT.US", "report_date": "2024-04-25"},
        ],
    }

    def fake_get(url, params=None, timeout=30):
        resp = SimpleNamespace(status_code=200, text="")
        resp.raise_for_status = lambda: None
        resp.json = lambda: sample_response
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=30):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    client = mod.EODHDClient(api_key="test_key")
    client.connect()
    result = client.fetch_all_symbols_earnings(
        symbols=["AAPL", "MSFT"],
        from_date="2024-01-01",
    )
    client.disconnect()

    assert "AAPL" in result
    assert "MSFT" in result
    assert result["AAPL"] == ["2024-01-25", "2024-05-02"]
    assert result["MSFT"] == ["2024-01-30", "2024-04-25"]


def test_client_raises_without_api_key(monkeypatch):
    """Test that missing API key raises ValueError."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    # Clear env var
    monkeypatch.delenv("EODHD_API_KEY", raising=False)

    class DummySession:
        def get(self, url, params=None, timeout=30):
            pass

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.EODHDClient(api_key=None)
    client.connect()

    with pytest.raises(ValueError, match="API key not configured"):
        client.fetch_earnings(symbols=["AAPL"])


def test_client_raises_when_not_connected():
    """Test that requests without connect() raise RuntimeError."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    client = mod.EODHDClient(api_key="test_key")

    with pytest.raises(RuntimeError, match="not connected"):
        client.fetch_earnings(symbols=["AAPL"])


def test_request_retries_on_rate_limit(monkeypatch):
    """Test that rate limits trigger retries."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    attempts = {"count": 0}

    def fake_get(url, params=None, timeout=30):
        attempts["count"] += 1
        status = 429 if attempts["count"] == 1 else 200
        resp = SimpleNamespace(status_code=status, text="")

        def raise_for_status():
            if status >= 400:
                import requests
                raise requests.HTTPError(str(status))

        resp.raise_for_status = raise_for_status
        resp.json = lambda: {"earnings": []}
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=30):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    client = mod.EODHDClient(api_key="test_key")
    client.connect()
    client.fetch_earnings(symbols=["AAPL"])
    client.disconnect()

    assert attempts["count"] >= 2


def test_symbols_formatted_with_us_suffix(monkeypatch):
    """Test that symbols are formatted as SYMBOL.US."""
    mod = importlib.import_module("tomic.integrations.eodhd.client")

    captured_params = {}

    def fake_get(url, params=None, timeout=30):
        captured_params.update(params or {})
        resp = SimpleNamespace(status_code=200, text="")
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"earnings": []}
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=30):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.EODHDClient(api_key="test_key")
    client.connect()
    client.fetch_earnings(symbols=["aapl", "Msft", "GOOGL"])
    client.disconnect()

    assert captured_params["symbols"] == "AAPL.US,MSFT.US,GOOGL.US"
