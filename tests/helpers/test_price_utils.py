from pathlib import Path

from tomic.helpers import price_utils
from tomic.journal.utils import save_json


def test_load_latest_close_non_positive(monkeypatch, tmp_path):
    """Non-positive close values should be returned as ``None``."""

    data_dir = tmp_path / "prices"
    data_dir.mkdir()
    save_json([{"date": "2024-01-01", "close": -1}], data_dir / "AAA.json")

    monkeypatch.setattr(
        price_utils,
        "load_price_history",
        lambda symbol: [{"date": "2024-01-01", "close": -1}],
    )
    monkeypatch.setattr(
        price_utils,
        "load_price_meta",
        lambda: {
            "AAA": {
                "source": "polygon",
                "fetched_at": "2024-01-02T10:00:00",
                "baseline_active": True,
                "baseline_as_of": "2024-01-01",
            }
        },
    )

    snapshot = price_utils._load_latest_close("AAA")
    assert isinstance(snapshot, price_utils.ClosePriceSnapshot)
    assert snapshot.price is None
    assert snapshot.date == "2024-01-01"
    assert snapshot.source == "polygon"
    assert snapshot.fetched_at == "2024-01-02T10:00:00"
    assert snapshot.baseline is False

    date_only = price_utils._load_latest_close("AAA", return_date_only=True)
    assert date_only == "2024-01-01"

