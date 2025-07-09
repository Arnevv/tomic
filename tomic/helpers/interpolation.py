import pandas as pd
import numpy as np
from scipy.interpolate import UnivariateSpline



def interpolate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Interpoleer DELTA met lineaire interpolatie per expiry
    if 'delta' in df.columns:
        df['delta'] = (
            df.groupby('expiration')
            .apply(_interpolate_column, column='delta', method='linear')
            .reset_index(level=0, drop=True)
        )

    # Interpoleer IV met spline-interpolatie per expiry
    if 'iv' in df.columns:
        df['iv'] = (
            df.groupby('expiration')
            .apply(_interpolate_column, column='iv', method='spline')
            .reset_index(level=0, drop=True)
        )

    return df


def _interpolate_column(group: pd.DataFrame, column: str, method: str) -> pd.Series:
    x = group['strike']
    y = group[column]

    if y.isnull().sum() == 0:
        return y  # niets te interpoleren

    if method == 'linear':
        valid = y.notnull()
        return pd.Series(np.interp(x, x[valid], y[valid]), index=group.index)

    elif method == 'spline':
        valid = y.notnull()
        if valid.sum() < 4:
            return y  # onvoldoende punten voor spline
        spline = UnivariateSpline(x[valid], y[valid], s=0)
        return pd.Series(spline(x), index=group.index)

    else:
        raise ValueError(f"Unsupported interpolation method: {method}")

