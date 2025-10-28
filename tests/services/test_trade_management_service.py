import copy
import math

import pytest

from tomic.services.trade_management_service import (
    StrategyExitIntent,
    build_exit_intents,
)


@pytest.fixture
def sample_positions():
    return [
        {
            "conId": 1001,
            "symbol": "XYZ",
            "lastTradeDate": "20240119",
            "strike": 100.0,
            "right": "C",
            "position": -1,
            "bid": 1.1,
            "ask": 1.2,
            "minTick": 0.01,
        },
        {
            "conId": 1002,
            "symbol": "XYZ",
            "lastTradeDate": "20240119",
            "strike": 105.0,
            "right": "C",
            "position": 1,
            "bid": 0.55,
            "ask": 0.65,
            "minTick": 0.01,
        },
    ]


@pytest.fixture
def sample_journal():
    return [
        {
            "TradeID": "trade-1",
            "Symbool": "XYZ",
            "Expiry": "2024-01-19",
            "Legs": [
                {"conId": 1001},
                {"conId": 1002},
            ],
            "ExitRules": {"target_profit_pct": 50},
        }
    ]


@pytest.fixture
def aggregated_strategies():
    return [
        {
            "trade_id": "trade-1",
            "symbol": "XYZ",
            "expiry": "2024-01-19",
            "type": "vertical",
            "legs": [
                {"conId": 1001, "strike": 100.0, "position": -1, "right": "call"},
                {"conId": 1002, "strike": 105.0, "position": 1, "right": "call"},
            ],
        }
    ]


def test_build_exit_intents_returns_raw_legs_and_rules(
    sample_positions, sample_journal, aggregated_strategies
):
    loader_payloads = {
        "positions.json": copy.deepcopy(sample_positions),
        "journal.json": copy.deepcopy(sample_journal),
    }

    def loader(path):
        return loader_payloads[path]

    exit_rules = {("XYZ", "2024-01-19"): {"target_profit_pct": 50}}

    intents = build_exit_intents(
        positions_file="positions.json",
        journal_file="journal.json",
        grouper=lambda positions, journal: copy.deepcopy(aggregated_strategies),
        exit_rule_loader=lambda path: exit_rules,
        loader=loader,
    )

    assert len(intents) == 1
    intent = intents[0]
    assert isinstance(intent, StrategyExitIntent)
    assert intent.exit_rules == {"target_profit_pct": 50}
    assert intent.legs == sample_positions
    legs = intent.strategy["legs"]
    assert legs[0]["bid"] == 1.1
    assert legs[0]["ask"] == 1.2
    assert legs[0]["minTick"] == 0.01
    assert legs[1]["bid"] == 0.55
    assert legs[1]["ask"] == 0.65


def test_build_exit_intents_fetches_quotes_when_missing():
    positions = [
        {
            "conId": 2001,
            "symbol": "ABC",
            "lastTradeDate": "20240216",
            "strike": 95.0,
            "right": "P",
            "position": -1,
        }
    ]
    journal = [
        {
            "TradeID": "trade-2",
            "Symbool": "ABC",
            "Expiry": "2024-02-16",
            "Legs": [{"conId": 2001}],
        }
    ]

    loader_payloads = {
        "positions.json": copy.deepcopy(positions),
        "journal.json": copy.deepcopy(journal),
    }

    def loader(path):
        return loader_payloads[path]

    aggregated = [
        {
            "trade_id": "trade-2",
            "symbol": "ABC",
            "expiry": "2024-02-16",
            "type": "vertical",
            "legs": [{"conId": 2001, "strike": 95.0, "position": -1, "right": "put"}],
        }
    ]

    calls: list[tuple[dict, list[dict]]] = []

    def quote_fetcher(strategy, legs):
        calls.append((strategy, legs))
        enriched = []
        for leg in legs:
            updated = dict(leg)
            updated["bid"] = 0.45
            updated["ask"] = 0.6
            updated["minTick"] = 0.05
            enriched.append(updated)
        return enriched

    intents = build_exit_intents(
        positions_file="positions.json",
        journal_file="journal.json",
        grouper=lambda positions, journal: copy.deepcopy(aggregated),
        exit_rule_loader=lambda path: {},
        loader=loader,
        quote_fetcher=quote_fetcher,
    )

    assert len(intents) == 1
    assert calls, "quote_fetcher should be invoked when quotes are missing"
    intent = intents[0]
    leg = intent.strategy["legs"][0]
    assert leg["bid"] == 0.45
    assert leg["ask"] == 0.6
    assert leg["minTick"] == 0.05
    assert intent.legs[0]["bid"] == 0.45
    assert intent.legs[0]["ask"] == 0.6
    assert intent.legs[0]["minTick"] == 0.05


def test_build_exit_intents_freshens_quotes_even_when_present():
    positions = [
        {
            "conId": 3001,
            "symbol": "DEF",
            "lastTradeDate": "20240315",
            "strike": 110.0,
            "right": "C",
            "position": -1,
            "bid": 1.2,
            "ask": 1.3,
            "minTick": 0.01,
        }
    ]
    journal = [
        {
            "TradeID": "trade-3",
            "Symbool": "DEF",
            "Expiry": "2024-03-15",
            "Legs": [{"conId": 3001}],
        }
    ]

    loader_payloads = {
        "positions.json": copy.deepcopy(positions),
        "journal.json": copy.deepcopy(journal),
    }

    def loader(path):
        return loader_payloads[path]

    aggregated = [
        {
            "trade_id": "trade-3",
            "symbol": "DEF",
            "expiry": "2024-03-15",
            "type": "single",
            "legs": [
                {"conId": 3001, "strike": 110.0, "position": -1, "right": "call"}
            ],
        }
    ]

    calls: list[tuple[dict, list[dict]]] = []

    def quote_fetcher(strategy, legs):
        calls.append((strategy, legs))
        enriched = []
        for leg in legs:
            updated = dict(leg)
            updated["bid"] = (leg.get("bid") or 1.2) + 0.01
            updated["ask"] = (leg.get("ask") or 1.3) + 0.01
            updated["minTick"] = 0.01
            enriched.append(updated)
        return enriched

    intents = build_exit_intents(
        positions_file="positions.json",
        journal_file="journal.json",
        grouper=lambda positions, journal: copy.deepcopy(aggregated),
        exit_rule_loader=lambda path: {},
        loader=loader,
        quote_fetcher=quote_fetcher,
        freshen_attempts=2,
        freshen_wait_s=0.0,
    )

    assert len(intents) == 1
    assert calls, "quote_fetcher should run when freshen_attempts > 0"
    leg = intents[0].strategy["legs"][0]
    assert math.isclose(leg["bid"], 1.21, rel_tol=1e-9)
    assert math.isclose(leg["ask"], 1.31, rel_tol=1e-9)
