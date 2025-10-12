import tomic.strategy_candidates as sc
from tomic.strategies import StrategyName
from tomic.criteria import CriteriaConfig, MarketDataCriteria, load_criteria


def test_metrics_rejects_low_liquidity(monkeypatch):
    legs = [
        {
            "expiry": "20250101",
            "type": "P",
            "strike": 100,
            "delta": -0.4,
            "bid": 1.0,
            "ask": 1.2,
            "mid": 1.1,
            "edge": 0,
            "model": 1,
            "position": -1,
            "volume": 0,
            "open_interest": 0,
        },
        {
            "expiry": "20250101",
            "type": "P",
            "strike": 90,
            "delta": -0.2,
            "bid": 0.5,
            "ask": 0.7,
            "mid": 0.6,
            "edge": 0,
            "model": 1,
            "position": 1,
            "volume": 0,
            "open_interest": 0,
        },
    ]

    logged: list[str] = []

    class DummyLogger:
        def info(self, msg: str, *args: object, **kwargs: object) -> None:
            if args:
                try:
                    formatted = msg % args
                except Exception:
                    formatted = " ".join([msg, *map(str, args)])
            else:
                formatted = msg
            logged.append(str(formatted))

    import tomic.analysis.scoring as scoring

    monkeypatch.setattr(scoring, "logger", DummyLogger())
    base = load_criteria()
    criteria = CriteriaConfig(
        version=base.version,
        strike=base.strike,
        strategy=base.strategy,
        market_data=MarketDataCriteria(
            min_option_volume=10, min_option_open_interest=10
        ),
        alerts=base.alerts,
        portfolio=base.portfolio,
    )
    metrics, reasons = sc._metrics(StrategyName.SHORT_PUT_SPREAD, legs, criteria=criteria)
    messages = [reason.message for reason in reasons]
    assert metrics is None
    assert any("volume" in r for r in messages)
    assert any(
        "Onvoldoende volume/open interest" in entry for entry in logged
    )
