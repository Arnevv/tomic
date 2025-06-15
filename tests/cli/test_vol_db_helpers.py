import importlib
from tomic.analysis.vol_db import init_db, get_latest_vol_stats, load_latest_stats


def test_get_latest_and_load_latest_stats():
    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("AAA", "2024-01-01", 0.5, 0.4, 0.3, 0.2, 10.0, 20.0),
    )
    conn.execute(
        "INSERT INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("AAA", "2024-01-02", 0.6, 0.5, 0.4, 0.3, 11.0, 21.0),
    )
    conn.execute(
        "INSERT INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BBB", "2024-01-01", 0.7, 0.6, 0.5, 0.4, 12.0, 22.0),
    )
    conn.commit()

    rec = get_latest_vol_stats(conn, "AAA")
    assert rec is not None
    assert rec.date == "2024-01-02"
    assert rec.iv == 0.6

    stats = load_latest_stats(conn, ["AAA", "BBB", "CCC"])
    assert set(stats.keys()) == {"AAA", "BBB"}
    assert stats["BBB"].iv_rank == 12.0
