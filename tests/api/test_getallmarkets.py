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
combined_stub = types.ModuleType("tomic.api.combined_app")
combined_stub.CombinedApp = object
sys.modules.setdefault("tomic.api.combined_app", combined_stub)
mu_stub = types.ModuleType("tomic.api.market_utils")
mu_stub.fetch_market_metrics = lambda *a, **k: None
mu_stub.start_app = lambda *a, **k: None
mu_stub.await_market_data = lambda *a, **k: True
sys.modules.setdefault("tomic.api.market_utils", mu_stub)

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
