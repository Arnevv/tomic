import pandas as pd
import pytest

from tomic.helpers.csv_norm import dataframe_to_records, normalize_chain_dataframe


if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)


def test_normalize_chain_dataframe_handles_aliases_and_nan():
    df = pd.DataFrame(
        {
            "Expiration": ["2024-01-19", "2024-02-16"],
            "BID": ["1,20", ""],
            "Ask": ["1,50", "1,55"],
            "Delta": ["0,45", None],
            "Custom": [pd.NA, "value"],
        }
    )

    normalized = normalize_chain_dataframe(
        df,
        decimal_columns=("bid", "ask", "delta"),
        date_columns=("expiry",),
        date_format="%Y-%m-%d",
    )

    assert list(normalized.columns) == ["expiry", "bid", "ask", "delta", "custom"]
    assert normalized.loc[0, "bid"] == pytest.approx(1.20)
    assert normalized.loc[0, "ask"] == pytest.approx(1.50)
    assert normalized.loc[0, "delta"] == pytest.approx(0.45)
    assert normalized.loc[1, "bid"] is None or pd.isna(normalized.loc[1, "bid"])
    assert normalized.loc[0, "expiry"] == "2024-01-19"

    records = dataframe_to_records(normalized)
    assert records[0]["bid"] == pytest.approx(1.20)
    assert records[0]["delta"] == pytest.approx(0.45)
    assert records[1]["bid"] is None
    assert records[1]["delta"] is None
    assert records[0]["custom"] is None
    assert records[1]["custom"] == "value"


def test_normalize_chain_dataframe_drops_duplicate_alias_columns():
    df = pd.DataFrame(
        {
            "expiry": ["2024-01-19"],
            "expiration": ["2024-01-20"],
            "bid": [1.0],
        }
    )

    normalized = normalize_chain_dataframe(df)
    assert list(normalized.columns) == ["expiry", "bid"]
    # Original expiry column should win when both are present
    assert normalized.loc[0, "expiry"] == "2024-01-19"


def test_normalize_chain_dataframe_prefers_first_alias_when_no_canonical_column():
    df = pd.DataFrame(
        {
            "exp": ["2024-01-19"],
            "expiry_date": ["2024-02-16"],
            "ask": [1.5],
        }
    )

    normalized = normalize_chain_dataframe(
        df,
        column_aliases={"exp": "expiry", "expiry_date": "expiry"},
        date_columns=("expiry",),
        date_format="%Y-%m-%d",
    )

    assert list(normalized.columns) == ["expiry", "ask"]
    # First alias should be preserved
    assert normalized.loc[0, "expiry"] == "2024-01-19"
