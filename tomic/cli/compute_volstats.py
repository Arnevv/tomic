from __future__ import annotations

"""CLI entrypoint to compute volatility statistics."""

from typing import List

from tomic.config import get as cfg_get  # re-exported for monkeypatching in tests
from tomic.logutils import setup_logging

from .services import volatility as _vol_service

fetch_iv30d = _vol_service.fetch_iv30d
historical_volatility = _vol_service.historical_volatility
update_json_file = _vol_service.update_json_file
_get_closes = _vol_service._get_closes
logger = _vol_service.logger


def _sync_overrides() -> None:
    """Propagate patched helpers to the underlying service module."""

    _vol_service.cfg_get = cfg_get
    _vol_service.fetch_iv30d = fetch_iv30d
    _vol_service.historical_volatility = historical_volatility
    _vol_service.update_json_file = update_json_file
    _vol_service._get_closes = _get_closes
    _vol_service.logger = logger


def compute_volatility_stats(symbols: List[str] | None = None) -> list[str]:
    _sync_overrides()
    return _vol_service.compute_volatility_stats(symbols)


def main(argv: List[str] | None = None) -> None:
    """Compute volatility statistics for configured or provided symbols."""
    setup_logging()
    symbols = [s.upper() for s in argv] if argv else None
    compute_volatility_stats(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
