import importlib


def test_bs_calculator_main(capsys):
    mod = importlib.import_module("tomic.cli.bs_calculator")
    mod.main(["C", "100", "90", "30", "0.2", "0.045", "0"])
    out = capsys.readouterr().out
    assert "Theoretical value" in out
    assert "Intrinsic value" in out


def test_bs_calculator_with_midprice(capsys):
    mod = importlib.import_module("tomic.cli.bs_calculator")
    mod.main(["C", "100", "90", "30", "0.2", "0.045", "0", "25"])
    out = capsys.readouterr().out
    assert "Edge op basis" in out
