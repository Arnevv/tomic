import importlib
import builtins
import json
import types
from datetime import datetime, timedelta
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


def test_process_chain_refreshes_spot_price(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    # expose nested _process_chain function
    proc = None
    for const in mod.run_portfolio_menu.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "_process_chain":
            def _cell(value):
                return (lambda x: lambda: x)(value).__closure__[0]

            cells = []
            for name in const.co_freevars:
                cells.append(_cell(lambda *_a, **_k: None))
            proc = types.FunctionType(
                const,
                mod.run_portfolio_menu.__globals__,
                None,
                None,
                tuple(cells),
            )
            break
    assert proc is not None
    mod._process_chain = proc

    csv_path = tmp_path / "chain.csv"
    csv_path.write_text("dummy")

    class SimpleDF:
        def __init__(self):
            self.columns = ["expiry"]
            self._data = {"expiry": ["2024-01-01"]}

        def __getitem__(self, key):
            return self._data[key]

        def __setitem__(self, key, val):
            self._data[key] = val

        def to_dict(self, orient=None):
            return [
                {k: v[0] if isinstance(v, list) else v for k, v in self._data.items()}
            ]

        def __len__(self):
            return len(next(iter(self._data.values())))

    df = SimpleDF()

    class DummyPD:
        def read_csv(self, path):
            return df

        def to_datetime(self, series, errors=None):
            class _DT:
                def strftime(self, fmt):
                    return series

            return types.SimpleNamespace(dt=_DT())

    monkeypatch.setattr(mod, "pd", DummyPD())
    monkeypatch.setattr(mod, "normalize_european_number_format", lambda d, c: d)
    monkeypatch.setattr(mod, "calculate_csv_quality", lambda d: 100.0)
    monkeypatch.setattr(mod, "interpolate_missing_fields", lambda d: d)

    dummy_option = {
        "expiry": "2024-01-01",
        "mid": 1.0,
        "edge": 0.1,
        "pos": 0.2,
        "ev": 0.05,
        "type": "call",
        "strike": 100,
    }
    monkeypatch.setattr(mod, "filter_by_expiry", lambda data, rng: [dummy_option])
    monkeypatch.setattr(
        mod,
        "StrikeSelector",
        lambda config: type("S", (), {"select": lambda self, data, debug_csv=None: [dummy_option]})(),
    )
    monkeypatch.setattr(mod, "generate_strategy_candidates", lambda *a, **k: ([], None))
    monkeypatch.setattr(mod, "latest_atr", lambda s: 0.0)
    monkeypatch.setattr(mod, "_load_spot_from_metrics", lambda d, s: None)
    monkeypatch.setattr(mod, "_load_latest_close", lambda s: (111.0, "2024-01-01"))
    monkeypatch.setattr(mod, "normalize_leg", lambda rec: rec)
    monkeypatch.setattr(mod, "get_option_mid_price", lambda opt: opt.get("mid"))
    monkeypatch.setattr(mod, "calculate_pos", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_rom", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_edge", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_ev", lambda *a, **k: 0.0)

    def cfg_get(name, default=None):
        if name == "CSV_MIN_QUALITY":
            return 0
        if name == "PRICE_HISTORY_DIR":
            return str(tmp_path)
        return default

    monkeypatch.setattr(mod.cfg, "get", cfg_get)

    meta_store: dict[str, str] = {}
    monkeypatch.setattr(mod, "load_price_meta", lambda: meta_store.copy())
    monkeypatch.setattr(mod, "save_price_meta", lambda m: meta_store.update(m))

    real_dt = datetime
    class DummyDateTime:
        def __init__(self):
            self.current = real_dt(2024, 1, 1)

        def now(self):
            self.current += timedelta(minutes=11)
            return self.current

        def fromisoformat(self, s):
            return real_dt.fromisoformat(s)

    monkeypatch.setattr(mod, "datetime", DummyDateTime())

    import tomic.polygon_client as poly_mod
    prices = iter([101.0, 202.0])
    monkeypatch.setattr(poly_mod.PolygonClient, "connect", lambda self: None)
    monkeypatch.setattr(poly_mod.PolygonClient, "disconnect", lambda self: None)
    monkeypatch.setattr(
        poly_mod.PolygonClient,
        "fetch_spot_price",
        lambda self, sym: next(prices),
    )

    prompts = iter([True, False, False, True])
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: next(prompts))

    mod.SESSION_STATE.clear()
    mod.SESSION_STATE.update({"evaluated_trades": [], "symbol": "AAA"})

    mod._process_chain(csv_path)

    assert mod.SESSION_STATE.get("spot_price") == 202.0


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

    proposal = StrategyProposal(
        legs=[], credit=0.0, profit_estimated=True, scenario_info={"foo": "bar"}
    )

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
    assert data["metrics"]["profit_estimated"] is True
    assert data["metrics"]["scenario_info"] == {"foo": "bar"}


def _extract_show_details(mod):
    """Return the nested _show_proposal_details function."""
    def _cell(value):
        return (lambda x: lambda: x)(value).__closure__[0]

    for const in mod.run_portfolio_menu.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "_show_proposal_details":
            cells = []
            for name in const.co_freevars:
                if name == "_export_proposal_csv":
                    cells.append(_cell(lambda *_a, **_k: None))
                elif name == "_export_proposal_json":
                    cells.append(_cell(lambda *_a, **_k: None))
                else:  # _proposal_journal_text
                    cells.append(_cell(lambda *_a, **_k: ""))
            return types.FunctionType(
                const,
                mod.run_portfolio_menu.__globals__,
                None,
                None,
                tuple(cells),
            )
    return None


def test_show_proposal_details_suffix(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: False)
    proposal = StrategyProposal(
        legs=[],
        rom=10.0,
        ev=5.0,
        profit_estimated=True,
        scenario_info={"scenario_label": "Foo"},
    )
    show(proposal)
    out = capsys.readouterr().out
    assert "ROM: 10.00 Foo (geschat)" in out
    assert "EV: 5.00 Foo (geschat)" in out


def test_show_proposal_details_no_scenario(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: False)
    proposal = StrategyProposal(
        legs=[],
        rom=1.0,
        ev=2.0,
        profit_estimated=False,
        scenario_info={"error": "no scenario defined"},
    )
    show(proposal)
    out = capsys.readouterr().out
    assert "no scenario defined" in out
