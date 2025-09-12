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

    recs, table = build_market_overview(rows)
    assert len(recs) == 2
    assert len(table) == 2
    assert recs[0]["category"] == "Vega Short"
    assert table[0][4] == "Long"
    assert table[0][5] == "Short"
    assert table[1][5] == "Long"


def test_build_market_overview_no_recommendations(monkeypatch):
    rows = [["BBB", 100.0, 0.3, 0.3, 0.3, 0.3, 0.25, 0.1, 0.2, 1.0, 1.0, 0.0, ""]]

    monkeypatch.setattr(
        "tomic.analysis.market_overview.recommend_strategies",
        lambda metrics: [],
    )

    recs, table = build_market_overview(rows)
    assert recs == []
    assert table == []
