from typing import Mapping

from tomic.helpers.config import load_dte_range


def test_load_dte_range_uses_strategy_specific_override():
    config: Mapping[str, object] = {
        "strategies": {"iron_condor": {"dte_range": (7, 45)}}
    }
    assert load_dte_range("iron condor", config) == (7, 45)


def test_load_dte_range_falls_back_to_default():
    config = {"default": {"dte_range": [10, 30]}}
    assert load_dte_range("unknown", config) == (10, 30)


def test_load_dte_range_uses_loader_when_provided():
    def loader(strategy: str, _config: Mapping[str, object]) -> Mapping[str, object]:
        return {"dte_range": (12, 25)}

    assert load_dte_range("anything", {}, loader=loader) == (12, 25)
