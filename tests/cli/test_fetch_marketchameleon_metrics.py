import importlib

mod = importlib.import_module("tomic.cli.fetch_marketchameleon_metrics")


def test_parse_iv_html():
    html = """
    Last Price <span>123.45</span>
    30-Day IV <span>0.25</span>
    IV30 % Rank <span>55%</span>
    20-Day HV <span>0.2</span>
    1-Year HV <span>0.3</span>
    """
    result = mod.parse_iv_html(html)
    assert result["spot_price"] == 123.45
    assert result["iv30"] == 0.25
    assert result["iv_rank"] == 55.0
    assert result["hv_20"] == 0.2
    assert result["hv_252"] == 0.3


def test_parse_skew_html():
    html = "Skew: <strong>-1.5</strong>"
    assert mod.parse_skew_html(html) == -1.5
