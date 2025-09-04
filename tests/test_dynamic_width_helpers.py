from datetime import date

import pytest

from tomic.strategies.utils import (
    compute_sigma_width,
    compute_delta_width,
    compute_atr_width,
)


def test_compute_sigma_width(monkeypatch):
    short_opt = {"iv": 0.2, "expiry": "2024-01-11"}
    spot = 100
    sigma_multiple = 1.0
    monkeypatch.setattr("tomic.strategies.utils.today", lambda: date(2024, 1, 1))
    width = compute_sigma_width(short_opt, spot=spot, sigma_multiple=sigma_multiple)
    assert width == pytest.approx(3.3104235544)


def test_compute_delta_width():
    short_opt = {"strike": 100}
    option_chain = [
        {"expiry": "2024-01-11", "right": "call", "delta": 0.1, "strike": 90},
        {"expiry": "2024-01-11", "right": "call", "delta": 0.3, "strike": 110},
    ]
    width = compute_delta_width(
        short_opt,
        target_delta=0.25,
        option_chain=option_chain,
        expiry="2024-01-11",
        option_type="call",
    )
    assert width == 10


def test_compute_atr_width():
    assert compute_atr_width(atr=5, atr_multiple=2, use_atr=True) == 10
    assert compute_atr_width(atr=5, atr_multiple=2, use_atr=False) == 2
