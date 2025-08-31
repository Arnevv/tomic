from tomic import loader


def test_returns_strategy_when_found():
    config = {
        "default": {"foo": 1},
        "strategies": {"s1": {"foo": 2}},
    }
    result = loader.load_strike_config("s1", config)
    assert result == {"foo": 2}


def test_falls_back_to_default():
    config = {
        "default": {"foo": 1},
        "strategies": {"s1": {"foo": 2}},
    }
    result = loader.load_strike_config("unknown", config)
    assert result == {"foo": 1}


def test_flat_mapping_support():
    config = {
        "default": {"foo": 1},
        "s1": {"foo": 2},
    }
    assert loader.load_strike_config("s1", config) == {"foo": 2}
    assert loader.load_strike_config("unknown", config) == {"foo": 1}
