import importlib
from types import SimpleNamespace


def test_request_retries_rate_limit(monkeypatch):
    mod = importlib.import_module("tomic.polygon_client")

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
