import json
import builtins
from multiprocessing import Queue
import sys
import types

# Stub dependencies so modules import without the real packages present
contract_stub = types.ModuleType("ibapi.contract")
contract_stub.Contract = type("Contract", (), {})
contract_stub.ContractDetails = type("ContractDetails", (), {})
client_stub = types.ModuleType("ibapi.client")
client_stub.EClient = type("EClient", (), {})
wrapper_stub = types.ModuleType("ibapi.wrapper")
wrapper_stub.EWrapper = type("EWrapper", (), {})
ticktype_stub = types.ModuleType("ibapi.ticktype")
ticktype_stub.TickTypeEnum = type("TickTypeEnum", (), {})
common_stub = types.ModuleType("ibapi.common")
common_stub.TickerId = int
ibapi_pkg = types.ModuleType("ibapi")
sys.modules["ibapi"] = ibapi_pkg
sys.modules["pandas"] = types.ModuleType("pandas")
sys.modules["ibapi.contract"] = contract_stub
sys.modules["ibapi.client"] = client_stub
sys.modules["ibapi.wrapper"] = wrapper_stub
sys.modules["ibapi.ticktype"] = ticktype_stub
sys.modules["ibapi.common"] = common_stub
ibapi_pkg.contract = contract_stub
ibapi_pkg.client = client_stub
ibapi_pkg.wrapper = wrapper_stub
ibapi_pkg.ticktype = ticktype_stub
ibapi_pkg.common = common_stub

import pytest
from tomic.proto import rpc
from tomic.cli import daemonctl


def setup_ib_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    contract_stub = types.ModuleType("ibapi.contract")
    contract_stub.Contract = type("Contract", (), {})
    contract_stub.ContractDetails = type("ContractDetails", (), {})
    client_stub = types.ModuleType("ibapi.client")
    wrapper_stub = types.ModuleType("ibapi.wrapper")
    client_stub.EClient = type("EClient", (), {})
    wrapper_stub.EWrapper = type("EWrapper", (), {})
    ticktype_stub = types.ModuleType("ibapi.ticktype")
    ticktype_stub.TickTypeEnum = type("TickTypeEnum", (), {})
    common_stub = types.ModuleType("ibapi.common")
    common_stub.TickerId = int
    monkeypatch.setitem(sys.modules, "ibapi.contract", contract_stub)
    monkeypatch.setitem(sys.modules, "ibapi.client", client_stub)
    monkeypatch.setitem(sys.modules, "ibapi.wrapper", wrapper_stub)
    monkeypatch.setitem(sys.modules, "ibapi.ticktype", ticktype_stub)
    monkeypatch.setitem(sys.modules, "ibapi.common", common_stub)
    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))


def setup_paths(tmp_path, monkeypatch):
    setup_ib_stubs(monkeypatch)
    monkeypatch.setattr(rpc, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rpc, "STATUS_DIR", rpc.JOBS_DIR / "status")
    monkeypatch.setattr(rpc, "INDEX_FILE", rpc.JOBS_DIR / "index.json")
    monkeypatch.setattr(daemonctl.tws_daemon, "LOG_FILE", rpc.JOBS_DIR / "daemon.log")
    rpc.JOBS_DIR.mkdir(parents=True)
    rpc.STATUS_DIR.mkdir(parents=True)
    rpc.INDEX_FILE.write_text("[]")
    monkeypatch.setattr(rpc, "TASK_QUEUE", Queue())


def test_daemonctl_ls(tmp_path, monkeypatch):
    setup_paths(tmp_path, monkeypatch)
    rpc.submit_task({"type": "get_market_data", "symbol": "XYZ"})
    out = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: out.append(" ".join(str(x) for x in a))
    )
    daemonctl.main(["ls", "--all"])
    assert any("XYZ" in line for line in out)


def test_daemonctl_retry(tmp_path, monkeypatch):
    setup_paths(tmp_path, monkeypatch)
    job_id = rpc.submit_task({"type": "get_market_data", "symbol": "XYZ"})
    # emulate failure
    rpc.update_index(job_id, status="failed")
    out = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: out.append(" ".join(str(x) for x in a))
    )
    assert daemonctl.main(["retry", job_id]) == 0
    assert any("requeued" in line for line in out)
    index = json.loads(rpc.INDEX_FILE.read_text())
    assert index[0]["status"] == "queued"


def test_daemonctl_done(tmp_path, monkeypatch):
    setup_paths(tmp_path, monkeypatch)
    job_id = rpc.submit_task({"type": "get_market_data", "symbol": "XYZ"})
    rpc.update_index(job_id, status="completed")
    out = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: out.append(" ".join(str(x) for x in a))
    )
    daemonctl.main(["done"])
    assert any("XYZ" in line for line in out)


def test_daemonctl_log(tmp_path, monkeypatch):
    setup_paths(tmp_path, monkeypatch)
    log_path = rpc.JOBS_DIR / "daemon.log"
    log_path.write_text("hello")
    out = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: out.append(" ".join(str(x) for x in a))
    )
    assert daemonctl.main(["log"]) == 0
    assert any("hello" in line for line in out)
