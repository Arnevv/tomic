import pandas as pd
import numpy as np
import pytest

if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)

from tomic.helpers.interpolation import interpolate_missing_fields


def test_linear_interpolation_delta():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 5,
        'strike': [100, 105, 110, 115, 120],
        'delta': [0.9, np.nan, np.nan, 0.2, 0.1],
        'iv': [0.25] * 5
    })
    result = interpolate_missing_fields(df)
    assert not result['delta'].isnull().any()
    assert abs(result.loc[1, 'delta'] - 0.666) < 0.01


def test_spline_interpolation_iv():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 6,
        'strike': [100, 105, 110, 115, 120, 125],
        'delta': [0.9] * 6,
        'iv': [0.30, 0.28, np.nan, 0.27, 0.29, 0.31]
    })
    result = interpolate_missing_fields(df)
    assert not result['iv'].isnull().any()


def test_spline_handles_unsorted_duplicates():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 8,
        'strike': [110, 100, 105, 110, 120, 115, 125, 100],
        'delta': [0.9] * 8,
        'iv': [0.30, 0.28, 0.29, np.nan, 0.27, np.nan, 0.31, 0.32],
    })
    result = interpolate_missing_fields(df)
    assert not result['iv'].isnull().any()


def test_interpolates_per_expiration_and_type():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 8,
        'strike': [100, 105, 110, 115, 100, 105, 110, 115],
        'type': ['call'] * 4 + ['put'] * 4,
        'delta': [0.6, np.nan, 0.4, 0.3, -0.6, np.nan, -0.4, -0.3],
        'iv': [0.25] * 8,
    })
    result = interpolate_missing_fields(df)
    call_delta = result[(result['type'] == 'call') & (result['strike'] == 105)]['delta'].iloc[0]
    put_delta = result[(result['type'] == 'put') & (result['strike'] == 105)]['delta'].iloc[0]
    assert abs(call_delta - 0.5) < 0.01
    assert abs(put_delta + 0.5) < 0.01


def test_iv_scale_detection_and_interpolation():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 6,
        'strike': [100, 105, 110, 115, 120, 125],
        'type': ['call'] * 6,
        'delta': [0.5] * 6,
        'iv': [25, 24, np.nan, 26, 27, 28],
    })
    result = interpolate_missing_fields(df)
    assert result['iv'].max() < 1.0
    assert not result['iv'].isnull().any()


def test_clipping_of_values():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 5,
        'strike': [100, 110, 120, 130, 140],
        'type': ['call'] * 5,
        'delta': [1.2, np.nan, np.nan, 1.1, 0.9],
        'iv': [600, 750, np.nan, 550, 650],
    })
    result = interpolate_missing_fields(df)
    assert (result['delta'] <= 1.0).all()
    assert (result['iv'] <= 5.0).all()


def test_no_interpolation_with_insufficient_points():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 3,
        'strike': [100, 105, 110],
        'type': ['call'] * 3,
        'delta': [0.9, np.nan, np.nan],
        'iv': [0.25, np.nan, np.nan],
    })
    result = interpolate_missing_fields(df)
    assert result['delta'].isnull().sum() == 2
    assert result['iv'].isnull().sum() == 2


def test_no_interpolation_with_all_missing_values():
    df = pd.DataFrame({
        'expiry': ['2025-08-16'] * 3,
        'strike': [100, 105, 110],
        'delta': [np.nan, np.nan, np.nan],
        'iv': [np.nan, np.nan, np.nan],
    })
    result = interpolate_missing_fields(df)
    assert result['delta'].isnull().all()
    assert result['iv'].isnull().all()
