from tomic.cli.strategy_dashboard import generate_exit_alerts, print_strategy_alerts


def test_print_strategy_alerts_dte(capsys):
    strategy = {"symbol": "XYZ", "type": "Test", "alerts": ["⏳ 5 DTE"]}
    print_strategy_alerts(strategy)
    captured = capsys.readouterr().out
    assert "⏳ 5 DTE" in captured
    assert "🚨 XYZ – Test" in captured


def test_print_strategy_alerts_exit(capsys):
    strategy = {"symbol": "XYZ", "type": "Test", "spot": 90.0}
    rule = {"spot_below": 100}
    generate_exit_alerts(strategy, rule)
    print_strategy_alerts(strategy)
    captured = capsys.readouterr().out
    assert "onder exitniveau 100" in captured
