import importlib

from tomic import config


def test_volatility_db_value():
    cfg = importlib.reload(config)
    assert cfg.get("VOLATILITY_DB") == "tomic/data/volatility.db"
