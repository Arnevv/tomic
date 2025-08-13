import importlib
import builtins
import json
import types
from datetime import datetime
from pathlib import Path
from tomic.journal.utils import save_json
from tomic.strategy_candidates import StrategyProposal


def test_show_market_info(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    sum_dir = tmp_path / "sum"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for p in (sum_dir, hv_dir, spot_dir):
        p.mkdir()

    earn_file = tmp_path / "earnings_dates.json"
    save_json({"AAA": ["2030-01-01"]}, earn_file)

    save_json(
        [
            {"date": "2025-06-28", "close": 534.5},
            {"date": "2025-06-27", "close": 530.1},
        ],
        spot_dir / "AAA.json",
    )
    save_json(
        [
            {
                "date": "2025-06-27",
                "atm_iv": 0.4,
                "iv_rank (HV)": 55.0,
                "iv_percentile (HV)": 70.0,
                "term_m1_m2": 1.2,
                "term_m1_m3": 1.2,
                "skew": 4.0,
            }
        ],
        sum_dir / "AAA.json",
    )
    save_json([
        {"date": "2025-06-27", "hv20": 0.2, "hv30": 0.3, "hv90": 0.3, "hv252": 0.25}
    ], hv_dir / "AAA.json")

    pos_file = tmp_path / "p.json"
    pos_file.write_text("[]")
    monkeypatch.setattr(mod, "POSITIONS_FILE", pos_file)

    monkeypatch.setattr(
        mod.cfg,
        "get",
        lambda key, default=None: ["AAA"]
        if key == "DEFAULT_SYMBOLS"
        else (
            str(sum_dir)
            if key == "IV_DAILY_SUMMARY_DIR"
            else (
                str(hv_dir)
                if key == "HISTORICAL_VOLATILITY_DIR"
                else (
                    str(spot_dir)
                    if key == "PRICE_HISTORY_DIR"
                    else (
                        str(earn_file)
                        if key == "EARNINGS_DATES_FILE"
                        else default
                    )
                )
            )
        ),
    )

    prints = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    inputs = iter(["5", "0", "7"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))
    mod.run_portfolio_menu()

    assert any("2030-01-01" in line for line in prints)
    assert any("short_put_spread" in line for line in prints)


def test_export_proposal_json_includes_earnings(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    earn_file = tmp_path / "earnings_dates.json"
    save_json({"AAA": ["2030-01-01"]}, earn_file)

    def cfg_get(key, default=None):
        if key == "EARNINGS_DATES_FILE":
            return str(earn_file)
        if key == "EXPORT_DIR":
            return str(tmp_path)
        return default

    monkeypatch.setattr(mod.cfg, "get", cfg_get)

    mod.SESSION_STATE["symbol"] = "AAA"
    mod.SESSION_STATE["strategy"] = "test_strategy"
    mod.SESSION_STATE["spot_price"] = 100.0

    proposal = StrategyProposal(legs=[], credit=0.0)

    def _cell(value):
        return (lambda x: lambda: x)(value).__closure__[0]

    export_func = None
    for const in mod.run_portfolio_menu.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "_export_proposal_json":
            cells = []
            for name in const.co_freevars:
                if name == "_load_acceptance_criteria":
                    cells.append(_cell(lambda *_a, **_k: {}))
                elif name == "_load_portfolio_context":
                    cells.append(_cell(lambda *_a, **_k: ({}, False)))
                else:
                    cells.append(_cell(None))
            export_func = types.FunctionType(
                const,
                mod.run_portfolio_menu.__globals__,
                None,
                None,
                tuple(cells),
            )
            break
    assert export_func is not None

    export_func(proposal)

    out_dir = tmp_path / datetime.now().strftime("%Y%m%d")
    files = list(out_dir.glob("strategy_proposal_AAA_test_strategy_*.json"))
    assert files, "export file not created"
    data = json.loads(files[0].read_text())
    assert data["next_earnings_date"] == "2030-01-01"
