"""Wrapper module for running entry_flow with timeout and data sync.

This module provides a safe way to run the entry flow with:
- Git pull to fetch latest IV data from GitHub
- Global timeout to prevent hanging
- Proper cleanup of IB connections
- Better error reporting

Designed for Windows Task Scheduler / cron scheduling.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NoReturn

from tomic.logutils import logger, setup_logging


class TimeoutError(Exception):
    """Raised when the entry flow exceeds the maximum runtime."""

    pass


class GitSyncError(Exception):
    """Raised when git pull fails."""

    pass


def _get_repo_root() -> Path:
    """Find the git repository root directory."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    raise FileNotFoundError("Geen git repository gevonden")


def sync_data_from_remote(
    *,
    timeout_seconds: int = 60,
    branch: str = "main",
) -> bool:
    """Pull latest data from remote repository.

    This syncs IV data that was updated by GitHub Actions.

    Args:
        timeout_seconds: Maximum time to wait for git pull.
        branch: Branch to pull from.

    Returns:
        True if sync succeeded, False otherwise.
    """
    logger.info("🔄 Synchroniseren van data via git pull...")

    try:
        repo_root = _get_repo_root()
    except FileNotFoundError as exc:
        logger.warning("Git sync overgeslagen: %s", exc)
        return False

    try:
        # First fetch to see if there are updates
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if fetch_result.returncode != 0:
            logger.warning("Git fetch mislukt: %s", fetch_result.stderr)
            return False

        # Check if we're behind
        status_result = subprocess.run(
            ["git", "status", "-uno"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if "Your branch is behind" in status_result.stdout:
            logger.info("Updates beschikbaar, pullen...")

            # Pull changes
            pull_result = subprocess.run(
                ["git", "pull", "origin", branch, "--ff-only"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            if pull_result.returncode != 0:
                logger.error("Git pull mislukt: %s", pull_result.stderr)
                return False

            logger.info("✅ Git pull succesvol")
            return True
        else:
            logger.info("✅ Lokale data is actueel")
            return True

    except subprocess.TimeoutExpired:
        logger.error("Git sync timeout na %ds", timeout_seconds)
        return False
    except FileNotFoundError:
        logger.warning("Git niet gevonden - sync overgeslagen")
        return False
    except Exception as exc:
        logger.exception("Git sync fout: %s", exc)
        return False


def _force_cleanup_ib_connections():
    """Force cleanup of any active IB connections.

    This clears the ACTIVE_CLIENT_IDS registry to allow future connections
    with the same client IDs.
    """
    try:
        from tomic.api.client_registry import ACTIVE_CLIENT_IDS

        if ACTIVE_CLIENT_IDS:
            stale_ids = list(ACTIVE_CLIENT_IDS)
            logger.warning(
                "Cleaning up %d stale IB client IDs: %s",
                len(stale_ids),
                stale_ids,
            )
            ACTIVE_CLIENT_IDS.clear()
            logger.info("Client ID registry cleared")
        else:
            logger.debug("No active IB client IDs to clean up")
    except ImportError:
        logger.debug("Could not import client_registry for cleanup")


def run_with_timeout(
    timeout_seconds: int = 300,
    *,
    skip_git_sync: bool = False,
    git_timeout: int = 60,
) -> int:
    """Run entry_flow with timeout and data sync.

    Args:
        timeout_seconds: Maximum runtime in seconds (default: 300 = 5 min).
        skip_git_sync: Skip git pull step if True.
        git_timeout: Timeout for git operations.

    Returns:
        Exit code: 0 for success, 1 for failure, 124 for timeout.
    """
    # Use stdout=True to avoid PowerShell NativeCommandError
    # PowerShell treats stderr output as errors, even for INFO logs
    setup_logging(stdout=True)

    logger.info("=" * 60)
    logger.info("Entry Flow Runner gestart")
    logger.info(f"Maximum runtime: {timeout_seconds}s")
    logger.info("=" * 60)

    # Step 1: Sync data from remote
    if not skip_git_sync:
        sync_ok = sync_data_from_remote(timeout_seconds=git_timeout)
        if not sync_ok:
            logger.warning("Git sync niet gelukt - ga door met lokale data")
    else:
        logger.info("Git sync overgeslagen (--skip-git-sync)")

    start_time = time.time()

    # Import here to avoid circular imports
    from tomic.services.entry_flow import execute_entry_flow

    result_container = {"result": None, "error": None}

    def run_entry_flow():
        try:
            result_container["result"] = execute_entry_flow()
        except Exception as e:
            result_container["error"] = e

    thread = threading.Thread(target=run_entry_flow, daemon=True)
    thread.start()

    # Wait with timeout
    thread.join(timeout=timeout_seconds)

    elapsed = time.time() - start_time

    if thread.is_alive():
        logger.error(
            "Entry flow timeout na %.1fs (max=%ds)",
            elapsed,
            timeout_seconds,
        )
        logger.error("Process wordt geforceerd gestopt")
        logger.error("Dit kan betekenen dat:")
        logger.error("  - TWS niet reageert of is afgesloten")
        logger.error("  - Er een IB API deadlock is")
        logger.error("  - De Polygon API te traag is")
        logger.error("Tip: Check of TWS/IB Gateway draait op de geconfigureerde poort")

        _force_cleanup_ib_connections()
        return 124  # Standard timeout exit code

    # Always cleanup stale connections after completion
    _force_cleanup_ib_connections()

    if result_container["error"]:
        logger.error("Entry flow exception: %s", result_container["error"])
        return 1

    result = result_container["result"]
    if result is None:
        logger.error("Entry flow returned None")
        return 1

    logger.info("Entry flow afgerond in %.1fs", elapsed)
    logger.info("Status: %s", result.status)
    logger.info("Entries: %d succesvol, %d mislukt",
                result.successful_entries, result.failed_entries)

    # Return 0 for success or partial success
    if result.status in ("success", "partial", "no_candidates", "no_slots", "no_entries"):
        return 0
    return 1


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run entry flow with timeout protection and data sync"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum runtime in seconds (default: 300)",
    )
    parser.add_argument(
        "--skip-git-sync",
        action="store_true",
        help="Skip git pull step",
    )
    parser.add_argument(
        "--git-timeout",
        type=int,
        default=60,
        help="Git operation timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    try:
        return run_with_timeout(
            timeout_seconds=args.timeout,
            skip_git_sync=args.skip_git_sync,
            git_timeout=args.git_timeout,
        )
    except KeyboardInterrupt:
        logger.info("Onderbroken door gebruiker (Ctrl+C)")
        return 130


if __name__ == "__main__":
    sys.exit(main())
