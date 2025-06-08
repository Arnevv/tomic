import asyncio
import importlib


class FakeSeries:
    def __init__(self, value: str) -> None:
        self.value = value

    @property
    def iloc(self) -> "FakeSeries":
        return self

    def __getitem__(self, idx: int) -> str:
        return self.value


class FakeFrame:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.columns = ["Symbol"]

    @property
    def empty(self) -> bool:
        return False

    def isna(self):
        class _Stage2:
            def all(self) -> bool:
                return False

        class _Stage1:
            def all(self) -> _Stage2:
                return _Stage2()

        return _Stage1()

    def __getitem__(self, key: str) -> FakeSeries:
        assert key == "Symbol"
        return FakeSeries(self.symbol)


def test_gather_markets_passes_flags(monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets_async"))

    calls = []

    def fake_run(sym, out=None, *, fetch_metrics=True, fetch_chains=True):
        calls.append((sym, out, fetch_metrics, fetch_chains))
        return FakeFrame(sym)

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "export_combined_csv", lambda *a, **k: None)

    result = asyncio.run(
        mod.gather_markets(["AAA"], "out", fetch_metrics=False, fetch_chains=True)
    )

    assert [f.symbol for f in result] == ["AAA"]
    assert calls == [("AAA", "out", False, True)]


def test_gather_markets_exports_when_metrics(tmp_path, monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets_async"))

    monkeypatch.setattr(
        mod,
        "run",
        lambda sym, out=None, *, fetch_metrics=True, fetch_chains=True: FakeFrame(sym),
    )
    paths = []
    monkeypatch.setattr(
        mod, "export_combined_csv", lambda frames, out: paths.append(out)
    )

    asyncio.run(
        mod.gather_markets(
            ["A", "B"], str(tmp_path), fetch_metrics=True, fetch_chains=False
        )
    )

    assert paths == [str(tmp_path)]
