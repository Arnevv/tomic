import importlib
from tomic.analysis.vol_db import init_db


def test_show_pricehistory(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.show_pricehistory")

    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO PriceHistory (symbol, date, close, volume, atr) VALUES (?, ?, ?, ?, ?)",
        ("AAA", "2024-01-01", 1.23, 100, None),
    )
    conn.execute(
        "INSERT INTO PriceHistory (symbol, date, close, volume, atr) VALUES (?, ?, ?, ?, ?)",
        ("AAA", "2024-01-02", 1.25, 120, None),
    )
    conn.commit()

    monkeypatch.setattr(mod, "init_db", lambda path: conn)
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    mod.main(["AAA"])

    out = capsys.readouterr().out
    assert "2024-01-01" in out
    assert "1.23" in out
    assert "2024-01-02" in out
