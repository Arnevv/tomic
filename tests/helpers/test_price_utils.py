from pathlib import Path

from tomic.helpers import price_utils
from tomic.journal.utils import save_json


def test_load_latest_close_non_positive(monkeypatch, tmp_path):
    """Non-positive close values should be returned as ``None``."""

    data_dir = tmp_path / "prices"
    data_dir.mkdir()
    save_json([{"date": "2024-01-01", "close": -1}], data_dir / "AAA.json")

    monkeypatch.setattr(price_utils, "cfg_get", lambda *a, **k: str(data_dir))

    price, date = price_utils._load_latest_close("AAA")
    assert price is None
    assert date == "2024-01-01"

    date_only = price_utils._load_latest_close("AAA", return_date_only=True)
    assert date_only == "2024-01-01"

