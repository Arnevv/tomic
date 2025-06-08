from tomic.webdata.utils import parse_patterns
from tomic.analysis.iv_patterns import EXTRA_PATTERNS


def test_parse_skew_from_simple_html():
    html = "<div>Skew:</span> <span><strong>-0.25%</strong></span></div>"
    result = parse_patterns({"skew": EXTRA_PATTERNS["skew"]}, html)
    assert result["skew"] == -0.25


def test_parse_skew_ignores_week_prefix():
    html = "Skew 4 Week -1.20%"
    result = parse_patterns({"skew": EXTRA_PATTERNS["skew"]}, html)
    assert result["skew"] == -1.20
