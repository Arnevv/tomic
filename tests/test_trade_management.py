import builtins
import importlib


def _setup(monkeypatch, tmp_path, strategies):
    tm = importlib.import_module("tomic.cli.trade_management")
    positions = tmp_path / "positions.json"
    journal = tmp_path / "journal.json"
    positions.write_text("[]")
    journal.write_text("[]")
    monkeypatch.setattr(
        tm,
        "cfg_get",
        lambda name, default=None: str(positions if name == "POSITIONS_FILE" else journal),
    )
    monkeypatch.setattr(tm, "group_strategies", lambda p, j: strategies)
    monkeypatch.setattr(tm, "extract_exit_rules", lambda jf: {})
    monkeypatch.setattr(tm, "generate_exit_alerts", lambda strat, rule: None)
    return tm


def test_exit_alert(monkeypatch, tmp_path, capsys):
    strategies = [
        {
            "symbol": "AAA",
            "type": "Strat",
            "spot": 100,
            "unrealizedPnL": 10,
            "days_to_expiry": 5,
            "alerts": ["exitniveau"],
            "expiry": "",
        }
    ]
    tm = _setup(monkeypatch, tmp_path, strategies)
    tm.main()
    out = capsys.readouterr().out
    assert "=== 📊 TRADE MANAGEMENT ===" in out
    assert "AAA" in out
    assert "exitniveau" in out
    assert "⚠️ Beheer nodig" in out


def test_no_alert(monkeypatch, tmp_path, capsys):
    strategies = [
        {
            "symbol": "AAA",
            "type": "Strat",
            "spot": 100,
            "unrealizedPnL": 10,
            "days_to_expiry": 5,
            "alerts": [],
            "expiry": "",
        }
    ]
    tm = _setup(monkeypatch, tmp_path, strategies)
    tm.main()
    out = capsys.readouterr().out
    assert "geen trigger" in out
    assert "✅ Houden" in out


def test_multiple_alerts(monkeypatch, tmp_path, capsys):
    strategies = [
        {
            "symbol": "AAA",
            "type": "Strat",
            "spot": 100,
            "unrealizedPnL": 10,
            "days_to_expiry": 5,
            "alerts": ["exitniveau", "PnL"],
            "expiry": "",
        },
        {
            "symbol": "BBB",
            "type": "Strat",
            "spot": 200,
            "unrealizedPnL": -5,
            "days_to_expiry": 10,
            "alerts": ["DTE ≤ exitdrempel"],
            "expiry": "",
        },
    ]
    tm = _setup(monkeypatch, tmp_path, strategies)
    tm.main()
    out = capsys.readouterr().out
    assert out.count("⚠️ Beheer nodig") == 2
    assert "exitniveau | PnL" in out
