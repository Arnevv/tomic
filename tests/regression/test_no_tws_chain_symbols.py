import pathlib
import re

FORBIDDEN = [r"\bOptionChainClient\b", r"\bexport_market_data\b", r"\bStepByStepClient\b"]


def test_no_forbidden_symbols():
    text = "\n".join(
        path.read_text(errors="ignore")
        for path in pathlib.Path("tomic").rglob("*.py")
    )
    assert not any(re.search(pattern, text) for pattern in FORBIDDEN)
