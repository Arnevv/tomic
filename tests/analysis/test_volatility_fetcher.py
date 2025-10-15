"""Tests for the volatility fetcher helpers."""

from tomic.analysis.volatility_fetcher import (
    _parse_vix_from_google,
    _parse_vix_from_yahoo,
)


def test_parse_vix_from_yahoo_regular_market_price():
    html = """
        {"regularMarketPrice":{"raw":19.52,"fmt":"19.52"}}
    """

    assert _parse_vix_from_yahoo(html) == 19.52


def test_parse_vix_from_yahoo_fin_streamer_value():
    html = """
        <fin-streamer data-field="regularMarketPrice" data-symbol="^VIX" value="17.31">17.31</fin-streamer>
    """

    assert _parse_vix_from_yahoo(html) == 17.31


def test_parse_vix_from_yahoo_skips_other_fields():
    html = """
        <fin-streamer data-symbol="^VIX" data-field="fiftyTwoWeekHigh" value="71.04">71.04</fin-streamer>
        <fin-streamer data-symbol="^VIX" data-field="regularMarketPrice" value="19.88">19.88</fin-streamer>
    """

    assert _parse_vix_from_yahoo(html) == 19.88


def test_parse_vix_from_google_data_last_price():
    html = '<div data-last-price="19.42"></div>'

    assert _parse_vix_from_google(html) == 19.42


def test_parse_vix_from_google_price_class():
    html = '<div class="YMlKec fxKbKc"> 20.01</div>'

    assert _parse_vix_from_google(html) == 20.01
