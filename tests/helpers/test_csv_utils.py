import importlib
import pytest

pd = importlib.import_module("pandas")
if getattr(pd, "DataFrame", object) is object:
    pytest.skip("pandas not available", allow_module_level=True)

from tomic.helpers.csv_utils import normalize_european_number_format, parse_euro_float


def test_normalize_european_number_format():
    df = pd.DataFrame(
        {
            "iv": ["0,25", "0,30", "1.234,56"],
            "close": ["28.583,69", "5", "11.405.000"],
        }
    )
    result = normalize_european_number_format(df, ["iv", "close"])
    assert result["iv"].tolist() == [0.25, 0.30, 1234.56]
    assert result["close"].tolist() == [28583.69, 5.0, 11405000.0]


def test_parse_euro_float():
    assert parse_euro_float("1.234,56") == 1234.56
    assert parse_euro_float("0,9939") == 0.9939
    assert parse_euro_float("11.405.000") == 11405000.0
    assert parse_euro_float(None) is None
