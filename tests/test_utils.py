import json
from datetime import date
from typing import Dict

from tomic.utils import today
from tomic.journal import utils as journal_utils
import vol_cone_db


def test_today_env(monkeypatch):
    monkeypatch.setenv("TOMIC_TODAY", "2024-01-02")
    assert today().isoformat() == "2024-01-02"


def test_today_default(monkeypatch):
    monkeypatch.delenv("TOMIC_TODAY", raising=False)
    assert isinstance(today(), date)


def test_load_journal_missing(tmp_path):
    path = tmp_path / "missing.json"
    assert journal_utils.load_journal(path) == []


def test_save_and_load_journal(tmp_path):
    path = tmp_path / "journal.json"
    data = [{"TradeID": 1}]
    journal_utils.save_journal(data, path)
    assert journal_utils.load_journal(path) == data


def test_store_volatility_snapshot_replace(tmp_path):
    path = tmp_path / "vol.json"
    record1: Dict[str, object] = {
        "date": "2024-01-02",
        "symbol": "SPY",
        "spot": 100.0,
        "iv30": 0.2,
        "hv30": 0.15,
        "iv_rank": 50.0,
        "skew": 0.1,
    }
    vol_cone_db.store_volatility_snapshot(record1, path)
    assert json.loads(path.read_text())[0]["iv_rank"] == 50.0

    record2 = record1.copy()
    record2["iv_rank"] = 60.0
    vol_cone_db.store_volatility_snapshot(record2, path)
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["iv_rank"] == 60.0


def test_store_volatility_snapshot_incomplete(tmp_path):
    path = tmp_path / "vol.json"
    incomplete = {
        "date": "2024-01-02",
        "symbol": "SPY",
        "spot": 100.0,
        "iv30": 0.2,
        # missing hv30
        "iv_rank": 50.0,
        "skew": 0.1,
    }
    vol_cone_db.store_volatility_snapshot(incomplete, path)
    assert not path.exists()


def test_snapshot_symbols(monkeypatch, tmp_path):
    path = tmp_path / "vol.json"

    def fake_fetch(symbol: str) -> Dict[str, float]:
        return {
            "spot_price": 100.0,
            "implied_volatility": 0.2,
            "hv30": 0.15,
            "iv_rank": 55.0,
            "skew": 0.05,
        }

    monkeypatch.setattr(vol_cone_db, "fetch_market_metrics", fake_fetch)
    vol_cone_db.snapshot_symbols(["SPY"], output_path=str(path))
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["symbol"] == "SPY"
