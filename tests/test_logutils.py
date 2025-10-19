from tomic.logutils import _LoggerProxy, normalize_reason
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
