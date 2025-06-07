import json
import builtins
from multiprocessing import Queue

import pytest

from tomic.proto import rpc, tws_daemon, job_status


def test_submit_task_creates_files(tmp_path, monkeypatch):
    monkeypatch.setattr(rpc, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rpc, "STATUS_DIR", rpc.JOBS_DIR / "status")
    rpc.JOBS_DIR.mkdir(parents=True)
    rpc.STATUS_DIR.mkdir(parents=True)
    monkeypatch.setattr(rpc, "TASK_QUEUE", Queue())

    job_id = rpc.submit_task({"type": "get_market_data", "symbol": "XYZ"})
    job_files = list(rpc.JOBS_DIR.glob("*.json"))
    status_files = list(rpc.STATUS_DIR.glob("*.json"))
    assert len(job_files) == 1
    assert len(status_files) == 1
    assert job_files[0].stem == job_id
    assert status_files[0].stem == job_id
    data = json.loads(job_files[0].read_text())
    status = json.loads(status_files[0].read_text())
    assert data["id"] == job_id
    assert status["state"] == "queued"


def test_daemon_updates_status(tmp_path, monkeypatch):
    monkeypatch.setattr(rpc, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rpc, "STATUS_DIR", rpc.JOBS_DIR / "status")
    rpc.JOBS_DIR.mkdir(parents=True)
    rpc.STATUS_DIR.mkdir(parents=True)
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
