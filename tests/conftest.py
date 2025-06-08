import sys
import types
import pytest

@pytest.fixture(autouse=True)
def stub_external_modules():
    """Provide lightweight stubs for optional external dependencies."""
    ibapi_pkg = types.ModuleType("ibapi")
    contract_stub = types.ModuleType("ibapi.contract")
    client_stub = types.ModuleType("ibapi.client")
    wrapper_stub = types.ModuleType("ibapi.wrapper")
    ticktype_stub = types.ModuleType("ibapi.ticktype")
    common_stub = types.ModuleType("ibapi.common")
    acct_stub = types.ModuleType("ibapi.account_summary_tags")

    contract_stub.Contract = type("Contract", (), {})
    contract_stub.ContractDetails = type("ContractDetails", (), {})
    class _EClient:
        def __init__(self, wrapper=None):
            pass

        def connect(self, host, port, clientId=0):
            pass

        def disconnect(self):
            pass

        def run(self):
            pass

    client_stub.EClient = _EClient
    wrapper_stub.EWrapper = type("EWrapper", (), {})
    ticktype_stub.TickTypeEnum = type("TickTypeEnum", (), {})
    common_stub.TickerId = int
    common_stub.OrderId = int
    acct_stub.AccountSummaryTags = type("AccountSummaryTags", (), {})

    sys.modules["ibapi"] = ibapi_pkg
    sys.modules["ibapi.contract"] = contract_stub
    sys.modules["ibapi.client"] = client_stub
    sys.modules["ibapi.wrapper"] = wrapper_stub
    sys.modules["ibapi.ticktype"] = ticktype_stub
    sys.modules["ibapi.common"] = common_stub
    sys.modules["ibapi.account_summary_tags"] = acct_stub

    ibapi_pkg.contract = contract_stub
    ibapi_pkg.client = client_stub
    ibapi_pkg.wrapper = wrapper_stub
    ibapi_pkg.ticktype = ticktype_stub
    ibapi_pkg.common = common_stub
    ibapi_pkg.account_summary_tags = acct_stub

    # Ensure attributes exist even if modules were previously imported
    sys.modules["ibapi.client"].EClient = client_stub.EClient
    sys.modules["ibapi.wrapper"].EWrapper = wrapper_stub.EWrapper

    pd_stub = types.ModuleType("pandas")
    pd_stub.DataFrame = object
    pd_stub.concat = lambda frames, ignore_index=False: object()
    sys.modules["pandas"] = pd_stub

    sys.modules.setdefault("google", types.ModuleType("google"))
    sys.modules.setdefault("google.protobuf", types.ModuleType("protobuf"))
    sys.modules.setdefault("numpy", types.ModuleType("numpy"))
    sys.modules.setdefault("requests", types.ModuleType("requests"))

    # Ensure market_utils is reloaded fresh for each test
    sys.modules.pop("tomic.api.market_utils", None)
    sys.modules.pop("tomic.api.base_client", None)
    yield
