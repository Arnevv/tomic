import pytest

from tomic.core.data import (
    ChainNormalizerConfig,
    dataframe_to_records,
    normalize_chain_records,
    normalize_dataframe,
)


def _require_pandas():
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - optional dependency
        pytest.skip("pandas not available", allow_module_level=True)
    if not hasattr(pd, "DataFrame") or not isinstance(pd.DataFrame, type):
        pytest.skip("pandas not available", allow_module_level=True)
    try:
        pd.DataFrame([{}])
    except Exception:
        pytest.skip("pandas not available", allow_module_level=True)
    return pd


def test_csv_and_live_feeds_produce_identical_records():
    pd = _require_pandas()

    csv_rows = [
        {
            "Expiration": "2025-07-26",
            "Type": "CALL",
            "Strike": "145",
            "Mid": "",
            "Bid": "1.20",
            "Ask": "1.40",
            "DTE": 365,
        },
        {
            "Expiration": "2025-07-26",
            "Type": "PUT",
            "Strike": "145",
            "Mid": "5.00",
            "Bid": "5.10",
            "Ask": "5.30",
            "DTE": 365,
        },
    ]

    df = pd.DataFrame(csv_rows)
    config = ChainNormalizerConfig()
    normalized_df = normalize_dataframe(df, config=config)
    csv_records = normalize_chain_records(
        dataframe_to_records(normalized_df),
        spot_price=150.0,
        interest_rate=0.02,
        apply_parity=True,
    )

    live_records = normalize_chain_records(
        [
            {
                "expiry": "2025-07-26",
                "type": "call",
                "strike": 145.0,
                "mid": None,
                "bid": 1.2,
                "ask": 1.4,
                "dte": 365,
            },
            {
                "expiry": "2025-07-26",
                "type": "put",
                "strike": 145.0,
                "mid": 5.0,
                "bid": 5.1,
                "ask": 5.3,
                "dte": 365,
            },
        ],
        spot_price=150.0,
        interest_rate=0.02,
        apply_parity=True,
    )

    assert csv_records == live_records
    assert csv_records[0]["mid_from_parity"] is True
    assert csv_records[1]["mid_from_parity"] is False
