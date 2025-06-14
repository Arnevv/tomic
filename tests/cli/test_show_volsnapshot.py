import importlib
from tomic.analysis.vol_db import init_db


def test_show_volsnapshot_table_output(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.show_volsnapshot")

    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("AAA", "2024-01-01", 0.5, 0.4, 0.3, 0.2, 10.0, 20.0),
    )
    conn.execute(
        "INSERT INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BBB", "2024-01-01", 0.6, 0.5, 0.4, 0.3, 11.0, 21.0),
    )
    conn.commit()

    monkeypatch.setattr(mod, "init_db", lambda path: conn)
    monkeypatch.setattr(mod, "setup_logging", lambda: None)

    mod.main(["2024-01-01"])

    out = capsys.readouterr().out
    assert "AAA" in out
    assert "BBB" in out
    assert "symbol" in out
