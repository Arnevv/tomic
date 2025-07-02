import importlib
import builtins
from pathlib import Path
from tomic.journal.utils import save_json


def test_show_market_info(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    sum_dir = tmp_path / "sum"
    hv_dir = tmp_path / "hv"
    spot_dir = tmp_path / "spot"
    for p in (sum_dir, hv_dir, spot_dir):
        p.mkdir()

    save_json(
        [{"date": "2025-06-28", "close": 534.5}, {"date": "2025-06-27", "close": 530.1}],
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
                else (str(spot_dir) if key == "PRICE_HISTORY_DIR" else default)
            )
        ),
    )

    prints = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))

    inputs = iter(["5", "0", "6"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))
    mod.run_portfolio_menu()

    assert any("2025-06-28" in line for line in prints)
    assert any("short_put_spread" in line for line in prints)
