import asyncio
import importlib
import sys
import types


def test_run_async_does_not_connect(monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.api.getonemarket"))

    async def fake_market(*a, **k):
        return None

    async def fake_chain(*a, **k):
        return None

    export_stub = types.SimpleNamespace(
        export_market_data_async=fake_market,
        export_option_chain_async=fake_chain,
    )
    monkeypatch.setitem(sys.modules, "tomic.api.market_export", types.ModuleType("tomic.api.market_export"))
    monkeypatch.setattr(mod, "_market_export", lambda: export_stub)
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    called = []
    if hasattr(mod, "connect_ib"):
        monkeypatch.setattr(mod, "connect_ib", lambda *a, **k: called.append(True))

    result = asyncio.run(mod.run_async("ABC"))

    assert result is True
    assert not called
