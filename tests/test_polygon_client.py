import importlib
from types import SimpleNamespace


def test_request_retries_rate_limit(monkeypatch):
    mod = importlib.import_module("tomic.integrations.polygon.client")

    attempts = {"count": 0}

    def fake_get(url, params=None, timeout=10):
        attempts["count"] += 1
        status = 429 if attempts["count"] == 1 else 200
        resp = SimpleNamespace(status_code=status, text="", headers={"Retry-After": "1"})
        def raise_for_status():
            if status >= 400:
                import requests
                raise requests.HTTPError(str(status))
        resp.raise_for_status = raise_for_status
        resp.json = lambda: {}
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    client = mod.PolygonClient(api_key="key")
    client.connect()
    client._request("path")
    client.disconnect()
    assert attempts["count"] >= 2


def test_request_switches_api_key_on_403(monkeypatch):
    mod = importlib.import_module("tomic.integrations.polygon.client")

    used_keys = []

    def fake_get(url, params=None, timeout=10):
        key = params.get("apiKey")
        used_keys.append(key)
        status = 403 if key == "bad1" else 200
        resp = SimpleNamespace(status_code=status, text="")

        def raise_for_status():
            if status >= 400:
                import requests
                raise requests.HTTPError(str(status))

        resp.raise_for_status = raise_for_status
        resp.json = lambda: {"ok": True}
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.PolygonClient(api_key="bad1,bad2")
    client.connect()
    data = client._request("path")
    client.disconnect()

    assert used_keys == ["bad1", "bad2"]
    assert data == {"ok": True}


def test_request_raises_after_all_keys_invalid(monkeypatch):
    mod = importlib.import_module("tomic.integrations.polygon.client")

    used_keys = []

    def fake_get(url, params=None, timeout=10):
        key = params.get("apiKey")
        used_keys.append(key)
        status = 403
        resp = SimpleNamespace(status_code=status, text="")

        def raise_for_status():
            if status >= 400:
                import requests
                raise requests.HTTPError(str(status))

        resp.raise_for_status = raise_for_status
        resp.json = lambda: {}
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.PolygonClient(api_key="bad1,bad2")
    client.connect()
    import pytest

    with pytest.raises(Exception):
        client._request("path")
    client.disconnect()

    assert used_keys == ["bad1", "bad2"]


def test_fetch_ticker_details_success(monkeypatch):
    """Test fetching ticker details with sector info."""
    mod = importlib.import_module("tomic.integrations.polygon.client")

    def fake_get(url, params=None, timeout=10):
        resp = SimpleNamespace(status_code=200, text="")
        resp.raise_for_status = lambda: None
        resp.json = lambda: {
            "results": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "market": "stocks",
                "locale": "us",
                "primary_exchange": "XNAS",
                "type": "CS",
                "sic_code": "3571",
                "sic_description": "Electronic Computers",
                "market_cap": 3000000000000,
                "currency_name": "usd",
            }
        }
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.PolygonClient(api_key="key")
    client.connect()
    details = client.fetch_ticker_details("AAPL")
    client.disconnect()

    assert details["symbol"] == "AAPL"
    assert details["name"] == "Apple Inc."
    assert details["sic_code"] == "3571"
    assert details["sic_description"] == "Electronic Computers"
    assert details["market_cap"] == 3000000000000


def test_fetch_ticker_details_error_handling(monkeypatch):
    """Test fetch_ticker_details handles errors gracefully."""
    mod = importlib.import_module("tomic.integrations.polygon.client")

    def fake_get(url, params=None, timeout=10):
        raise Exception("Network error")

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)

    client = mod.PolygonClient(api_key="key")
    client.connect()
    details = client.fetch_ticker_details("AAPL")
    client.disconnect()

    # Should return minimal dict on error, not raise
    assert details["symbol"] == "AAPL"
    assert details.get("name") is None


def test_fetch_ticker_details_batch(monkeypatch):
    """Test batch fetching ticker details."""
    mod = importlib.import_module("tomic.integrations.polygon.client")

    call_count = {"count": 0}

    def fake_get(url, params=None, timeout=10):
        call_count["count"] += 1
        symbol = url.split("/")[-1].upper()
        resp = SimpleNamespace(status_code=200, text="")
        resp.raise_for_status = lambda: None
        resp.json = lambda: {
            "results": {
                "ticker": symbol,
                "name": f"{symbol} Inc.",
                "sic_code": "7370",
            }
        }
        return resp

    class DummySession:
        def get(self, url, params=None, timeout=10):
            return fake_get(url, params, timeout)

        def close(self):
            pass

    dummy_requests = SimpleNamespace(Session=lambda: DummySession())
    monkeypatch.setattr(mod, "requests", dummy_requests)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod.cfg, "get", lambda key, default=None: 0 if key == "POLYGON_SLEEP_BETWEEN" else default)

    client = mod.PolygonClient(api_key="key")
    client.connect()
    results = client.fetch_ticker_details_batch(["AAPL", "MSFT", "GOOGL"])
    client.disconnect()

    assert len(results) == 3
    assert "AAPL" in results
    assert "MSFT" in results
    assert "GOOGL" in results
    assert call_count["count"] == 3
