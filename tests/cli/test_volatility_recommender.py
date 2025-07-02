from tomic.cli.volatility_recommender import recommend_strategy


def test_recommend_strategy_match():
    metrics = {
        "iv_rank": 55,
        "iv_percentile": 70,
        "skew": 4,
        "term_m1_m3": 1.2,
        "IV": 0.4,
        "HV20": 0.2,
    }
    rec = recommend_strategy(metrics)
    assert rec and rec["strategy"] == "short_put_spread"
    assert rec.get("export_heatmap") is True
    assert rec.get("heatmap_columns") == ["strike", "delta", "iv"]


def test_recommend_strategy_none():
    metrics = {
        "iv_rank": 10,
        "iv_percentile": 20,
        "skew": 0,
        "term_m1_m3": 0,
        "IV": 0.3,
        "HV20": 0.4,
    }
    rec = recommend_strategy(metrics)
    assert rec is None
