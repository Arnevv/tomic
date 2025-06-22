import importlib

from tomic import config


def test_default_data_dirs():
    cfg = importlib.reload(config)
    assert cfg.get("PRICE_HISTORY_DIR") == "tomic/data/spot_prices"
    assert cfg.get("IV_DAILY_SUMMARY_DIR") == "tomic/data/iv_daily_summary"
