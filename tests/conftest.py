import sys
import types

# Provide dummy ibapi modules so imports succeed during tests
sys.modules.setdefault("ibapi", types.ModuleType("ibapi"))

client = types.ModuleType("ibapi.client")
setattr(client, "EClient", type("EClient", (), {}))
sys.modules.setdefault("ibapi.client", client)

wrapper = types.ModuleType("ibapi.wrapper")
setattr(wrapper, "EWrapper", type("EWrapper", (), {}))
sys.modules.setdefault("ibapi.wrapper", wrapper)

contract_mod = types.ModuleType("ibapi.contract")
setattr(contract_mod, "Contract", type("Contract", (), {}))
setattr(contract_mod, "ContractDetails", type("ContractDetails", (), {}))
sys.modules.setdefault("ibapi.contract", contract_mod)

ticktype_mod = types.ModuleType("ibapi.ticktype")
setattr(ticktype_mod, "TickTypeEnum", type("TickTypeEnum", (), {}))
sys.modules.setdefault("ibapi.ticktype", ticktype_mod)

common_mod = types.ModuleType("ibapi.common")
setattr(common_mod, "TickerId", int)
sys.modules.setdefault("ibapi.common", common_mod)
