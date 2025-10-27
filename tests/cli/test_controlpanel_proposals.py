import builtins
import json
import importlib
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

import tomic.services.chain_processing as chain_services

from tomic.helpers.price_utils import ClosePriceSnapshot

from tomic.journal.utils import save_json, load_json
from tomic.strategy_candidates import StrategyProposal
from tomic.services.chain_processing import PreparedChain, ChainPreparationConfig
from tomic.services.ib_marketdata import SnapshotResult
from tomic.services.pipeline_refresh import (
    PipelineStats,
    Proposal as RefreshProposal,
    RefreshContext,
    RefreshParams,
    RefreshResult,
    RefreshSource,
    Rejection as RefreshRejection,
)
from tomic.services.market_snapshot_service import MarketSnapshot, MarketSnapshotRow


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
                "iv_rank (HV)": 0.55,
                "iv_percentile (HV)": 0.70,
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

    mod.MARKET_SNAPSHOT_SERVICE = mod.MarketSnapshotService(mod.cfg)

    monkeypatch.setattr(mod, "fetch_volatility_metrics", lambda *a, **k: {"vix": 19.5})

    rec = {
        "symbol": "AAA",
        "spot": 100.0,
        "iv": 0.25,
        "hv20": 0.2,
        "hv30": 0.21,
        "hv90": 0.22,
        "hv252": 0.23,
        "strategy": "short_put_spread",
        "greeks": "vega short",
        "indication": None,
        "criteria": "",
        "term_m1_m2": 1.0,
        "term_m1_m3": 1.1,
        "next_earnings": "2030-01-01",
        "iv_rank": 0.6,
        "iv_percentile": 0.55,
        "skew": 3.4,
        "category": "Vega Short",
    }
    table_rows = [
        [
            1,
            "AAA",
            "short_put_spread",
            "0.25",
            "Delta",
            "Vega",
            "Theta",
            "60",
            "3.4",
            "2030-01-01",
        ]
    ]
    monkeypatch.setattr(
        mod,
        "build_market_overview",
        lambda rows: ([rec], table_rows, {"earnings_filtered": {}}),
    )

    prints = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    inputs = iter(["5", "0", "7", "8"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))
    mod.run_portfolio_menu()

    assert any("2030-01-01" in line for line in prints)
    assert any("short_put_spread" in line for line in prints)
    assert any("VIX" in line for line in prints)


def test_market_info_polygon_scan(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    def cfg_get(key, default=None):
        if key == "DEFAULT_SYMBOLS":
            return ["AAA"]
        if key == "MARKET_SCAN_TOP_N":
            return 2
        if key == "EXPORT_DIR":
            return str(tmp_path)
        if key == "INTEREST_RATE":
            return 0.05
        return default

    monkeypatch.setattr(mod.cfg, "get", cfg_get)

    monkeypatch.setattr(
        mod.MARKET_SNAPSHOT_SERVICE,
        "load_snapshot",
        lambda params: MarketSnapshot(
            generated_at=date.today(),
            symbols=["AAA"],
            rows=[
                MarketSnapshotRow(
                    symbol="AAA",
                    spot=100.0,
                    iv=0.25,
                    hv20=0.2,
                    hv30=0.21,
                    hv90=0.22,
                    hv252=0.23,
                    iv_rank=0.6,
                    iv_percentile=0.55,
                    term_m1_m2=1.0,
                    term_m1_m3=1.1,
                    skew=3.4,
                    next_earnings=date(2030, 1, 1),
                )
            ],
        ),
    )

    monkeypatch.setattr(
        mod,
        "fetch_volatility_metrics",
        lambda *a, **k: {"vix": 19.5},
    )

    rec = {
        "symbol": "AAA",
        "spot": 100.0,
        "iv": 0.25,
        "hv20": 0.2,
        "hv30": 0.21,
        "hv90": 0.22,
        "hv252": 0.23,
        "strategy": "short_put_spread",
        "greeks": "vega short",
        "indication": None,
        "criteria": "",
        "term_m1_m2": 1.0,
        "term_m1_m3": 1.1,
        "next_earnings": "2030-01-01",
        "iv_rank": 0.6,
        "iv_percentile": 0.55,
        "skew": 3.4,
        "category": "Vega Short",
    }
    table_rows = [
        [
            1,
            "AAA",
            "short_put_spread",
            "0.25",
            "Delta",
            "Vega",
            "Theta",
            "60",
            "3.4",
            "2030-01-01",
        ]
    ]
    monkeypatch.setattr(
        mod,
        "build_market_overview",
        lambda rows: ([rec], table_rows, {"earnings_filtered": {}}),
    )

    prints: list[str] = []
    fetch_calls: list[str] = []

    def fake_fetch(symbol):
        fetch_calls.append(symbol)
        return tmp_path / "AAA_scan-optionchainpolygon.csv"

    monkeypatch.setattr(mod.services, "fetch_polygon_chain", fake_fetch)

    captured: dict[str, object] = {}

    class DummyScanService:
        def __init__(self, pipeline, portfolio_service, **kwargs):
            captured["init"] = kwargs

        def run_market_scan(self, requests, *, chain_source, top_n, refresh_quotes=False):
            captured["requests"] = list(requests)
            captured["top_n"] = top_n
            captured["paths"] = [chain_source(req.symbol) for req in requests]
            captured["refresh_quotes"] = refresh_quotes
            proposal = types.SimpleNamespace(
                score=12.34,
                ev=45.67,
                legs=[{"expiry": "2024-01-19", "strike": 100, "type": "put"}],
            )
            return [
                types.SimpleNamespace(
                    symbol="AAA",
                    strategy="short_put_spread",
                    proposal=proposal,
                    score=12.34,
                    ev=45.67,
                    risk_reward=1.5,
                    dte_summary="30",
                    iv_rank=0.6,
                    iv_percentile=0.55,
                    skew=3.4,
                    bid_ask_pct=0.02,
                    mid_sources=("advisory", "needs_refresh", "close:1"),
                    mid_status="advisory",
                    needs_refresh=True,
                    next_earnings=date(2030, 1, 1),
                    metrics={"iv_rank": 0.6, "iv_percentile": 0.55, "skew": 3.4},
                    spot=100.0,
                )
            ]

    monkeypatch.setattr(mod, "MarketScanService", DummyScanService)

    def _menu_run(self):
        for desc, handler in self.items:
            if desc == "Toon marktinformatie":
                handler()
                break

    monkeypatch.setattr(mod.Menu, "run", _menu_run)

    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    inputs = iter(["999", "", "", "0"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))

    mod.run_portfolio_menu()

    assert fetch_calls == ["AAA"], prints
    assert captured["init"].get("refresh_snapshot") is mod.portfolio_services.refresh_proposal_from_ib
    assert captured["top_n"] == 2
    assert captured["refresh_quotes"] is True
    assert captured["paths"] == [tmp_path / "AAA_scan-optionchainpolygon.csv"]
    assert any("Bid/Ask%" in line for line in prints), prints
    assert any("12.34" in line for line in prints), prints
    assert any("close" in line for line in prints), prints


def test_market_info_polygon_scan_existing_dir(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    def cfg_get(key, default=None):
        if key == "DEFAULT_SYMBOLS":
            return ["AAA"]
        if key == "MARKET_SCAN_TOP_N":
            return 2
        if key == "EXPORT_DIR":
            return str(tmp_path)
        if key == "INTEREST_RATE":
            return 0.05
        return default

    monkeypatch.setattr(mod.cfg, "get", cfg_get)

    monkeypatch.setattr(
        mod.MARKET_SNAPSHOT_SERVICE,
        "load_snapshot",
        lambda params: MarketSnapshot(
            generated_at=date.today(),
            symbols=["AAA"],
            rows=[
                MarketSnapshotRow(
                    symbol="AAA",
                    spot=100.0,
                    iv=0.25,
                    hv20=0.2,
                    hv30=0.21,
                    hv90=0.22,
                    hv252=0.23,
                    iv_rank=0.6,
                    iv_percentile=0.55,
                    term_m1_m2=1.0,
                    term_m1_m3=1.1,
                    skew=3.4,
                    next_earnings=date(2030, 1, 1),
                )
            ],
        ),
    )

    monkeypatch.setattr(
        mod,
        "fetch_volatility_metrics",
        lambda *a, **k: {"vix": 19.5},
    )

    rec = {
        "symbol": "AAA",
        "spot": 100.0,
        "iv": 0.25,
        "hv20": 0.2,
        "hv30": 0.21,
        "hv90": 0.22,
        "hv252": 0.23,
        "strategy": "short_put_spread",
        "greeks": "vega short",
        "indication": None,
        "criteria": "",
        "term_m1_m2": 1.0,
        "term_m1_m3": 1.1,
        "next_earnings": "2030-01-01",
        "iv_rank": 0.6,
        "iv_percentile": 0.55,
        "skew": 3.4,
        "category": "Vega Short",
    }
    table_rows = [
        [
            1,
            "AAA",
            "short_put_spread",
            "0.25",
            "Delta",
            "Vega",
            "Theta",
            "60",
            "3.4",
            "2030-01-01",
        ]
    ]
    monkeypatch.setattr(
        mod,
        "build_market_overview",
        lambda rows: ([rec], table_rows, {"earnings_filtered": {}}),
    )

    existing_dir = tmp_path / "chains"
    existing_dir.mkdir()
    csv_path = existing_dir / "AAA_existing-optionchainpolygon.csv"
    csv_path.write_text("dummy")

    prints: list[str] = []
    fetch_calls: list[str] = []

    def fake_fetch(symbol):
        fetch_calls.append(symbol)
        raise AssertionError("fetch should not be called when using existing dir")

    monkeypatch.setattr(mod.services, "fetch_polygon_chain", fake_fetch)

    captured: dict[str, object] = {}

    class DummyScanService:
        def __init__(self, pipeline, portfolio_service, **kwargs):
            captured["init"] = kwargs

        def run_market_scan(self, requests, *, chain_source, top_n, refresh_quotes=False):
            captured["requests"] = list(requests)
            captured["top_n"] = top_n
            captured["paths"] = [chain_source(req.symbol) for req in requests]
            captured["refresh_quotes"] = refresh_quotes
            proposal = types.SimpleNamespace(
                score=12.34,
                ev=45.67,
                legs=[{"expiry": "2024-01-19", "strike": 100, "type": "put"}],
            )
            return [
                types.SimpleNamespace(
                    symbol="AAA",
                    strategy="short_put_spread",
                    proposal=proposal,
                    score=12.34,
                    ev=45.67,
                    risk_reward=1.5,
                    dte_summary="30",
                    iv_rank=0.6,
                    iv_percentile=0.55,
                    skew=3.4,
                    bid_ask_pct=0.02,
                    mid_sources=("advisory", "needs_refresh", "close:1"),
                    mid_status="advisory",
                    needs_refresh=True,
                    next_earnings=date(2030, 1, 1),
                    metrics={"iv_rank": 0.6, "iv_percentile": 0.55, "skew": 3.4},
                    spot=100.0,
                )
            ]

    monkeypatch.setattr(mod, "MarketScanService", DummyScanService)

    def _menu_run(self):
        for desc, handler in self.items:
            if desc == "Toon marktinformatie":
                handler()
                break

    monkeypatch.setattr(mod.Menu, "run", _menu_run)

    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))
    inputs = iter(["999", str(existing_dir), "", "0"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))

    mod.run_portfolio_menu()

    assert fetch_calls == []
    assert captured["init"].get("refresh_snapshot") is mod.portfolio_services.refresh_proposal_from_ib
    assert captured["paths"] == [csv_path]
    assert captured["refresh_quotes"] is True
    assert any("Bid/Ask%" in line for line in prints), prints
    assert any("12.34" in line for line in prints), prints
    assert any("close" in line for line in prints), prints

def test_market_info_reports_earnings_filter(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")

    def cfg_get(key, default=None):
        if key == "DEFAULT_SYMBOLS":
            return ["AAA"]
        return default

    monkeypatch.setattr(mod.cfg, "get", cfg_get)

    monkeypatch.setattr(
        mod.MARKET_SNAPSHOT_SERVICE,
        "load_snapshot",
        lambda params: MarketSnapshot(
            generated_at=date.today(),
            symbols=["AAA"],
            rows=[
                MarketSnapshotRow(
                    symbol="AAA",
                    spot=100.0,
                    iv=0.25,
                    hv20=0.2,
                    hv30=0.21,
                    hv90=0.22,
                    hv252=0.23,
                    iv_rank=0.6,
                    iv_percentile=0.55,
                    term_m1_m2=1.0,
                    term_m1_m3=1.1,
                    skew=3.4,
                    next_earnings=date(2030, 1, 1),
                    days_until_earnings=2,
                )
            ],
        ),
    )

    monkeypatch.setattr(
        mod,
        "fetch_volatility_metrics",
        lambda *a, **k: {"vix": 20.1},
    )

    monkeypatch.setattr(
        mod,
        "build_market_overview",
        lambda rows: (
            [],
            [],
            {"earnings_filtered": {"AAA": ["Iron Condor", "ATM Iron Butterfly"]}},
        ),
    )

    prints: list[str] = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    def _menu_run(self):
        for desc, handler in self.items:
            if desc == "Toon marktinformatie":
                handler()
                break

    monkeypatch.setattr(mod.Menu, "run", _menu_run)

    mod.run_portfolio_menu()

    assert any("earnings-filter" in line.lower() for line in prints)


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

    prepared = PreparedChain(
        path=csv_path,
        source_path=csv_path,
        dataframe=types.SimpleNamespace(),
        records=[],
        quality=100.0,
        interpolation_applied=False,
    )

    monkeypatch.setattr(
        mod.ChainPreparationConfig,
        "from_app_config",
        classmethod(lambda cls: ChainPreparationConfig(min_quality=0)),
    )
    monkeypatch.setattr(mod, "load_and_prepare_chain", lambda *a, **k: prepared)

    dummy_option = {
        "expiry": "2024-01-01",
        "mid": 1.0,
        "edge": 0.1,
        "pos": 0.2,
        "ev": 0.05,
        "type": "call",
        "strike": 100,
    }
    prepared.records = [dummy_option]
    monkeypatch.setattr(chain_services, "filter_by_expiry", lambda data, rng: [dummy_option])
    monkeypatch.setattr(mod, "filter_by_expiry", lambda data, rng: [dummy_option])
    monkeypatch.setattr(
        mod,
        "StrikeSelector",
        lambda config: type(
            "S",
            (),
            {
                "select": lambda self, data, debug_csv=None, return_info=False: (
                    ([dummy_option], {}, {}) if return_info else [dummy_option]
                )
            },
        )(),
    )
    monkeypatch.setattr(
        mod, "generate_strategy_candidates", lambda *a, **k: ([], ["r1", "r2"])
    )
    monkeypatch.setattr(mod, "latest_atr", lambda s: 0.0)
    monkeypatch.setattr(mod, "_load_spot_from_metrics", lambda d, s: None)
    monkeypatch.setattr(mod, "_load_latest_close", lambda s: ClosePriceSnapshot(111.0, "2024-01-01"))
    monkeypatch.setattr(mod, "normalize_leg", lambda rec: rec)
    monkeypatch.setattr(mod, "get_option_mid_price", lambda opt: (opt.get("mid"), False))
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

    meta_store: dict[str, dict[str, str]] = {}

    def load_meta():
        return {k: v.copy() for k, v in meta_store.items()}

    def save_meta(meta):
        meta_store.clear()
        for key, value in meta.items():
            if isinstance(value, dict):
                meta_store[key] = value.copy()
            else:
                meta_store[key] = value

    monkeypatch.setattr(mod, "load_price_meta", load_meta)
    monkeypatch.setattr(mod, "save_price_meta", save_meta)

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

    import tomic.integrations.polygon.client as poly_mod
    prices = iter([101.0, 202.0])
    monkeypatch.setattr(poly_mod.PolygonClient, "connect", lambda self: None)
    monkeypatch.setattr(poly_mod.PolygonClient, "disconnect", lambda self: None)
    monkeypatch.setattr(
        poly_mod.PolygonClient,
        "fetch_spot_price",
        lambda self, sym: next(prices),
    )

    responses = {
        "Doorgaan?": [True],
        "Wil je delta/iv interpoleren om de data te verbeteren?": [False],
        "Opslaan naar CSV?": [False],
        "Doorgaan naar strategie voorstellen?": [True],
        "Wil je een samenvatting van rejection reasons (y/n)?": [False, True],
        "Wil je meer details opvraagbaar per rij (y/n)?": [False, False],
    }

    def fake_prompt(question, default=False):
        assert question in responses, f"Unexpected prompt: {question}"
        queue = responses[question]
        assert queue, f"No responses left for: {question}"
        return queue.pop(0)

    monkeypatch.setattr(mod, "prompt_yes_no", fake_prompt)

    prints: list[str] = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a))
    )

    mod.SESSION_STATE.clear()
    mod.SESSION_STATE.update({"evaluated_trades": [], "symbol": "AAA"})

    mod._process_chain(csv_path)

    assert mod.SESSION_STATE.get("spot_price") == 202.0
    assert any(
        "Geen opties door filters afgewezen" in line for line in prints
    )
    by_strategy = getattr(mod.PIPELINE, "last_rejections", {}).get("by_strategy", {})
    combined = {
        reason.message for reasons in by_strategy.values() for reason in reasons
    }
    assert {"r1", "r2"}.issubset(combined)
    assert "AAA" in meta_store
    assert "fetched_at" in meta_store["AAA"]

    spot_path = tmp_path / "AAA_spot.json"
    assert spot_path.exists(), "spot cache should use _spot.json suffix"
    assert not (tmp_path / "AAA.json").exists(), "historical data file must remain untouched"
    assert load_json(spot_path).get("price") == 202.0


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

    monkeypatch.setattr(mod, "_load_acceptance_criteria", lambda *_a, **_k: {})
    monkeypatch.setattr(mod, "_load_portfolio_context", lambda: ({}, False))

    result_path = mod._export_proposal_json(proposal)

    assert result_path.exists(), "export file not created"
    assert result_path.parent.name == datetime.now().strftime("%Y%m%d")
    assert "AAA" in result_path.name
    assert "proposal" in result_path.name
    payload = json.loads(result_path.read_text())
    assert payload["data"]["next_earnings_date"] == "2030-01-01"
    metrics = payload["data"]["metrics"]
    assert metrics["profit_estimated"] is True
    assert metrics["scenario_info"] == {"foo": "bar"}


def _extract_show_details(mod):
    """Return the show details function for testing."""

    return getattr(mod, "_show_proposal_details", None)


def test_show_proposal_details_suffix(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    monkeypatch.setattr(
        mod,
        "fetch_quote_snapshot",
        lambda proposal, **_: SnapshotResult(proposal, [], True, []),
    )
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_export_proposal_csv", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_export_proposal_json", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_submit_ib_order", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "render_journal_entries", lambda *_a, **_k: [])
    proposal = StrategyProposal(
        legs=[],
        rom=10.0,
        ev=5.0,
        profit_estimated=True,
        scenario_info={"scenario_label": "Foo"},
    )
    show(proposal)
    out = capsys.readouterr().out
    assert "ROM         | 10.00     | Foo (geschat)" in out
    assert "EV          | 5.00      | Foo (geschat)" in out


def test_show_proposal_details_no_scenario(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    monkeypatch.setattr(
        mod,
        "fetch_quote_snapshot",
        lambda proposal, **_: SnapshotResult(proposal, [], True, []),
    )
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: False)
    monkeypatch.setattr(mod, "_export_proposal_csv", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_export_proposal_json", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_submit_ib_order", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "render_journal_entries", lambda *_a, **_k: [])
    proposal = StrategyProposal(
        legs=[],
        rom=1.0,
        ev=2.0,
        profit_estimated=False,
        scenario_info={"error": "no scenario defined"},
    )
    show(proposal)
    out = capsys.readouterr().out
    assert "Scenario fout | no scenario defined" in out


def test_show_proposal_details_blocks_on_acceptance(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    proposal = StrategyProposal(
        legs=[
            {
                "symbol": "AAA",
                "expiry": "2024-01-19",
                "strike": 100.0,
                "type": "put",
                "position": -1,
                "bid": 1.0,
                "ask": 1.2,
                "mid": 1.1,
                "edge": 0.2,
            }
        ],
        rom=5.0,
        ev=1.0,
    )
    reason = types.SimpleNamespace(message="ROM onder minimum", code="ROM_LOW")

    monkeypatch.setattr(
        mod,
        "fetch_quote_snapshot",
        lambda proposal, **_: SnapshotResult(proposal, [reason], False, ["100"]),
    )
    monkeypatch.setattr(mod, "_export_proposal_csv", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_export_proposal_json", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_submit_ib_order", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "render_journal_entries", lambda *_a, **_k: [])

    prompts: list[str] = []

    def _prompt(question, default=False):
        prompts.append(question)
        return True if "Haal orderinformatie" in question else False

    monkeypatch.setattr(mod, "prompt_yes_no", _prompt)
    mod.SESSION_STATE["symbol"] = "AAA"

    show(proposal)
    out = capsys.readouterr().out
    assert "❌ Acceptatiecriteria niet gehaald" in out
    assert "ROM onder minimum" in out
    assert any("Haal orderinformatie" in q for q in prompts)
    assert not any("Order naar IB" in q for q in prompts)


def test_show_proposal_details_retry_on_missing_bid_ask(monkeypatch, capsys, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")
    show = _extract_show_details(mod)
    assert show is not None
    session = mod._CONTEXT.session

    base_proposal = mod.StrategyProposal(
        strategy="iron_bfly",
        legs=[
            {
                "symbol": "AAA",
                "expiry": "2024-01-19",
                "strike": 100.0,
                "type": "call",
                "position": -1,
                "edge": 0.05,
            }
        ],
    )

    refreshed = [
        mod.StrategyProposal(
            strategy="iron_bfly",
            legs=[
                {
                    "symbol": "AAA",
                    "expiry": "2024-01-19",
                    "strike": 100.0,
                    "type": "call",
                    "position": -1,
                    "bid": 1.0,
                    "ask": None,
                    "mid": 1.0,
                    "edge": 0.05,
                }
            ],
        ),
        mod.StrategyProposal(
            strategy="iron_bfly",
            legs=[
                {
                    "symbol": "AAA",
                    "expiry": "2024-01-19",
                    "strike": 100.0,
                    "type": "call",
                    "position": -1,
                    "bid": 1.0,
                    "ask": 1.2,
                    "mid": 1.1,
                    "edge": 0.05,
                }
            ],
        ),
    ]

    refresh_iter = iter(refreshed)
    refresh_calls: list[object] = []

    def _refresh(proposal, **_):
        refresh_calls.append(proposal)
        updated = next(refresh_iter)
        return SnapshotResult(updated, [], True, [])

    monkeypatch.setattr(mod.portfolio_services, "refresh_proposal_from_ib", _refresh)

    def _export_csv(session, proposal):
        path = tmp_path / "proposal.csv"
        path.write_text("csv")
        return path

    def _export_json(session, proposal):
        path = tmp_path / "proposal.json"
        path.write_text("{}")
        return path

    monkeypatch.setattr(mod.portfolio_services, "export_proposal_to_csv", _export_csv)
    monkeypatch.setattr(mod.portfolio_services, "export_proposal_to_json", _export_json)
    monkeypatch.setattr(mod, "_submit_ib_order", lambda *_a, **_k: None)

    prompts: list[str] = []
    responses = iter([True, True, False, False, False])

    def _prompt(question, default=False):
        prompts.append(question)
        try:
            return next(responses)
        except StopIteration:
            return default

    monkeypatch.setattr(mod, "prompt_yes_no", _prompt)
    monkeypatch.setattr(mod.portfolio, "prompt_yes_no", _prompt)

    show(session, base_proposal)

    out = capsys.readouterr().out
    assert any("Bid/ask ontbreekt" in line for line in out.splitlines())
    assert any("Bid/ask data niet compleet" in question for question in prompts)
    retry_index = next(
        i for i, q in enumerate(prompts) if "Bid/ask data niet compleet" in q
    )
    csv_index = next(
        i for i, q in enumerate(prompts) if "Voorstel opslaan naar CSV" in q
    )
    assert retry_index < csv_index, "retry prompt should appear before export prompts"
    assert len(refresh_calls) == 2


def test_print_reason_summary_no_rejections(capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    mod._print_reason_summary(agg)
    out = capsys.readouterr().out
    assert "Geen opties door filters afgewezen" in out


def test_rejection_detail_offers_ib_fetch(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    entry = {
        "strategy": "iron_condor",
        "status": "reject",
        "description": "SC 490.0 SP 420.0 σ 1.0",
        "metrics": {
            "score": 66.41,
            "ev": 841.5,
            "rom": 0.7,
            "credit": 1656.3,
            "margin": 2343.7,
            "max_profit": 1656.3,
            "max_loss": -2343.7,
            "breakevens": [403.437, 506.563],
            "pos": 79.63,
        },
        "legs": [
            {
                "expiry": "2025-11-21",
                "type": "call",
                "strike": 490.0,
                "position": -1,
                "bid": 12.85,
                "ask": 13.0,
                "mid": 12.92,
            },
            {
                "expiry": "2025-11-21",
                "type": "put",
                "strike": 420.0,
                "position": -1,
                "bid": 6.45,
                "ask": 6.55,
                "mid": 6.50,
            },
        ],
        "meta": {"symbol": "SPY"},
    }

    prompts: list[str] = []
    selections = iter(["1", "0"])

    def fake_prompt(question: str, default: object | None = None):
        prompts.append(question)
        try:
            return next(selections)
        except StopIteration:
            return "0"

    called: list[tuple[object, object]] = []

    def fake_display(proposal, symbol_hint):
        called.append((proposal, symbol_hint))

    monkeypatch.setattr(mod, "prompt", fake_prompt)
    monkeypatch.setattr(mod, "_display_rejection_proposal", fake_display)

    original_symbol = mod.SESSION_STATE.get("symbol")
    original_strategy = mod.SESSION_STATE.get("strategy")
    mod.SESSION_STATE["symbol"] = "OLD"
    mod.SESSION_STATE["strategy"] = "old_strategy"
    try:
        mod._show_rejection_detail(entry)
    finally:
        if original_symbol is None:
            mod.SESSION_STATE.pop("symbol", None)
        else:
            mod.SESSION_STATE["symbol"] = original_symbol
        if original_strategy is None:
            mod.SESSION_STATE.pop("strategy", None)
        else:
            mod.SESSION_STATE["strategy"] = original_strategy

    capsys.readouterr()

    assert any("Kies actie" in q for q in prompts)
    assert called, "_display_rejection_proposal was not triggered"
    proposal, symbol_hint = called[0]
    assert isinstance(proposal, mod.StrategyProposal)
    assert proposal.strategy == "iron_condor"
    assert len(proposal.legs) == 2
    assert symbol_hint == "SPY"
    assert mod.SESSION_STATE.get("symbol") == original_symbol
    assert mod.SESSION_STATE.get("strategy") == original_strategy


def test_refresh_reject_entries_fetches_all(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    entries = [
        {
            "status": "reject",
            "strategy": "iron_condor",
            "metrics": {"score": 10.0},
            "legs": [
                {
                    "symbol": "AAA",
                    "expiry": "2025-11-21",
                    "type": "call",
                    "strike": 490.0,
                    "position": -1,
                }
            ],
            "meta": {"symbol": "AAA"},
        },
        {
            "status": "reject",
            "strategy": "short_put_spread",
            "metrics": {"score": 5.0},
            "legs": [
                {
                    "symbol": "BBB",
                    "expiry": "2025-12-19",
                    "type": "put",
                    "strike": 410.0,
                    "position": -1,
                }
            ],
            "meta": {"symbol": "BBB"},
        },
    ]

    captured: dict[str, object] = {}

    def fake_refresh(context: RefreshContext, *, params: RefreshParams) -> RefreshResult:
        captured["context"] = context
        captured["params"] = params
        accepted_proposal = mod.build_proposal_from_entry(entries[0])
        rejected_proposal = mod.build_proposal_from_entry(entries[1])
        assert accepted_proposal is not None
        assert rejected_proposal is not None
        accepted = RefreshProposal(
            proposal=accepted_proposal,
            source=RefreshSource(index=0, entry=entries[0], symbol="AAA"),
            reasons=[],
            missing_quotes=[],
        )
        rejection = RefreshRejection(
            source=RefreshSource(index=1, entry=entries[1], symbol="BBB"),
            proposal=rejected_proposal,
            reasons=[],
            missing_quotes=[],
            attempts=1,
        )
        stats = PipelineStats(
            total=2,
            accepted=1,
            rejected=1,
            failed=0,
            duration=0.05,
            attempts=2,
            retries=0,
        )
        return RefreshResult(accepted=[accepted], rejections=[rejection], stats=stats)

    monkeypatch.setattr(mod, "refresh_pipeline", fake_refresh)
    monkeypatch.setattr(mod, "load_criteria", lambda: {"dummy": True})
    monkeypatch.setattr(
        mod.cfg,
        "get",
        lambda key, default=None: 7 if key == "MARKET_DATA_TIMEOUT" else default,
    )

    original_spot = mod.SESSION_STATE.get("spot_price")
    mod.SESSION_STATE["spot_price"] = 123.45
    try:
        mod._refresh_reject_entries(entries)
    finally:
        if original_spot is None:
            mod.SESSION_STATE.pop("spot_price", None)
        else:
            mod.SESSION_STATE["spot_price"] = original_spot

    out = capsys.readouterr().out
    params = captured["params"]
    assert isinstance(params, RefreshParams)
    assert params.timeout == 7
    assert params.spot_price == 123.45
    assert entries[0]["refreshed_accepted"] is True
    assert entries[1]["refreshed_accepted"] is False
    assert entries[0]["refreshed_proposal"].strategy == "iron_condor"
    assert "Samenvatting" in out


def test_print_reason_summary_all_refresh(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    entries = [
        {
            "status": "reject",
            "strategy": "Wheel",
            "description": "Anchor A",
            "legs": [
                {"type": "call", "strike": 100, "expiry": "2024-01-19", "position": -1}
            ],
        },
        {
            "status": "reject",
            "strategy": "Iron Condor",
            "description": "Anchor B",
            "legs": [
                {"type": "put", "strike": 90, "expiry": "2024-01-26", "position": 1}
            ],
        },
    ]

    mod.SESSION_STATE["combo_evaluations"] = entries

    monkeypatch.setattr(mod, "SHOW_REASONS", True)

    prompts = iter(["a", "0"])
    monkeypatch.setattr(mod, "prompt", lambda *a, **k: next(prompts))

    called: list[int] = []
    monkeypatch.setattr(mod, "_refresh_reject_entries", lambda items: called.append(len(items)))

    mod._print_reason_summary(mod.RejectionSummary())

    assert called == [len(entries)]


def test_reason_aggregator_prefers_risk_over_fallback():
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    detail = agg.add_reason("model-mid gebruikt; risk/reward onvoldoende")
    assert detail.category == mod.ReasonCategory.RR_BELOW_MIN
    assert agg.by_reason[detail.message] == 1
    assert agg.by_category[mod.ReasonCategory.PREVIEW_QUALITY] == 1
    assert agg.by_category[mod.ReasonCategory.RR_BELOW_MIN] == 1


def test_reason_aggregator_retains_missing_mid_priority():
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    detail = agg.add_reason("midprijs niet gevonden; risk/reward onvoldoende")
    assert detail.category == mod.ReasonCategory.MISSING_DATA
    assert agg.by_reason[detail.message] == 1
    assert agg.by_category[mod.ReasonCategory.MISSING_DATA] == 1
    assert agg.by_category[mod.ReasonCategory.RR_BELOW_MIN] == 1


def test_reason_aggregator_normalizes_multiple_fragments():
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    details = agg._normalize_reason_list(
        "previewkwaliteit (parity_close); negatieve EV of score"
    )
    categories = {detail.category for detail in details}
    assert categories == {
        mod.ReasonCategory.PREVIEW_QUALITY,
        mod.ReasonCategory.EV_BELOW_MIN,
    }
    preview_detail = next(
        detail for detail in details if detail.category == mod.ReasonCategory.PREVIEW_QUALITY
    )
    assert preview_detail.data.get("mid_source") == "parity_close"


def test_reason_aggregator_counts_split_fragments():
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    inputs = [
        "previewkwaliteit (parity_close); negatieve EV of score",
        "previewkwaliteit (model), negatieve EV of score",
        "previewkwaliteit (close)\nnegatieve EV of score",
        "onbekend",
    ]
    for value in inputs:
        agg.add_reason(value)

    assert agg.by_category[mod.ReasonCategory.PREVIEW_QUALITY] == 3
    assert agg.by_category[mod.ReasonCategory.EV_BELOW_MIN] == 3
    assert agg.by_category.get(mod.ReasonCategory.OTHER, 0) == 1


def test_format_reject_reasons_uses_reject_counts():
    mod = importlib.import_module("tomic.cli.controlpanel")
    evaluations = [
        {
            "status": "reject",
            "reason": "previewkwaliteit (model); previewkwaliteit (parity_close); negatieve EV of score",
        },
        {
            "status": "reject",
            "reason": "previewkwaliteit (parity_close); negatieve EV of score",
        },
        {
            "status": "reject",
            "reason": "previewkwaliteit (parity_close); negatieve EV of score",
        },
    ]

    summary = mod.summarize_evaluations(evaluations)

    assert summary.reject_total == 3
    formatted = mod._format_reject_reasons(summary)
    assert "Datakwaliteit (fallback mid) (133%)" in formatted
    assert "EV onvoldoende (100%)" in formatted


def test_reason_aggregator_extends_reason_counts():
    mod = importlib.import_module("tomic.cli.controlpanel")
    agg = mod.ReasonAggregator()
    agg.extend_reason_counts(
        {
            mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY): 2,
            mod.ReasonCategory.LOW_LIQUIDITY: 3,
        }
    )
    assert agg.by_category[mod.ReasonCategory.PREVIEW_QUALITY] == 2
    assert agg.by_category[mod.ReasonCategory.LOW_LIQUIDITY] == 3


def test_generate_with_capture_records_summary(monkeypatch):
    mod = importlib.import_module("tomic.cli.controlpanel")

    active: dict[str, list[dict] | None] = {"captured": None}

    @contextmanager
    def fake_capture():
        captured: list[dict] = []
        active["captured"] = captured
        try:
            yield captured
        finally:
            active["captured"] = None

    def fake_generate(*args, **kwargs):
        assert active["captured"] is not None, "capture context not active"
        active["captured"].extend(
            [
                {
                    "status": "reject",
                    "legs": [{"expiry": "2024-01-19"}],
                    "raw_reason": "fallback naar close gebruikt voor midprijs",
                },
                {
                    "status": "reject",
                    "legs": [{"expiry": "2024-01-26"}],
                    "reason": mod.ReasonCategory.LOW_LIQUIDITY,
                },
                {
                    "status": "pass",
                    "legs": [{"expiry": "2024-01-19"}],
                },
            ]
        )
        return ([{"dummy": True}], [mod.ReasonCategory.LOW_LIQUIDITY])

    monkeypatch.setattr(mod, "capture_combo_evaluations", fake_capture)
    monkeypatch.setattr(mod, "generate_strategy_candidates", fake_generate)

    mod.SESSION_STATE["combo_evaluations"] = ["stale"]
    mod.SESSION_STATE["combo_evaluation_summary"] = object()

    proposals, reasons = mod._generate_with_capture("AAA", strategy="wheel")

    assert proposals == [{"dummy": True}]
    assert [mod.normalize_reason(r).message for r in reasons] == [
        mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY)
    ]

    captured = mod.SESSION_STATE["combo_evaluations"]
    assert isinstance(captured, list)
    assert len(captured) == 3

    summary = mod.SESSION_STATE["combo_evaluation_summary"]
    assert summary is not None
    assert summary.total == 3

    breakdown = summary.expiries.get("2024-01-19")
    assert breakdown.ok == 1 and breakdown.reject == 1

    other_breakdown = summary.expiries.get("2024-01-26")
    assert other_breakdown.ok == 0 and other_breakdown.reject == 1

    assert summary.reasons.by_category[mod.ReasonCategory.PREVIEW_QUALITY] == 1
    assert summary.reasons.by_category[mod.ReasonCategory.LOW_LIQUIDITY] == 1


def test_print_reason_summary_declines_all(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    responses = iter([False, False])
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: next(responses))
    monkeypatch.setattr(mod, "prompt", lambda *a, **k: "0")
    monkeypatch.setattr(mod, "SHOW_REASONS", False)

    entry = {
        "status": "reject",
        "strategy": "Wheel",
        "description": "Anchor",
        "legs": [{"type": "call", "strike": 100, "expiry": "2024-01-19", "position": -1}],
        "reason": mod.ReasonCategory.LOW_LIQUIDITY,
    }
    mod.SESSION_STATE["combo_evaluations"] = [entry]

    summary = mod.RejectionSummary(
        by_filter={"delta": 2},
        by_reason={"Volume/OI": 1},
        by_strategy={"wheel": ["Volume/OI"]},
    )

    mod._print_reason_summary(summary)

    out = capsys.readouterr().out
    assert out.strip() == ""


def test_print_reason_summary_summary_only(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    responses = iter([True, False])
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: next(responses))
    monkeypatch.setattr(mod, "prompt", lambda *a, **k: "0")
    monkeypatch.setattr(mod, "SHOW_REASONS", False)

    entry = {
        "status": "reject",
        "strategy": "Wheel",
        "description": "Anchor",
        "legs": [{"type": "call", "strike": 100, "expiry": "2024-01-19", "position": -1}],
        "reason": mod.ReasonCategory.LOW_LIQUIDITY,
    }
    mod.SESSION_STATE["combo_evaluations"] = [entry]

    summary = mod.RejectionSummary(
        by_filter={"delta": 2},
        by_reason={
            mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY): 1,
            mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY): 1,
        },
        by_strategy={
            "wheel": [
                mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY),
                mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY),
            ]
        },
    )

    mod._print_reason_summary(summary)

    out = capsys.readouterr().out
    assert "Afwijzingen per filter:" in out
    assert "| Filter" in out and "delta" in out
    assert "Redenen:" in out
    assert mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY) in out
    assert "Redenen per categorie:" in out
    assert "| Categorie" in out
    assert "50%" in out
    assert "wheel:" in out
    assert "Strat" not in out  # table with details should not be printed


def test_print_reason_summary_show_details(monkeypatch, capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")

    yes_no = iter([True, True])
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: next(yes_no))

    selections = iter(["1", "2", "0"])

    def fake_prompt(question, default=None):
        if "Kies actie" in question:
            return "0"
        try:
            return next(selections)
        except StopIteration:
            return "0"

    monkeypatch.setattr(mod, "prompt", fake_prompt)
    monkeypatch.setattr(mod, "SHOW_REASONS", True)

    entries = [
        {
            "status": "reject",
            "strategy": "Wheel",
            "description": "Anchor A",
            "legs": [
                {"type": "call", "strike": 100, "expiry": "2024-01-19", "position": -1},
                {"type": "put", "strike": 95, "expiry": "2024-01-19", "position": 1},
            ],
            "reason": mod.ReasonCategory.LOW_LIQUIDITY,
            "metrics": {
                "credit": 1.5,
                "pos": 60,
                "max_profit": 120,
                "max_loss": -60,
                "score": 25.123,
            },
            "meta": {"note": "illiquid"},
        },
        {
            "status": "reject",
            "strategy": "Iron Condor",
            "description": "Anchor B",
            "legs": [
                {"type": "call", "strike": 110, "expiry": "2024-01-26", "position": -1},
                {"type": "put", "strike": 90, "expiry": "2024-01-26", "position": 1},
            ],
            "raw_reason": "fallback naar close gebruikt voor midprijs",
            "metrics": {"net_credit": 0.85, "ev_pct": 12.345, "score": 70.5},
        },
    ]
    mod.SESSION_STATE["combo_evaluations"] = entries

    summary = mod.RejectionSummary(
        by_filter={"delta": 2},
        by_reason={
            mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY): 1,
            mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY): 1,
        },
        by_strategy={
            "wheel": [mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY)]
        },
    )

    mod._print_reason_summary(summary)

    out = capsys.readouterr().out
    assert "Afwijzingen per filter:" in out
    assert "| Strat" in out and "Anchor B" in out
    assert "|   Score |" in out
    assert "70.5" in out and "25.12" in out
    assert out.index("Iron Condor") < out.index("Wheel")
    assert "Redenen per categorie:" in out
    assert "Strategie: Iron Condor" in out
    assert "Anchor: Anchor B" in out
    assert "Reden: previewkwaliteit (close)" in out
    assert "Detail: fallback naar close gebruikt voor midprijs" in out
    assert "note=illiquid" in out or "Flags:" in out


def test_summarize_evaluations_normalizes_reasons():
    mod = importlib.import_module("tomic.cli.controlpanel")
    evaluations = [
        {
            "status": "reject",
            "legs": [{"expiry": "2024-01-19"}],
            "reason": mod.ReasonCategory.LOW_LIQUIDITY,
        },
        {
            "status": "pass",
            "legs": [{"expiry": "2024-01-19"}],
        },
        {
            "status": "reject",
            "legs": [{"expiry": "2024-01-26"}],
            "raw_reason": "fallback naar close gebruikt voor midprijs",
        },
    ]
    summary = mod.summarize_evaluations(evaluations)
    assert summary is not None
    assert summary.total == 3
    breakdown = {item.label: (item.ok, item.reject) for item in summary.sorted_expiries()}
    assert breakdown["2024-01-19"] == (1, 1)
    assert breakdown["2024-01-26"] == (0, 1)
    top = mod._format_reject_reasons(summary)
    assert mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY) in top
    assert mod.ReasonAggregator.label_for(mod.ReasonCategory.PREVIEW_QUALITY) in top
    assert "50%" in top


def test_format_leg_summary_positions():
    mod = importlib.import_module("tomic.cli.controlpanel")
    legs = [
        {"type": "call", "strike": 100, "position": -1},
        {"type": "put", "strike": "105", "position": 1},
        {"type": "call", "strike": None, "position": 0},
    ]
    assert mod._format_leg_summary(legs) == "SC 100, LP 105, LC"
    assert mod._format_leg_summary([]) == "—"


def test_print_evaluation_overview_formats(capsys):
    mod = importlib.import_module("tomic.cli.controlpanel")
    summary = mod.EvaluationSummary(total=2)
    summary.expiries["2024-01-19"] = mod.ExpiryBreakdown(
        label="2024-01-19",
        sort_key=datetime(2024, 1, 19).date(),
        ok=1,
        reject=1,
    )
    summary.reasons.by_category = {mod.ReasonCategory.LOW_LIQUIDITY: 2}
    mod._print_evaluation_overview("AAA", 123.456, summary)
    out = capsys.readouterr().out
    assert "Evaluatieoverzicht" in out
    assert "AAA" in out
    assert "123.46" in out
    assert "OK 1" in out
    assert mod.ReasonAggregator.label_for(mod.ReasonCategory.LOW_LIQUIDITY) in out


def _extract_process_chain(mod):
    proc = None
    for const in mod.run_portfolio_menu.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "_process_chain":
            def _cell(value):
                return (lambda x: lambda: x)(value).__closure__[0]

            cells = [_cell(lambda *_a, **_k: None) for _ in const.co_freevars]
            proc = types.FunctionType(
                const, mod.run_portfolio_menu.__globals__, None, None, tuple(cells)
            )
            break
    assert proc is not None
    return proc


def test_spot_from_chain_returns_value():
    from tomic.cli.controlpanel import _spot_from_chain

    chain = [{"underlying_price": 10.5}, {"close": 5}]
    assert _spot_from_chain(chain) == 10.5


def test_strategy_proposals_abort_on_missing_spot(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")
    mod._process_chain = _extract_process_chain(mod)

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
        lambda config: type(
            "S",
            (),
            {
                "select": lambda self, data, debug_csv=None, return_info=False: (
                    ([dummy_option], {}, {}) if return_info else [dummy_option]
                )
            },
        )(),
    )

    called = {"val": False}

    def fake_generate(*args, **kwargs):
        called["val"] = True
        return [], []

    monkeypatch.setattr(mod, "generate_strategy_candidates", fake_generate)
    monkeypatch.setattr(mod, "latest_atr", lambda s: 0.0)
    monkeypatch.setattr(mod, "_load_spot_from_metrics", lambda d, s: None)
    monkeypatch.setattr(mod, "_load_latest_close", lambda s: ClosePriceSnapshot(None, None))
    monkeypatch.setattr(mod, "refresh_spot_price", lambda s: None)
    monkeypatch.setattr(mod, "normalize_leg", lambda rec: rec)
    monkeypatch.setattr(mod, "get_option_mid_price", lambda opt: (opt.get("mid"), False))
    monkeypatch.setattr(mod, "calculate_pos", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_rom", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_edge", lambda *a, **k: 0.0)
    monkeypatch.setattr(mod, "calculate_ev", lambda *a, **k: 0.0)

    prompts = iter([False, True])
    monkeypatch.setattr(mod, "prompt_yes_no", lambda *a, **k: next(prompts))

    prints = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    mod.SESSION_STATE.clear()
    mod.SESSION_STATE.update({"evaluated_trades": [], "symbol": "AAA", "strategy": "test"})

    mod._process_chain(csv_path)

    assert called["val"] is False
