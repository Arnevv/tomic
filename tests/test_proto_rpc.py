# ruff: noqa: E402
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


from tomic.proto import rpc, tws_daemon, job_status


def test_submit_task_creates_files(tmp_path, monkeypatch):
    setup_ib_stubs(monkeypatch)
    monkeypatch.setattr(rpc, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rpc, "STATUS_DIR", rpc.JOBS_DIR / "status")
    monkeypatch.setattr(rpc, "INDEX_FILE", rpc.JOBS_DIR / "index.json")
    rpc.JOBS_DIR.mkdir(parents=True)
    rpc.STATUS_DIR.mkdir(parents=True)
    rpc.INDEX_FILE.write_text("[]")
    monkeypatch.setattr(rpc, "TASK_QUEUE", Queue())

    job_id = rpc.submit_task({"type": "get_market_data", "symbol": "XYZ"})
    job_files = [p for p in rpc.JOBS_DIR.glob("*.json") if p.name != "index.json"]
    index_path = rpc.INDEX_FILE
    status_files = list(rpc.STATUS_DIR.glob("*.json"))
    assert index_path.exists()
    assert len(job_files) == 1
    assert len(status_files) == 1
    assert job_files[0].stem == job_id
    assert status_files[0].stem == job_id
    data = json.loads(job_files[0].read_text())
    status = json.loads(status_files[0].read_text())
    assert data["id"] == job_id
    assert status["state"] == "queued"
    index = json.loads(rpc.INDEX_FILE.read_text())
    assert index[0]["job_id"] == job_id
    assert index[0]["status"] == "queued"


def test_daemon_updates_status(tmp_path, monkeypatch):
    setup_ib_stubs(monkeypatch)
    monkeypatch.setattr(rpc, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rpc, "STATUS_DIR", rpc.JOBS_DIR / "status")
    monkeypatch.setattr(rpc, "INDEX_FILE", rpc.JOBS_DIR / "index.json")
    rpc.JOBS_DIR.mkdir(parents=True)
    rpc.STATUS_DIR.mkdir(parents=True)
    rpc.INDEX_FILE.write_text("[]")
    queue = Queue()
    monkeypatch.setattr(rpc, "TASK_QUEUE", queue)
    job_id = rpc.submit_task({"type": "get_market_data", "symbol": "ABC"})
    status_path = rpc.STATUS_DIR / f"{job_id}.json"
    (rpc.JOBS_DIR / f"{job_id}.json").unlink()  # avoid double processing

    states = []

    def fake_export(symbol, output_dir=None):
        states.append(json.loads(status_path.read_text())["state"])

    monkeypatch.setattr(tws_daemon, "export_market_data", fake_export)

    class DummyProcess:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            pass

    monkeypatch.setattr(tws_daemon, "Process", DummyProcess)

    manager = tws_daemon.TwsSessionManager()

    def stop(_):
        raise SystemExit

    monkeypatch.setattr(tws_daemon.time, "sleep", stop)
    with pytest.raises(SystemExit):
        manager._run()

    assert states == ["running"]
    assert json.loads(status_path.read_text())["state"] == "completed"
    index = json.loads(rpc.INDEX_FILE.read_text())
    assert index[0]["status"] == "completed"


def test_job_status_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(job_status, "STATUS_DIR", tmp_path)
    path = tmp_path / "123.json"
    path.write_text(json.dumps({"state": "completed"}))

    output = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: output.append(" ".join(str(x) for x in a))
    )
    assert job_status.main(["123"]) == 0
    assert output == ["completed"]
