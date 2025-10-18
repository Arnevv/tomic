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
