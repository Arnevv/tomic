from __future__ import annotations

import os

import pytest

from tomic.services.ib_marketdata import fetch_quote_snapshot, SnapshotResult
from tomic.services.order_submission import prepare_order_instructions
from tomic.services.strategy_pipeline import StrategyProposal


pytestmark = pytest.mark.skipif(
    os.environ.get("IB_INTEGRATION") != "1",
    reason="requires running IB Gateway/TWS (set IB_INTEGRATION=1)",
)


def test_ib_quote_and_order_concept_flow():  # pragma: no cover - integration only
    proposal = StrategyProposal(
        strategy="naked_put",
        legs=[
            {
                "symbol": "SPY",
                "expiry": "20240719",
                "strike": 400.0,
                "type": "put",
                "position": -1,
            }
        ],
    )
    snapshot = fetch_quote_snapshot(proposal, spot_price=None)
    assert isinstance(snapshot, SnapshotResult)
    prepare_order_instructions(proposal, symbol="SPY")
