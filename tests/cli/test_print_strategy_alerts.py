from tomic.cli.strategy_dashboard import print_strategy_alerts


def test_print_strategy_alerts_dte(capsys):
    strategy = {"symbol": "XYZ", "type": "Test", "alerts": ["⏳ 5 DTE"]}
    print_strategy_alerts(strategy)
    captured = capsys.readouterr().out
    assert "⏳ 5 DTE" in captured
    assert "🚨 XYZ – Test" in captured
