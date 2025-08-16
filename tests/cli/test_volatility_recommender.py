from tomic.cli.volatility_recommender import recommend_strategy, recommend_strategies


def test_recommend_strategy_match():
    metrics = {
        "iv_rank": 0.55,
        "iv_percentile": 0.70,
        "skew": 4,
        "term_m1_m3": 1.2,
        "IV": 0.4,
        "HV20": 0.2,
        "HV90": 0.3,
        "iv_vs_hv20": 0.2,
        "iv_vs_hv90": 0.1,
    }
    rec = recommend_strategy(metrics)
    assert rec and rec["strategy"] == "short_put_spread"
    assert rec.get("export_heatmap") is True
    assert rec.get("heatmap_columns") == ["strike", "delta", "iv"]


def test_recommend_strategy_none():
    metrics = {
        "iv_rank": 0.10,
        "iv_percentile": 0.20,
        "skew": 0,
        "term_m1_m3": 0,
        "IV": 0.3,
        "HV20": 0.4,
        "HV90": 0.5,
        "iv_vs_hv20": -0.1,
        "iv_vs_hv90": -0.2,
    }
    rec = recommend_strategy(metrics)
    assert rec is None


def test_recommend_strategies_multiple():
    metrics = {
        "iv_rank": 0.60,
        "iv_percentile": 0.70,
        "skew": 1.0,
        "term_m1_m3": 1.2,
        "IV": 0.4,
        "HV20": 0.2,
        "HV90": 0.3,
        "iv_vs_hv20": 0.2,
        "iv_vs_hv90": 0.1,
    }
    recs = recommend_strategies(metrics)
    names = {r["strategy"] for r in recs}
    assert "iron_condor" in names
    assert len(recs) >= 2


def test_recommend_strategies_none():
    metrics = {
        "iv_rank": 0.05,
        "iv_percentile": 0.10,
        "skew": 0,
        "term_m1_m3": 0,
        "IV": 0.2,
        "HV20": 0.3,
        "HV90": 0.25,
        "iv_vs_hv20": -0.1,
        "iv_vs_hv90": -0.05,
    }
    recs = recommend_strategies(metrics)
    assert recs == []
