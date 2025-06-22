import importlib
import json
import builtins
from pathlib import Path
from tomic.journal.utils import save_json


def test_generate_proposals_now_db(monkeypatch, tmp_path):
    mod = importlib.import_module("tomic.cli.controlpanel")

    sum_dir = tmp_path / "sum"
    hv_dir = tmp_path / "hv"
    sum_dir.mkdir(); hv_dir.mkdir()
    save_json([
        {"date": "2024-01-02", "atm_iv": 0.6, "iv_rank": 11.0, "iv_percentile": 21.0}
    ], sum_dir / "AAA.json")
    save_json([
        {"date": "2024-01-02", "hv20": 0.5, "hv30": 0.4, "hv90": 0.3}
    ], hv_dir / "AAA.json")
    monkeypatch.setattr(
        mod,
        "load_latest_summaries",
        lambda symbols: {"AAA": importlib.import_module("types").SimpleNamespace(date="2024-01-02", atm_iv=0.6, iv_rank=11.0, iv_percentile=21.0)},
    )

    pos_file = tmp_path / "p.json"
    pos_file.write_text('[{"symbol": "AAA", "position": 1}]')
    monkeypatch.setattr(mod, "POSITIONS_FILE", pos_file)

    export_dir = tmp_path / "exp"
    export_dir.mkdir()
    monkeypatch.setattr(mod, "_latest_export_dir", lambda base: export_dir)
    monkeypatch.setattr(mod.cfg, "get", lambda key, default=None: str(export_dir) if key == "EXPORT_DIR" else default)

    called = []
    def fake_run(module, *args):
        called.append((module, args))
    monkeypatch.setattr(mod, "run_module", fake_run)

    monkeypatch.setattr(mod, "compute_portfolio_greeks", lambda p: {"Delta": 0, "Vega": 0})
    prints = []
    monkeypatch.setattr(builtins, "print", lambda *a, **k: prints.append(" ".join(str(x) for x in a)))
    monkeypatch.setattr(mod.os, "unlink", lambda p: None)

    inputs = iter(["5", "6"])
    monkeypatch.setattr(builtins, "input", lambda *a: next(inputs))
    mod.run_portfolio_menu()

    assert any("AAA" in line for line in prints)
    assert called
    module, args = called[0]
    assert module == "tomic.cli.generate_proposals"
    assert len(args) == 3
    metrics_path = args[2]
    data = json.loads(Path(metrics_path).read_text())
    assert "AAA" in data
