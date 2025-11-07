import types

from tomic.cli.controlpanel import portfolio_ui


def test_tws_menu_option_reports_disabled(capsys):
    session = portfolio_ui.ControlPanelSession()
    services = types.SimpleNamespace()

    portfolio_ui._process_exported_chain(session, services)

    captured = capsys.readouterr()
    assert "TWS option-chain fetch is uitgeschakeld" in captured.out
