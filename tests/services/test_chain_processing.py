from pathlib import Path

import pandas as pd
import pytest

from tomic.services.chain_processing import (
    ChainPreparationConfig,
    PreparedChain,
    load_and_prepare_chain,
)
from tomic.services.strategy_pipeline import RejectionSummary, run as run_strategy_pipeline


if not hasattr(pd, "DataFrame") or isinstance(pd.DataFrame, type(object)):
    pytest.skip("pandas not available", allow_module_level=True)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_and_prepare_chain_normalizes_values(tmp_path):
    csv_path = tmp_path / "chain.csv"
    _write_csv(
        csv_path,
        [
            {
                "Expiration": "2024-01-19",
                "BID": "1,20",
                "Ask": "1,50",
                "Delta": "0,45",
                "Gamma": "0,10",
                "Vega": "0,25",
                "Theta": "-0,05",
                "Strike": 100,
                "Type": "CALL",
            },
            {
                "Expiration": "2024-02-16",
                "BID": "",
                "Ask": "1,55",
                "Delta": "",
                "Gamma": "",
                "Vega": "",
                "Theta": "",
                "Strike": 105,
                "Type": "PUT",
            },
        ],
    )

    config = ChainPreparationConfig(min_quality=0)
    prepared = load_and_prepare_chain(csv_path, config)

    assert isinstance(prepared, PreparedChain)
    assert prepared.path == csv_path
    first = prepared.records[0]
    assert first["bid"] == pytest.approx(1.20)
    assert first["ask"] == pytest.approx(1.50)
    assert first["delta"] == pytest.approx(0.45)
    assert first["expiry"] == "2024-01-19"
    second = prepared.records[1]
    assert second["bid"] is None
    assert second["delta"] is None
    assert second["expiry"] == "2024-02-16"


class _DummyPipeline:
    def __init__(self):
        self.last_context = None

    def build_proposals(self, context):
        self.last_context = context
        return [], RejectionSummary()


def test_load_and_prepare_chain_integrates_with_pipeline(tmp_path):
    csv_path = tmp_path / "chain.csv"
    _write_csv(
        csv_path,
        [
            {
                "expiration": "2024-01-19",
                "bid": "1,10",
                "ask": "1,20",
                "delta": "0,40",
                "gamma": "0,05",
                "vega": "0,10",
                "theta": "-0,04",
                "strike": 100,
                "type": "CALL",
            }
        ],
    )

    config = ChainPreparationConfig(min_quality=0)
    prepared = load_and_prepare_chain(csv_path, config)

    pipeline = _DummyPipeline()
    result = run_strategy_pipeline(
        pipeline,
        symbol="AAA",
        strategy="iron_condor",
        option_chain=prepared.records,
        spot_price=100.0,
        atr=1.5,
        config={},
        interest_rate=0.01,
    )

    assert result.context.symbol == "AAA"
    assert pipeline.last_context is result.context
    assert len(result.filtered_chain) == 1
    record = pipeline.last_context.option_chain[0]
    assert record["bid"] == pytest.approx(1.10)
    assert record["delta"] == pytest.approx(0.40)
    assert record["expiry"] == "2024-01-19"
