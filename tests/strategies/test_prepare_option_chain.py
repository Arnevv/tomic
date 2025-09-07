import importlib
import math
from unittest.mock import patch

import pytest
import sys

from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from tomic.strategies.utils import prepare_option_chain


def _get_real_pandas():
    pandas_stub = sys.modules.pop("pandas", None)
    numpy_stub = sys.modules.pop("numpy", None)
    try:
        pandas_real = importlib.import_module("pandas")
        importlib.import_module("numpy")
    except Exception:
        if pandas_stub is not None:
            sys.modules["pandas"] = pandas_stub
        if numpy_stub is not None:
            sys.modules["numpy"] = numpy_stub
        pytest.skip("pandas not available", allow_module_level=True)
    return pandas_real, pandas_stub, numpy_stub


def test_prepare_option_chain_calls_parity_and_updates_mids():
    pandas_real, pandas_stub, numpy_stub = _get_real_pandas()
    try:
        option_chain = [
            {
                "expiration": "2025-07-26",
                "strike": 145.0,
                "type": "call",
                "mid": math.nan,
                "dte": 365,
            },
            {
                "expiration": "2025-07-26",
                "strike": 145.0,
                "type": "put",
                "mid": 5.0,
                "dte": 365,
            },
        ]

        with patch("tomic.strategies.utils.pd", pandas_real), patch(
            "tomic.helpers.put_call_parity.pd", pandas_real
        ):
            with patch(
                "tomic.strategies.utils.fill_missing_mid_with_parity",
                wraps=fill_missing_mid_with_parity,
            ) as mock_fill:
                result = prepare_option_chain(option_chain, 150.0)
                assert mock_fill.called

        call_option = next(o for o in result if o["type"].lower().startswith("c"))
        assert call_option.get("mid_from_parity") is True
        assert not math.isnan(call_option.get("mid"))
    finally:
        if pandas_stub is not None:
            sys.modules["pandas"] = pandas_stub
        else:
            sys.modules.pop("pandas", None)
        if numpy_stub is not None:
            sys.modules["numpy"] = numpy_stub
        else:
            sys.modules.pop("numpy", None)

