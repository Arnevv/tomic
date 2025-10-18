from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

import pytest

from tomic.formatting.table_builders import (
    PORTFOLIO_SPEC,
    PROPOSALS_SPEC,
    REJECTIONS_SPEC,
    portfolio_table,
    proposals_table,
    rejections_table,
)
from tomic.services.pipeline_refresh import RefreshSource, Rejection
from tomic.services.proposal_details import (
    EarningsVM,
    ProposalCore,
    ProposalLegVM,
    ProposalSummaryVM,
    ProposalVM,
)


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    from tomic import formatting

    monkeypatch.setattr(
        formatting.table_builders, "today", lambda: date(2024, 7, 1)
    )


def _build_summary(**overrides):
    defaults = dict(
        credit=1.50,
        margin=10.0,
        max_profit=200.0,
        max_loss=-50.0,
        breakevens=(95.0, 90.0),
        pos=0.62,
        ev=125.12,
        rom=0.1,
        score=1.0,
        risk_reward=2.5,
        profit_estimated=False,
        scenario_label=None,
        scenario_error=None,
        iv_rank=0.45,
        iv_percentile=0.5,
        hv20=0.2,
        hv30=0.21,
        hv90=0.22,
        hv252=0.25,
        edge=0.1,
        greeks={"delta": -0.35, "theta": 0.08, "vega": 0.12},
    )
    defaults.update(overrides)
    return ProposalSummaryVM(**defaults)


def _build_vm(symbol: str, expiry: str, strikes: tuple[float, ...], **kwargs) -> ProposalVM:
    legs_core = tuple(
        {
            "expiry": expiry,
            "type": "call",
            "strike": strike,
            "iv": kwargs.get("iv", 0.21),
        }
        for strike in strikes
    )
    core = ProposalCore(
        symbol=symbol,
        strategy=kwargs.get("strategy", "spread"),
        expiry=expiry,
        strikes=strikes,
        legs=legs_core,
        greeks={
            "delta": kwargs.get("delta", -0.35),
            "theta": kwargs.get("theta", 0.08),
            "vega": kwargs.get("vega", 0.12),
        },
        pricing_meta={
            "credit": kwargs.get("credit", 1.2),
            "ev": kwargs.get("ev", 15.6),
            "pos": kwargs.get("pos", 0.61),
        },
    )
    leg_vm = ProposalLegVM(
        expiry=expiry,
        strike=strikes[0],
        option_type="call",
        position=-1,
        bid=kwargs.get("bid", 1.0),
        ask=kwargs.get("ask", 1.2),
        mid=kwargs.get("mid", 1.1),
        iv=kwargs.get("iv", 0.21),
        delta=kwargs.get("delta", -0.35),
        gamma=0.01,
        vega=kwargs.get("vega", 0.12),
        theta=kwargs.get("theta", 0.08),
        warnings=(),
    )
    summary = _build_summary(
        credit=kwargs.get("credit", 1.2),
        ev=kwargs.get("ev", 15.6),
        pos=kwargs.get("pos", 0.61),
        greeks={
            "delta": kwargs.get("delta", -0.35),
            "theta": kwargs.get("theta", 0.08),
            "vega": kwargs.get("vega", 0.12),
        },
    )
    earnings = EarningsVM(None, None, None, None)
    return ProposalVM(
        core=core,
        legs=(leg_vm,),
        warnings=(),
        missing_quotes=(),
        summary=summary,
        earnings=earnings,
        accepted=True,
        reasons=(),
        credit_capped=False,
        has_missing_edge=False,
    )


def test_proposals_table_formats_and_sorts():
    later = _build_vm(
        symbol="ZZZ",
        expiry="2024-07-19",
        strikes=(100.0, 105.0),
        delta=0.42,
        theta=-0.11,
        vega=0.55,
        iv=0.23,
        credit=1.75,
        ev=28.5,
        pos=0.58,
    )
    earlier = _build_vm(
        symbol="AAA",
        expiry="2024-06-21",
        strikes=(95.0, 90.0),
        delta=-0.35,
        theta=0.08,
        vega=0.12,
        iv=0.21,
        credit=1.2,
        ev=15.6,
        pos=0.61,
        strategy="short_put",
    )

    headers, rows = proposals_table([later, earlier], spec=PROPOSALS_SPEC)

    assert headers == [
        "Symbol",
        "Strategy",
        "Expiry",
        "Strike(s)",
        "Δ",
        "Θ",
        "Vega",
        "IV",
        "EV",
        "PoS",
        "Credit/Mid",
    ]
    assert rows == [
        [
            "AAA",
            "short_put",
            "2024-06-21",
            "95 / 90",
            "-0.35",
            "+0.08",
            "+0.12",
            "21.0%",
            "15.60",
            "61.0%",
            "1.20",
        ],
        [
            "ZZZ",
            "spread",
            "2024-07-19",
            "100 / 105",
            "+0.42",
            "-0.11",
            "+0.55",
            "23.0%",
            "28.50",
            "58.0%",
            "1.75",
        ],
    ]


def _build_rejection(symbol: str, expiry: str, **kwargs) -> Rejection:
    legs = (
        {
            "expiry": expiry,
            "type": "call",
            "strike": kwargs.get("strike", 120.0),
            "iv": kwargs.get("iv", 0.23),
        },
        {
            "expiry": expiry,
            "type": "call",
            "strike": kwargs.get("strike2", 125.0),
            "iv": kwargs.get("iv2", 0.21),
        },
    )
    core = ProposalCore(
        symbol=symbol,
        strategy=kwargs.get("strategy", "call_spread"),
        expiry=expiry,
        strikes=(legs[0]["strike"], legs[1]["strike"]),
        legs=legs,
        greeks={"delta": kwargs.get("delta", 0.4)},
        pricing_meta={
            "ev": kwargs.get("ev", 100.5),
            "score": kwargs.get("score", 1.25),
        },
    )
    source = RefreshSource(index=kwargs.get("index", 1), entry={}, symbol=symbol)
    return Rejection(
        source=source,
        proposal=None,
        reasons=kwargs.get("reasons", ["No edge"]),
        missing_quotes=[],
        error=None,
        attempts=0,
        core=core,
        accepted=False,
    )


def test_rejections_table_applies_sanitization():
    clean = _build_rejection("ZZZ", "2024-07-19", strike=120.0, ev=100.5, score=1.25)
    dirty = _build_rejection(
        "AAA",
        "2024-07-10",
        strike=115.0,
        iv=float("nan"),
        ev=math.nan,
        score=None,
        reasons=[""],
    )

    headers, rows = rejections_table([clean, dirty], spec=REJECTIONS_SPEC)

    assert headers == [
        "Symbol",
        "Expiry",
        "LegCount",
        "Reason",
        "Score",
        "Δ",
        "IV",
        "EV",
        "DTE",
    ]
    assert rows == [
        [
            "AAA",
            "2024-07-10",
            "2",
            "geen reden opgegeven",
            "—",
            "+0.40",
            "21.0%",
            "—",
            "9",
        ],
        [
            "ZZZ",
            "2024-07-19",
            "2",
            "No edge",
            "1.25",
            "+0.40",
            "23.0%",
            "100.50",
            "18",
        ],
    ]


@dataclass
class PortfolioRow:
    symbol: str
    quantity: int | None = None
    exposure: float | None = None
    greeks: dict[str, float] | None = None
    iv_rank: float | None = None
    hv30: float | None = None
    atr: float | None = None


def test_portfolio_table_formats_values():
    rows = [
        PortfolioRow(
            symbol="AAA",
            quantity=2,
            exposure=1500.125,
            greeks={"delta": 0.5, "theta": -0.1},
            iv_rank=0.4,
            hv30=0.25,
            atr=3.75,
        ),
        PortfolioRow(symbol="BBB"),
    ]

    headers, table_rows = portfolio_table(rows, spec=PORTFOLIO_SPEC)

    assert headers == [
        "Symbol",
        "Qty",
        "Exposure",
        "Greeks Σ",
        "IV Rank",
        "HV30",
        "ATR",
    ]
    assert table_rows == [
        [
            "AAA",
            "2",
            "1500.13",
            "Δ +0.50 · Θ -0.10",
            "40.0%",
            "25.0%",
            "3.75",
        ],
        ["BBB", "—", "—", "—", "—", "—", "—"],
    ]
