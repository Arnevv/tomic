import importlib
from tomic.analysis.vol_json import get_latest_summary, load_latest_summaries
from tomic.journal.utils import save_json


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

