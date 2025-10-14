"""Tests for the volatility fetcher helpers."""

from tomic.analysis.volatility_fetcher import _parse_vix_from_yahoo


def test_parse_vix_from_yahoo_regular_market_price():
    html = """
        {"regularMarketPrice":{"raw":19.52,"fmt":"19.52"}}
    """

    assert _parse_vix_from_yahoo(html) == 19.52


def test_parse_vix_from_yahoo_fin_streamer_value():
    html = """
        <fin-streamer data-symbol="^VIX" value="17.31">17.31</fin-streamer>
    """

    assert _parse_vix_from_yahoo(html) == 17.31
