import importlib
import sys
import types

# Build pandas stub with minimal functionality
captured_concat: list = []
combined_result = None


class FakeFrame:
    def __init__(
        self, empty: bool = False, all_na: bool = False, has_cols: bool = True
    ):
        self._empty = empty
        self._all_na = all_na
        self.saved_path: str | None = None
        self.columns = ["c"] if has_cols else []

    @property
    def empty(self) -> bool:
        return self._empty

    def isna(self):
        class _Stage1:
            def __init__(self, flag: bool):
                self.flag = flag

            def all(self):
                class _Stage2:
                    def __init__(self, flag: bool):
                        self.flag = flag

                    def all(self):
                        return self.flag

                return _Stage2(self.flag)

        return _Stage1(self._all_na)

    def to_csv(self, path: str, index: bool = False) -> None:
        self.saved_path = path


def fake_concat(frames, ignore_index=False):
    global combined_result
    captured_concat.extend(frames)
    combined_result = FakeFrame()
    return combined_result


pd_stub = types.ModuleType("pandas")
pd_stub.DataFrame = FakeFrame
pd_stub.concat = fake_concat
sys.modules["pandas"] = pd_stub

contract_stub = types.ModuleType("ibapi.contract")
client_stub = types.ModuleType("ibapi.client")
client_stub.EClient = type("EClient", (), {})
wrapper_stub = types.ModuleType("ibapi.wrapper")
wrapper_stub.EWrapper = type("EWrapper", (), {})
sys.modules.setdefault("ibapi.client", client_stub)
sys.modules.setdefault("ibapi.wrapper", wrapper_stub)


class Contract:  # noqa: D401 - simple stub
    """Stub contract object."""

    pass


contract_stub.Contract = Contract
sys.modules.setdefault("ibapi.contract", contract_stub)
client_stub = types.ModuleType("tomic.api.market_client")
client_stub.MarketClient = object
client_stub.OptionChainClient = object
client_stub.TermStructureClient = object
client_stub.fetch_market_metrics = lambda *a, **k: None
client_stub.start_app = lambda *a, **k: None
client_stub.await_market_data = lambda *a, **k: True
sys.modules.setdefault("tomic.api.market_client", client_stub)

getallmarkets = importlib.reload(importlib.import_module("tomic.api.getallmarkets"))


def test_export_combined_csv_filters_invalid(tmp_path):
    captured_concat.clear()
    global combined_result
    combined_result = None
    df_valid = FakeFrame()
    df_empty = FakeFrame(empty=True)
    df_all_na = FakeFrame(all_na=True)

    getallmarkets.export_combined_csv([df_valid, df_empty, df_all_na], str(tmp_path))

    assert captured_concat == [df_valid]
    assert combined_result.saved_path == str(tmp_path / "Overzicht_Marktkenmerken.csv")


def test_export_combined_csv_skips_no_columns(tmp_path):
    captured_concat.clear()
    global combined_result
    combined_result = None
    df_valid = FakeFrame()
    df_no_cols = FakeFrame(has_cols=False)

    getallmarkets.export_combined_csv([df_valid, df_no_cols], str(tmp_path))

    assert captured_concat == [df_valid]
    assert combined_result.saved_path == str(tmp_path / "Overzicht_Marktkenmerken.csv")


class FakeSeries:
    def __init__(self, value: str) -> None:
        self.value = value

    @property
    def iloc(self) -> "FakeSeries":
        return self

    def __getitem__(self, idx: int) -> str:
        return self.value


class FakeFrameRun:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.columns = ["Symbol"]

    @property
    def empty(self) -> bool:
        return False

    def isna(self):
        class _Stage1:
            def all(self) -> "_Stage2":
                class _Stage2:
                    def all(self) -> bool:
                        return False

                return _Stage2()

        return _Stage1()

    def __getitem__(self, key: str) -> FakeSeries:
        assert key == "Symbol"
        return FakeSeries(self.symbol)


def test_run_all_passes_flags(monkeypatch, tmp_path):
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets"))

    calls = []

    def fake_run(sym, out=None, *, fetch_metrics=True, fetch_chains=True):
        calls.append((sym, out, fetch_metrics, fetch_chains))
        return FakeFrameRun(sym)

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "export_combined_csv", lambda *a, **k: None)
    monkeypatch.setattr(mod, "connect_ib", lambda *a, **k: types.SimpleNamespace(disconnect=lambda: None))

    result = mod.run_all(["AAA"], str(tmp_path), fetch_metrics=False, fetch_chains=True)

    assert [f.symbol for f in result] == ["AAA"]
    assert calls == [("AAA", str(tmp_path), False, True)]


def test_run_all_uses_defaults(monkeypatch, tmp_path):
    mod = importlib.reload(importlib.import_module("tomic.api.getallmarkets"))

    monkeypatch.setattr(mod, "connect_ib", lambda *a, **k: types.SimpleNamespace(disconnect=lambda: None))
    monkeypatch.setattr(mod, "export_combined_csv", lambda *a, **k: None)

    def fake_cfg_get(key, default=None):
        if key == "DEFAULT_SYMBOLS":
            return ["A", "B"]
        if key == "EXPORT_DIR":
            return str(tmp_path)
        return default

    monkeypatch.setattr(mod, "cfg_get", fake_cfg_get)

    called = []

    def fake_run(sym, out=None, *, fetch_metrics=True, fetch_chains=True):
        called.append(sym)
        return FakeFrameRun(sym)

    monkeypatch.setattr(mod, "run", fake_run)

    frames = mod.run_all()

    assert called == ["A", "B"]
    assert [f.symbol for f in frames] == ["A", "B"]
