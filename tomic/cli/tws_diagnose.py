"""TWS connection diagnostic tool.

This module provides a CLI command to diagnose TWS connection issues.

Usage:
    python -m tomic.cli.tws_diagnose
    python -m tomic.cli.tws_diagnose --port 7496 --clear
"""

from __future__ import annotations

import argparse
import sys
from pprint import pformat

from tomic.logutils import logger, setup_logging


def main() -> int:
    """Run TWS connection diagnostics."""
    parser = argparse.ArgumentParser(
        description="Diagnose TWS/IB Gateway connection issues"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="TWS host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7497,
        help="TWS port (default: 7497 for paper, 7496 for live)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear stale client IDs from registry before diagnosis",
    )
    parser.add_argument(
        "--test-connect",
        action="store_true",
        help="Also test a full IB connection (uses client_id 999)",
    )

    args = parser.parse_args()
    setup_logging()

    print("=" * 60)
    print("TWS Connection Diagnostic Tool")
    print("=" * 60)
    print()

    from tomic.api.ib_connection import (
        diagnose_tws_connection,
        clear_stale_client_ids,
        connect_ib,
        ACTIVE_CLIENT_IDS,
    )

    # Optionally clear stale client IDs first
    if args.clear:
        print("Clearing stale client IDs...")
        cleared = clear_stale_client_ids()
        if cleared:
            print(f"  Cleared {len(cleared)} client IDs: {cleared}")
        else:
            print("  No client IDs to clear")
        print()

    # Run diagnosis
    print(f"Diagnosing connection to {args.host}:{args.port}...")
    print()

    report = diagnose_tws_connection(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
    )

    # Print report
    print("Diagnostic Report:")
    print("-" * 40)
    print(f"  Host: {report['host']}")
    print(f"  Port: {report['port']}")
    print(f"  Socket Reachable: {report['socket_reachable']}")
    if report['socket_error']:
        print(f"  Socket Error: {report['socket_error']}")
    if report['connection_time_ms'] is not None:
        print(f"  Connection Time: {report['connection_time_ms']}ms")
    print(f"  TWS Responsive: {report['tws_responsive']}")
    print(f"  Active Client IDs: {report['active_client_ids']}")
    print(f"  Active Count: {report['active_count']}")
    print()

    # Provide recommendations
    print("Recommendations:")
    print("-" * 40)

    if not report['socket_reachable']:
        print("  [ERROR] Cannot reach TWS on socket level!")
        print("    - Is TWS/IB Gateway running?")
        print("    - Check if API is enabled in TWS Configuration")
        print("    - Verify the correct port (7497=paper, 7496=live)")
        return 1

    if not report['tws_responsive']:
        print("  [WARNING] Socket connected but TWS did not respond")
        print("    - TWS may be busy or in an error state")
        print("    - Try restarting TWS")
        print("    - Check TWS API settings")

    if report['active_count'] > 0:
        print(f"  [WARNING] {report['active_count']} client ID(s) already registered")
        print("    - This may indicate zombie connections")
        print("    - Run with --clear to clear stale client IDs")
        print("    - Or restart your Python process")

    if report['socket_reachable'] and report['active_count'] == 0:
        print("  [OK] TWS appears to be running and accessible")

    # Optional: test full connection
    if args.test_connect and report['socket_reachable']:
        print()
        print("Testing full IB connection...")
        print("-" * 40)
        test_client_id = 999
        try:
            app = connect_ib(
                client_id=test_client_id,
                host=args.host,
                port=args.port,
                timeout=int(args.timeout),
            )
            print(f"  [SUCCESS] Connected with client_id={test_client_id}")
            print(f"  nextValidId: {app.next_valid_id}")
            print(f"  isConnected: {app.isConnected()}")

            # Disconnect
            app.disconnect()
            print("  Disconnected successfully")
            print(f"  Active IDs after disconnect: {list(ACTIVE_CLIENT_IDS)}")
        except Exception as e:
            print(f"  [ERROR] Connection failed: {e}")
            return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
