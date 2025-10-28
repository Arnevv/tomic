from __future__ import annotations

from types import SimpleNamespace

import pytest

from tomic.cli import module_runner


def test_run_module_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    command = []

    def fake_run(cmd, check=False):
        command.extend(cmd)
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module_runner.subprocess, "run", fake_run)

    exit_code = module_runner.run_module("dummy.module", "--flag", "value")

    assert exit_code == 0
    assert command[2:] == ["dummy.module", "--flag", "value"]
    captured = capsys.readouterr()
    assert captured.err == ""


def test_run_module_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_run(cmd, check=False):
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(module_runner.subprocess, "run", fake_run)

    exit_code = module_runner.run_module("dummy.module")

    assert exit_code == 3
    captured = capsys.readouterr()
    assert "exit-code 3" in captured.err
    assert "dummy.module" in captured.err
