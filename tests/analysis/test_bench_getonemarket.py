import csv
import importlib
from datetime import datetime


def test_bench_getonemarket_creates_csv(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.analysis.bench_getonemarket")
    monkeypatch.setattr(mod, "setup_logging", lambda: None)
    async def fake_bench_async(syms):
        return 1.0

    monkeypatch.setattr(mod, "bench_async", fake_bench_async)

    chain = tmp_path / "option_chain_XYZ_20240101_000000_000000.csv"
    chain.write_text("data")
    monkeypatch.setattr(mod, "find_latest_chain", lambda: chain)
    monkeypatch.setattr(mod.csv_quality_check, "analyze_csv", lambda p: {"total": 10, "valid": 8})
    monkeypatch.setattr(mod, "cfg_get", lambda n, default=None: str(tmp_path))

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1, 0, 0, 0)
    monkeypatch.setattr(mod, "datetime", FakeDT)

    mod.main(["XYZ"])

    result = tmp_path / "benchmark_20240101_000000_000000.csv"
    assert result.exists()
    with open(result, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["Symbols", "Runtime", "Quality", "ChainFile"]
    assert rows[1][0] == "XYZ"


def test_write_result_csv(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.analysis.bench_getonemarket")

    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 1, 0, 0, 0)

    monkeypatch.setattr(mod, "datetime", FakeDT)

    chain = tmp_path / "option_chain_ABC.csv"
    chain.write_text("data")

    out = mod.write_result_csv(["ABC"], 2.5, 90.0, chain)
    expected = tmp_path / "benchmark_20240101_000000_000000.csv"
    assert out == expected
    with open(out, newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1] == ["ABC", "2.50", "90.0", chain.name]
