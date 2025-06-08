import sys
import types

# Provide minimal ibapi stubs so CombinedApp can be imported without the real
# dependency.
client_stub = types.ModuleType("ibapi.client")


class EClient:
    def __init__(self, wrapper):
        pass


client_stub.EClient = EClient
sys.modules.setdefault("ibapi.client", client_stub)

wrapper_stub = types.ModuleType("ibapi.wrapper")


class EWrapper:
    pass


wrapper_stub.EWrapper = EWrapper
sys.modules.setdefault("ibapi.wrapper", wrapper_stub)

contract_stub = types.ModuleType("ibapi.contract")


class Contract:
    pass


class ContractDetails:
    def __init__(self):
        self.contract = Contract()


contract_stub.Contract = Contract
contract_stub.ContractDetails = ContractDetails
sys.modules.setdefault("ibapi.contract", contract_stub)

ticktype_stub = types.ModuleType("ibapi.ticktype")
ticktype_stub.TickTypeEnum = types.SimpleNamespace(LAST=4)
sys.modules.setdefault("ibapi.ticktype", ticktype_stub)

common_stub = types.ModuleType("ibapi.common")
common_stub.TickerId = int
sys.modules.setdefault("ibapi.common", common_stub)

from tomic.api.combined_app import CombinedApp  # noqa: E402
from tomic.utils import split_expiries  # noqa: E402


def test_option_params_aggregation():
    app = CombinedApp("ABC")
    calls: list[str] = []
    app.request_option_market_data = lambda: calls.append("called")  # type: ignore[assignment]

    app.spot_price = 102.4

    app.securityDefinitionOptionParameter(
        1,
        "SMART",
        1,
        "ABC",
        "100",
        {"20240105", "20240119", "20240112"},
        {95.0, 100.0},
    )

    app.securityDefinitionOptionParameter(
        1,
        "SMART",
        1,
        "ABC",
        "100",
        {"20240126", "20240202", "20240216", "20240315", "20240419"},
        {90.0, 110.0, 105.0, 115.0},
    )

    app.securityDefinitionOptionParameterEnd(1)

    all_exps = {
        "20240105",
        "20240119",
        "20240112",
        "20240126",
        "20240202",
        "20240216",
        "20240315",
        "20240419",
    }
    regulars, weeklies = split_expiries(sorted(all_exps))
    expected_expiries = regulars + weeklies

    assert app.expiries == expected_expiries
    assert app.strikes == [90.0, 95.0, 100.0, 105.0, 110.0, 115.0]
    assert calls == []
    assert app.option_params_event.is_set()
