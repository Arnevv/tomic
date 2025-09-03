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


def test_print_strategy_alerts_expiry_rule(capsys):
    strategy = {"symbol": "XYZ", "type": "Test", "days_to_expiry": 5}
    rule = {"days_before_expiry": 10}
    generate_exit_alerts(strategy, rule)
    print_strategy_alerts(strategy)
    captured = capsys.readouterr().out
    assert "⚠️ 5 DTE ≤ exitdrempel 10" in captured


def test_print_strategy_alerts_days_in_trade_rule(capsys):
    strategy = {"symbol": "XYZ", "type": "Test", "days_in_trade": 12}
    rule = {"max_days_in_trade": 10}
    generate_exit_alerts(strategy, rule)
    print_strategy_alerts(strategy)
    captured = capsys.readouterr().out
    assert "12 dagen in trade" in captured
