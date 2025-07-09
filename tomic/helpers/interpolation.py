import pandas as pd
import numpy as np
from scipy.interpolate import UnivariateSpline



def interpolate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Interpoleer DELTA met lineaire interpolatie per expiry
    if 'delta' in df.columns:
        df['delta'] = (
            df.groupby('expiration', group_keys=False)
            .apply(_interpolate_column, column='delta', method='linear')
        )

    # Interpoleer IV met spline-interpolatie per expiry
    if 'iv' in df.columns:
        df['iv'] = (
            df.groupby('expiration', group_keys=False)
            .apply(_interpolate_column, column='iv', method='spline')
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

        x_valid = pd.Series(x[valid]).astype(float)
        y_valid = pd.Series(y[valid]).astype(float)
        df_valid = (
            pd.DataFrame({"x": x_valid, "y": y_valid})
            .sort_values("x")
            .groupby("x", as_index=False)
            .mean()
        )
        if len(df_valid) < 4:
            return y

        spline = UnivariateSpline(df_valid["x"], df_valid["y"], s=0)
        x_all = pd.Series(x).astype(float)
        return pd.Series(spline(x_all), index=group.index)

    else:
        raise ValueError(f"Unsupported interpolation method: {method}")

