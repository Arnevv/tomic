from tomic.analysis.market_overview import build_market_overview


def test_build_market_overview_with_recommendations(monkeypatch):
    rows = [[
        "AAA",
        100.0,
        0.4,
        0.2,
        0.3,
        0.3,
        0.25,
        0.55,
        0.7,
        1.1,
        1.2,
        1.0,
        "2030-01-01",
        15,
    ]]

    recs_stub = [
        {
            "strategy": "short_put_spread",
            "greeks": "delta positive, theta short, vega short",
            "criteria": ["a"],
        },
        {
            "strategy": "calendar",
            "greeks": "delta neutral, theta long, vega long",
            "criteria": ["b"],
        },
    ]

    monkeypatch.setattr(
        "tomic.analysis.market_overview.recommend_strategies",
        lambda metrics: recs_stub,
    )

    recs, table, meta = build_market_overview(rows)
    assert len(recs) == 2
    assert len(table) == 2
    assert recs[0]["category"] == "Vega Short"
    assert table[0][4] == "Long"
    assert table[0][5] == "Short"
    assert table[1][5] == "Long"
    assert meta == {"earnings_filtered": {}}


def test_build_market_overview_no_recommendations(monkeypatch):
    rows = [["BBB", 100.0, 0.3, 0.3, 0.3, 0.3, 0.25, 0.1, 0.2, 1.0, 1.0, 0.0, "", None]]

    monkeypatch.setattr(
        "tomic.analysis.market_overview.recommend_strategies",
        lambda metrics: [],
    )

    recs, table, meta = build_market_overview(rows)
    assert recs == []
    assert table == []
    assert meta == {"earnings_filtered": {}}


def test_build_market_overview_filters_on_strategy_setting(monkeypatch):
    rows = [[
        "CCC",
        200.0,
        0.45,
        0.25,
        0.3,
        0.35,
        0.4,
        0.6,
        0.65,
        1.0,
        1.1,
        0.8,
        "2030-02-01",
        3,
    ]]

    recs_stub = [
        {
            "strategy": "Iron Condor",
            "greeks": "delta neutral, theta short, vega short",
            "criteria": ["a"],
        },
        {
            "strategy": "Short Put Spread",
            "greeks": "delta positive, theta short, vega short",
            "criteria": ["b"],
        },
    ]

    monkeypatch.setattr(
        "tomic.analysis.market_overview.recommend_strategies",
        lambda metrics: recs_stub,
    )

    recs, table, meta = build_market_overview(rows)
    assert len(recs) == 1
    assert recs[0]["strategy"] == "Short Put Spread"
    assert len(table) == 1
    assert meta == {"earnings_filtered": {"CCC": ["Iron Condor"]}}
