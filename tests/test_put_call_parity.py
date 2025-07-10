import math
import pandas as pd
import pytest

if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)

from tomic.helpers.put_call_parity import fill_missing_mid_with_parity


def test_reconstruct_call_from_put():
    df = pd.DataFrame({
        "expiration": ["2025-07-26", "2025-07-26"],
        "strike": [145.0, 145.0],
        "type": ["call", "put"],
        "mid": [math.nan, 5.0],
        "dte": [365, 365],
    })
    result = fill_missing_mid_with_parity(df, 150.0)
    call_mid = result[result["type"] == "call"]["mid"].iloc[0]
    expected = 5.0 + 150.0 - 145.0 * math.exp(-0.03 * (365 / 365))
    assert abs(call_mid - expected) < 1e-4
    assert result[result["type"] == "call"]["mid_from_parity"].iloc[0] is True


def test_reconstruct_put_from_call():
    df = pd.DataFrame({
        "expiration": ["2025-07-26", "2025-07-26"],
        "strike": [145.0, 145.0],
        "type": ["call", "put"],
        "mid": [10.0, math.nan],
        "dte": [365, 365],
    })
    result = fill_missing_mid_with_parity(df, 150.0)
    put_mid = result[result["type"] == "put"]["mid"].iloc[0]
    expected = 10.0 - 150.0 + 145.0 * math.exp(-0.03 * (365 / 365))
    assert abs(put_mid - expected) < 1e-4
    assert result[result["type"] == "put"]["mid_from_parity"].iloc[0] is True


def test_no_change_when_both_mids_present():
    df = pd.DataFrame({
        "expiration": ["2025-07-26", "2025-07-26"],
        "strike": [145.0, 145.0],
        "type": ["call", "put"],
        "mid": [10.0, 5.0],
        "dte": [365, 365],
    })
    result = fill_missing_mid_with_parity(df, 150.0)
    assert result["mid_from_parity"].any() is False


def test_skip_when_spot_or_dte_missing():
    df = pd.DataFrame({
        "expiration": ["2025-07-26", "2025-07-26"],
        "strike": [145.0, 145.0],
        "type": ["call", "put"],
        "mid": [math.nan, 5.0],
        "dte": [math.nan, math.nan],
    })
    result = fill_missing_mid_with_parity(df, None)
    assert math.isnan(result.loc[0, "mid"])
    assert not result["mid_from_parity"].any()


def test_skip_when_both_mids_missing():
    df = pd.DataFrame({
        "expiration": ["2025-07-26", "2025-07-26"],
        "strike": [145.0, 145.0],
        "type": ["call", "put"],
        "mid": [math.nan, math.nan],
        "dte": [365, 365],
    })
    result = fill_missing_mid_with_parity(df, 150.0)
    assert result["mid"].isna().all()
    assert not result["mid_from_parity"].any()
