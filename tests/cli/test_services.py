import importlib
from datetime import datetime
from pathlib import Path


def test_fetch_polygon_chain_returns_path(monkeypatch, tmp_path):
    services = importlib.import_module("tomic.cli.services")

    # configure export dir
    monkeypatch.setattr(
        services.cfg,
        "get",
        lambda name, default=None: str(tmp_path) if name == "EXPORT_DIR" else default,
    )

    # fixed datetime
    class FakeDT(datetime):
        @classmethod
        def now(cls):
            return datetime(2024, 1, 2)

    monkeypatch.setattr(services, "datetime", FakeDT)

    created = []

    def fake_fetch(symbol):
        d = tmp_path / FakeDT.now().strftime("%Y%m%d")
        d.mkdir(exist_ok=True)
        f = d / f"{symbol}_123-optionchainpolygon.csv"
        f.write_text("data")
        created.append(f)

    monkeypatch.setattr(services, "fetch_polygon_option_chain", fake_fetch)

    path = services.fetch_polygon_chain("XYZ")
    assert path == created[0]


def test_git_commit_no_changes(monkeypatch, tmp_path):
    services = importlib.import_module("tomic.cli.services")

    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return type("R", (), {"stdout": ""})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr(services, "subprocess", type("S", (), {"run": fake_run}))

    result = services.git_commit("msg", tmp_path)
    assert result is False
    assert ["git", "status", "--short"] in commands


def test_git_commit_with_changes(monkeypatch, tmp_path):
    services = importlib.import_module("tomic.cli.services")

    file1 = tmp_path / "a.json"
    file1.write_text("{}")

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return type("R", (), {"stdout": " M a.json"})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr(services, "subprocess", type("S", (), {"run": fake_run}))

    result = services.git_commit("msg", tmp_path)
    assert result is True

