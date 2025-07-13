import importlib

from tomic import config


def test_default_data_dirs():
    cfg = importlib.reload(config)
    assert cfg.get("PRICE_HISTORY_DIR") == "tomic/data/spot_prices"
    assert cfg.get("IV_DAILY_SUMMARY_DIR") == "tomic/data/iv_daily_summary"
    assert cfg.get("EARNINGS_DATES_FILE") == "tomic/data/earnings_dates.json"
    assert cfg.get("EARNINGS_DATA_FILE") == "tomic/data/earnings_data.json"


def test_default_strategy_settings():
    cfg = importlib.reload(config)
    assert cfg.get("NEAREST_STRIKE_TOLERANCE_PERCENT") == 2.0
    assert cfg.get("SCORE_WEIGHT_ROM") == 0.5
    assert cfg.get("SCORE_WEIGHT_POS") == 0.3
    assert cfg.get("SCORE_WEIGHT_EV") == 0.2
