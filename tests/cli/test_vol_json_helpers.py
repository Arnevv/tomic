import importlib
from tomic.analysis.vol_json import (
    get_latest_summary,
    load_latest_summaries,
    append_to_iv_summary,
)
from tomic.journal.utils import save_json, load_json


def test_get_and_load_latest_summaries(tmp_path):
    mod = importlib.import_module("tomic.analysis.vol_json")

    base = tmp_path
    save_json([
        {"date": "2024-01-01", "atm_iv": 0.2, "iv_rank": 10.0, "iv_percentile": 20.0},
        {"date": "2024-01-02", "atm_iv": 0.3, "iv_rank": 11.0, "iv_percentile": 21.0},
    ], base / "AAA.json")
    save_json([
        {"date": "2024-01-01", "atm_iv": 0.4, "iv_rank": 12.0, "iv_percentile": 22.0}
    ], base / "BBB.json")

    latest = get_latest_summary("AAA", base)
    assert latest is not None
    assert latest.date == "2024-01-02"
    stats = load_latest_summaries(["AAA", "BBB", "CCC"], base)
    assert set(stats.keys()) == {"AAA", "BBB"}
    assert stats["BBB"].iv_rank == 12.0


def test_append_to_iv_summary(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.analysis.vol_json")

    infos: list[str] = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *a, **k: infos.append(msg % a if a else msg))
    monkeypatch.setattr(mod.logger, "error", lambda *a, **k: None)

    base = tmp_path
    save_json([{"date": "2024-01-01", "atm_iv": 0.1}], base / "AAA.json")
    append_to_iv_summary("AAA", {"date": "2024-01-02", "atm_iv": 0.2}, base)
    data = load_json(base / "AAA.json")
    assert len(data) == 2
    assert any(rec.get("atm_iv") == 0.2 for rec in data)
    assert any("IV summary updated" in m for m in infos)


def test_append_to_iv_summary_corrupt(tmp_path, monkeypatch):
    mod = importlib.import_module("tomic.analysis.vol_json")

    monkeypatch.setattr(mod.logger, "info", lambda *a, **k: None)
    monkeypatch.setattr(mod.logger, "error", lambda *a, **k: None)

    path = tmp_path / "AAA.json"
    path.write_text("{bad json")
    append_to_iv_summary("AAA", {"date": "2024-01-01", "atm_iv": 0.2}, tmp_path)
    data = load_json(path)
    assert isinstance(data, list) and len(data) == 1

