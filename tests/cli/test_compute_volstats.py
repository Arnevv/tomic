import importlib
import types


def test_compute_volstats_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.compute_volstats")

    # Stub config
    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: ["ABC"] if name == "DEFAULT_SYMBOLS" else default)

    # Stub database connection and query
    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows
    class FakeConn:
        def __init__(self):
            self.closed = False
            self.queries = []
        def execute(self, sql, params):
            self.queries.append((sql, params))
            return FakeCursor([(1.0,) for _ in range(91)])
        def close(self):
            self.closed = True
    conn = FakeConn()
    monkeypatch.setattr(mod, "init_db", lambda path: conn)

    # Stub computations
    monkeypatch.setattr(mod, "fetch_iv30d", lambda sym: 0.25)
    monkeypatch.setattr(
        mod,
        "historical_volatility",
        lambda closes, *, window, trading_days=252: {30: 0.1, 60: 0.2, 90: 0.3}[window],
    )

    captured = []
    def fake_save(conn_obj, record, closes):
        captured.append(record)
    monkeypatch.setattr(mod, "save_vol_stats", fake_save)

    mod.main([])

    assert len(captured) == 1
    rec = captured[0]
    assert rec.symbol == "ABC"
    assert rec.iv == 0.25
    assert rec.hv30 == 0.1
    assert rec.hv60 == 0.2
    assert rec.hv90 == 0.3

