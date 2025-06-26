import importlib


def test_show_volstats_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.show_volstats")

    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["ABC"] if name == "DEFAULT_SYMBOLS" else default)
    monkeypatch.setattr(mod, "fetch_market_metrics", lambda sym, timeout=10: {
        "spot_price": 100.0,
        "implied_volatility": 20.0,
        "iv_rank": 50.0,
        "iv_percentile": 75.0,
        "atr14": 5.0,
        "vix": 17.0,
        "skew": -1.0,
        "term_m1_m2": -0.5,
        "term_m1_m3": -1.2,
    })
    monkeypatch.setattr(mod, "_get_closes", lambda sym: [1.0] * 300)
    monkeypatch.setattr(mod, "historical_volatility", lambda closes, *, window, trading_days=252: {30: 10.0, 90: 20.0, 252: 30.0}[window])

    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))

    mod.main([])

    assert any("ABC" in line for line in lines)
