import importlib
from pathlib import Path
from tomic.journal.utils import save_json


def test_earnings_info(monkeypatch, tmp_path, capsys):
    mod = importlib.import_module("tomic.cli.earnings_info")

    sum_dir = tmp_path / "sum"
    sum_dir.mkdir()
    earn_file = tmp_path / "earn.json"

    save_json(
        [
            {"date": "2025-07-02", "atm_iv": 0.5, "iv_rank (HV)": 40.0},
            {"date": "2025-07-05", "atm_iv": 0.6, "iv_rank (HV)": 50.0},
        ],
        sum_dir / "AAA.json",
    )
    save_json({"AAA": ["2025-07-05", "2025-04-01"]}, earn_file)

    monkeypatch.setenv("TOMIC_TODAY", "2025-07-02")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: ["AAA"]
        if name == "DEFAULT_SYMBOLS"
        else str(sum_dir)
        if name == "IV_DAILY_SUMMARY_DIR"
        else str(earn_file)
        if name == "EARNINGS_DATES_FILE"
        else default,
    )

    monkeypatch.setattr(__import__('builtins'), 'input', lambda *a: '')

    mod.main([])

    out = capsys.readouterr().out
    assert "AAA" in out
    assert "2025-07-05" in out
    assert "Strategie" in out


def test_earnings_info_fallback(monkeypatch, tmp_path, capsys):
    mod = importlib.import_module("tomic.cli.earnings_info")

    sum_dir = tmp_path / "sum2"
    sum_dir.mkdir()
    earn_file = tmp_path / "earn2.json"

    save_json(
        [
            {"date": "2025-07-02", "atm_iv": 0.4, "iv_rank (HV)": 30.0},
            {"date": "2025-07-03", "atm_iv": 0.45, "iv_rank (HV)": 35.0},
        ],
        sum_dir / "BBB.json",
    )
    save_json({"BBB": ["2025-07-05"]}, earn_file)

    monkeypatch.setenv("TOMIC_TODAY", "2025-07-04")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: ["BBB"]
        if name == "DEFAULT_SYMBOLS"
        else str(sum_dir)
        if name == "IV_DAILY_SUMMARY_DIR"
        else str(earn_file)
        if name == "EARNINGS_DATES_FILE"
        else default,
    )

    monkeypatch.setattr(__import__('builtins'), 'input', lambda *a: '')

    mod.main([])

    out = capsys.readouterr().out
    assert "BBB" in out
    assert "07-03" in out  # date of IV record used
    assert "Strategie" in out


def test_earnings_info_skip_when_no_iv(monkeypatch, tmp_path, capsys):
    mod = importlib.import_module("tomic.cli.earnings_info")

    sum_dir = tmp_path / "sum3"
    sum_dir.mkdir()
    earn_file = tmp_path / "earn3.json"

    save_json(
        [
            {"date": "2025-07-06", "atm_iv": 0.55, "iv_rank (HV)": 60.0},
        ],
        sum_dir / "CCC.json",
    )
    save_json({"CCC": ["2025-07-08"]}, earn_file)

    monkeypatch.setenv("TOMIC_TODAY", "2025-07-05")
    monkeypatch.setattr(
        mod,
        "cfg_get",
        lambda name, default=None: ["CCC"]
        if name == "DEFAULT_SYMBOLS"
        else str(sum_dir)
        if name == "IV_DAILY_SUMMARY_DIR"
        else str(earn_file)
        if name == "EARNINGS_DATES_FILE"
        else default,
    )

    monkeypatch.setattr(__import__('builtins'), 'input', lambda *a: '')

    mod.main([])

    out = capsys.readouterr().out
    assert "CCC" not in out
