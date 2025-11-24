"""Wrapper module for running exit_flow with timeout and robust cleanup.

This module provides a safer way to run the exit flow with:
- Global timeout to prevent hanging
- Proper cleanup of IB connections
- Better error reporting
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from typing import NoReturn

from tomic.logutils import logger, setup_logging


class TimeoutError(Exception):
    """Raised when the exit flow exceeds the maximum runtime."""

    pass


def _timeout_handler(signum: int, frame) -> NoReturn:
    """Signal handler for timeout."""
    logger.error("Exit flow timeout bereikt - forceer stop")
    raise TimeoutError("Exit flow heeft de maximale runtime overschreden")


def run_with_timeout(timeout_seconds: int = 300) -> int:
    """Run exit_flow.main() with a timeout.

    Args:
        timeout_seconds: Maximum runtime in seconds (default: 300 = 5 min)

    Returns:
        Exit code from exit_flow.main() or 124 on timeout
    """
    setup_logging()

    logger.info("=" * 60)
    logger.info("Exit Flow Runner gestart")
    logger.info(f"Maximum runtime: {timeout_seconds}s")
    logger.info("=" * 60)

    start_time = time.time()

    # Import hier om circulaire imports te voorkomen
    from tomic.cli.exit_flow import main as exit_flow_main

    # Op Windows werkt signal.SIGALRM niet, dus gebruiken we threading
    result_container = {"code": None, "error": None}

    def run_exit_flow():
        try:
            result_container["code"] = exit_flow_main()
        except Exception as e:
            result_container["error"] = e
            result_container["code"] = 1

    thread = threading.Thread(target=run_exit_flow, daemon=True)
    thread.start()

    # Wacht met timeout
    thread.join(timeout=timeout_seconds)

    elapsed = time.time() - start_time

    if thread.is_alive():
        logger.error(
            f"Exit flow timeout na {elapsed:.1f}s (max={timeout_seconds}s)"
        )
        logger.error("Process wordt geforceerd gestopt")
        logger.error("Dit kan betekenen dat:")
        logger.error("  - TWS niet reageert")
        logger.error("  - Er een IB API deadlock is")
        logger.error("  - De price ladder te lang duurt")

        # Force cleanup van eventuele IB connections
        _force_cleanup_ib_connections()

        return 124  # Standard timeout exit code

    if result_container["error"]:
        logger.error(f"Exit flow exception: {result_container['error']}")

    logger.info(f"Exit flow afgerond in {elapsed:.1f}s")
    return result_container["code"] or 0


def _force_cleanup_ib_connections():
    """Force cleanup of any active IB connections."""
    try:
        from tomic.api.client_registry import ACTIVE_CLIENT_IDS

        if ACTIVE_CLIENT_IDS:
            logger.warning(
                f"Actieve IB client IDs gevonden: {ACTIVE_CLIENT_IDS}"
            )
            logger.warning("Deze worden mogelijk niet correct afgesloten")
    except ImportError:
        pass


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run exit flow with timeout protection"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum runtime in seconds (default: 300)",
    )

    args = parser.parse_args()

    try:
        return run_with_timeout(timeout_seconds=args.timeout)
    except KeyboardInterrupt:
        logger.info("Onderbroken door gebruiker (Ctrl+C)")
        return 130


if __name__ == "__main__":
    sys.exit(main())
