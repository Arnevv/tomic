import pandas as pd
import numpy as np
import pytest

if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)

from tomic.helpers.interpolation import interpolate_missing_fields


def test_linear_interpolation_delta():
    df = pd.DataFrame({
        'expiration': ['2025-08-16'] * 5,
        'strike': [100, 105, 110, 115, 120],
        'delta': [0.9, np.nan, np.nan, 0.2, 0.1],
        'iv': [0.25] * 5
    })
    result = interpolate_missing_fields(df)
    assert not result['delta'].isnull().any()
    assert abs(result.loc[1, 'delta'] - 0.666) < 0.01


def test_spline_interpolation_iv():
    df = pd.DataFrame({
        'expiration': ['2025-08-16'] * 6,
        'strike': [100, 105, 110, 115, 120, 125],
        'delta': [0.9] * 6,
        'iv': [0.30, 0.28, np.nan, 0.27, 0.29, 0.31]
    })
    result = interpolate_missing_fields(df)
    assert not result['iv'].isnull().any()
