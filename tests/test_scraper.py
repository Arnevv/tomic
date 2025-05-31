from daily_vol_scraper import _parse_patterns


def test_parse_patterns_success():
    html = "Spot: 101 <span>IV Rank 45%</span>"
    patterns = {"spot_price": [r"Spot: (\d+)"], "iv_rank": [r"IV Rank (\d+)%"]}
    result = _parse_patterns(patterns, html)
    assert result == {"spot_price": 101.0, "iv_rank": 45.0}


def test_parse_patterns_missing_and_invalid():
    html = "Value: x"
    patterns = {"foo": [r"Value: (\d+)"]}
    result = _parse_patterns(patterns, html)
    assert result == {"foo": None}
