from tomic.webdata.utils import to_float


def test_to_float_parses_percentage_string():
    assert to_float(" 12,34 %") == 12.34


def test_to_float_handles_invalid_value():
    assert to_float("abc") is None
