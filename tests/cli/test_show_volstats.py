import importlib


def test_show_volstats_main(monkeypatch):
    mod = importlib.import_module("tomic.cli.show_volstats")

    monkeypatch.setattr(mod, "cfg_get", lambda name, default=None: default)

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows
        def fetchall(self):
            return self._rows
    class FakeConn:
        def __init__(self):
            self.closed = False
        def execute(self, sql, params):
            return FakeCursor([
                ("ABC", "2025-01-01", 0.3, 0.1, 0.2, 0.3, 50.0, 75.0),
            ])
        def close(self):
            self.closed = True
    conn = FakeConn()
    monkeypatch.setattr(mod, "init_db", lambda path: conn)

    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))

    mod.main([])

    assert any("ABC" in line for line in lines)
    assert conn.closed
