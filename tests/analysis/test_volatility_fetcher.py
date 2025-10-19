"""Tests for the volatility fetcher helpers."""

import asyncio
import importlib

import tomic.analysis.volatility_fetcher as vf


def test_parse_vix_from_yahoo_regular_market_price():
    html = """
        {"regularMarketPrice":{"raw":19.52,"fmt":"19.52"}}
    """

    assert vf._parse_vix_from_yahoo(html) == 19.52


def test_parse_vix_from_yahoo_fin_streamer_value():
    html = """
        <fin-streamer data-field="regularMarketPrice" data-symbol="^VIX" value="17.31">17.31</fin-streamer>
    """

    assert vf._parse_vix_from_yahoo(html) == 17.31


def test_parse_vix_from_yahoo_skips_other_fields():
    html = """
        <fin-streamer data-symbol="^VIX" data-field="fiftyTwoWeekHigh" value="71.04">71.04</fin-streamer>
        <fin-streamer data-symbol="^VIX" data-field="regularMarketPrice" value="19.88">19.88</fin-streamer>
    """

    assert vf._parse_vix_from_yahoo(html) == 19.88


def test_parse_vix_from_google_data_last_price():
    html = '<div data-last-price="19.42"></div>'

    assert vf._parse_vix_from_google(html) == 19.42


def test_parse_vix_from_google_price_class():
    html = '<div class="YMlKec fxKbKc"> 20.01</div>'

    assert vf._parse_vix_from_google(html) == 20.01


def test_daily_cache_hit(tmp_path, monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.analysis.volatility_fetcher"))
    config = mod.VixConfig(daily_store=str(tmp_path / "daily.csv"), provider_order=["ibkr"])
    mod._save_daily_vix(config, 18.42, "json_api")

    calls: list[str] = []

    async def failing_provider() -> mod._VixFetcherResult:  # type: ignore[attr-defined]
        calls.append("ibkr")
        return None, None, "unreachable"

    monkeypatch.setitem(mod._VIX_SOURCE_FETCHERS, "ibkr", failing_provider)
    monkeypatch.setattr(mod, "_vix_settings", lambda: config)
    mod._VIX_CACHE.clear()

    value, source = asyncio.run(mod._get_vix_value())

    assert value is not None and abs(value - 18.42) < 1e-6
    assert source == "json_api"
    assert calls == []


def test_orchestrator_uses_provider_and_updates_cache(tmp_path, monkeypatch):
    mod = importlib.reload(importlib.import_module("tomic.analysis.volatility_fetcher"))
    store = tmp_path / "daily.csv"
    config = mod.VixConfig(
        daily_store=str(store),
        provider_order=["ibkr", "json_api"],
    )

    async def failing_provider() -> mod._VixFetcherResult:  # type: ignore[attr-defined]
        return None, None, "failed"

    async def succeeding_provider() -> mod._VixFetcherResult:  # type: ignore[attr-defined]
        return 21.7, "json_api", None

    monkeypatch.setitem(mod._VIX_SOURCE_FETCHERS, "ibkr", failing_provider)
    monkeypatch.setitem(mod._VIX_SOURCE_FETCHERS, "json_api", succeeding_provider)
    monkeypatch.setattr(mod, "_vix_settings", lambda: config)
    mod._VIX_CACHE.clear()

    value, source = asyncio.run(mod._get_vix_value())

    assert value is not None and abs(value - 21.7) < 1e-6
    assert source == "json_api"
    assert store.exists()
    assert mod._VIX_CACHE["value"] is not None and abs(mod._VIX_CACHE["value"] - 21.7) < 1e-6
    assert mod._VIX_CACHE["source"] == "json_api"
