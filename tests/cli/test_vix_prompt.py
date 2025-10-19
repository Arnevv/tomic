import builtins

from tomic.cli.vix_prompt import prompt_manual_vix


def test_prompt_manual_vix_returns_float(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _: "18,42")
    value = prompt_manual_vix()
    assert value is not None and abs(value - 18.42) < 1e-6


def test_prompt_manual_vix_empty_returns_none(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _: "  ")
    assert prompt_manual_vix() is None


def test_prompt_manual_vix_invalid_value(monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", lambda _: "foo")
    assert prompt_manual_vix() is None
    captured = capsys.readouterr()
    assert "Ongeldige waarde" in captured.out
