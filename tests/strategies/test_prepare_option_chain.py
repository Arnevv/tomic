from unittest.mock import patch

from tomic.core.data import normalize_chain_records
from tomic.strategies.utils import prepare_option_chain


def test_prepare_option_chain_calls_normalizer_and_marks_parity():
    option_chain = [
        {
            "expiration": "2025-07-26",
            "strike": 145.0,
            "type": "call",
            "mid": None,
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

    with patch(
        "tomic.strategies.utils.normalize_chain_records",
        wraps=normalize_chain_records,
    ) as mock_normalize:
        result = prepare_option_chain(option_chain, 150.0)

    assert mock_normalize.called
    _, kwargs = mock_normalize.call_args
    assert kwargs.get("apply_parity") is True

    call_option = next(o for o in result if o["type"].lower().startswith("c"))
    assert call_option.get("mid_from_parity") is True
    assert call_option.get("mid") is not None

