import tomic.logutils as logutils
from tomic.core.pricing.mid_tags import MidTagSnapshot
from tomic.logutils import _LoggerProxy, log_combo_evaluation, normalize_reason
from tomic.strategy.reasons import ReasonCategory


def test_normalize_reason_exact_and_casefold():
    detail = normalize_reason("fallback naar close gebruikt voor midprijs")
    assert detail.category == ReasonCategory.PREVIEW_QUALITY
    assert detail.data.get("mid_source") == "close"
    assert normalize_reason("Onvoldoende Volume").category == ReasonCategory.LOW_LIQUIDITY
    assert normalize_reason("Previewkwaliteit").category == ReasonCategory.PREVIEW_QUALITY
    assert normalize_reason(None).category == ReasonCategory.OTHER


def test_logger_proxy_formats_percent_style_messages():
    events = []

    class DummyLogger:
        def info(self, message, **kwargs):
            events.append(("info", message, kwargs))

        def opt(self, **kwargs):
            events.append(("opt", kwargs))
            return self

    proxy = _LoggerProxy(DummyLogger())
    proxy.info("volatility=%s", 20.5)

    assert events == [("info", "volatility=20.5", {})]


def test_logger_proxy_respects_exc_info():
    events = []

    class DummyLogger:
        def info(self, message, **kwargs):
            events.append(("info", message, kwargs))

        def opt(self, **kwargs):
            events.append(("opt", kwargs))
            return self

    proxy = _LoggerProxy(DummyLogger())
    proxy.info("failure", exc_info=True)

    assert events == [("opt", {"exception": True}), ("info", "failure", {})]


def test_log_combo_evaluation_includes_mid_metadata(monkeypatch):
    messages: list[str] = []

    class DummyLogger:
        def info(self, message, **kwargs):
            messages.append(message)

    monkeypatch.setattr(logutils, "logger", DummyLogger())

    snapshot = MidTagSnapshot(tags=("tradable", "true:1"), counters={"true": 1})

    log_combo_evaluation(
        "iron_condor",
        "demo",
        {"pos": 55.0, "max_profit": 120.0, "max_loss": -200.0, "ev": 0.42},
        "pass",
        ReasonCategory.PREVIEW_QUALITY,
        legs=[{"type": "call", "strike": 100, "expiry": "2024-01-19", "position": -1}],
        extra={"mid": snapshot},
    )

    assert any("mid_tags=tradable,true:1" in msg for msg in messages)
    assert any("mid_counts=true:1" in msg for msg in messages)
