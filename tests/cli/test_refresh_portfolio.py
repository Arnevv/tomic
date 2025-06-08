import json
import sys
from types import SimpleNamespace

from tomic.cli import strategy_dashboard as dash


def test_refresh_portfolio_updates_meta(tmp_path, monkeypatch):
    meta = tmp_path / "meta.json"
    called = {"n": 0}

    def fake_main():
        called["n"] += 1

    monkeypatch.setitem(
        sys.modules,
        "tomic.api.getaccountinfo",
        SimpleNamespace(main=fake_main),
    )
    import tomic.api as api
    monkeypatch.setattr(api, "getaccountinfo", SimpleNamespace(main=fake_main), raising=False)
    monkeypatch.setattr(
        dash,
        "cfg_get",
        lambda key, default=None: (
            str(meta) if key == "PORTFOLIO_META_FILE" else default
        ),
    )

    dash.refresh_portfolio_data()

    assert called["n"] == 1
    assert meta.exists()
    data = json.loads(meta.read_text())
    assert "last_update" in data
