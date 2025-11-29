"""
TWS Connection Comparison Test

Tests both IBClient (direct) and QuoteSnapshotApp to isolate the problem.
"""

import sys
import time
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tomic.api.ib_connection import connect_ib, IBClient
from tomic.services.ib_marketdata import QuoteSnapshotApp


def test_ibclient():
    """Test with IBClient (default)."""
    print("\n" + "=" * 50)
    print("TEST 1: IBClient (default)")
    print("=" * 50)

    try:
        print("Connecting...")
        app = connect_ib(
            client_id=997,
            host="127.0.0.1",
            port=7497,
            timeout=10,
            connect_timeout=15.0,
        )
        print(f"✅ SUCCESS - isConnected={app.isConnected()}")
        time.sleep(0.5)
        app.disconnect()
        print("   Disconnected cleanly")
        return True
    except Exception as e:
        print(f"❌ FAILED - {type(e).__name__}: {e}")
        return False


def test_quotesnapshotapp():
    """Test with QuoteSnapshotApp (same as exit_flow)."""
    print("\n" + "=" * 50)
    print("TEST 2: QuoteSnapshotApp (same as exit_flow)")
    print("=" * 50)

    try:
        print("Creating QuoteSnapshotApp...")
        app = QuoteSnapshotApp()

        print("Connecting...")
        connect_ib(
            client_id=996,
            host="127.0.0.1",
            port=7497,
            timeout=10,
            app=app,
            connect_timeout=15.0,
        )
        print(f"✅ SUCCESS - isConnected={app.isConnected()}")
        time.sleep(0.5)
        app.disconnect()
        print("   Disconnected cleanly")
        return True
    except Exception as e:
        print(f"❌ FAILED - {type(e).__name__}: {e}")
        return False


def main():
    print("TWS Connection Comparison Test")
    print("Testing both app types to isolate the problem")

    # Wait between tests to let TWS recover
    result1 = test_ibclient()
    time.sleep(2)
    result2 = test_quotesnapshotapp()

    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"IBClient:         {'✅ WORKS' if result1 else '❌ FAILS'}")
    print(f"QuoteSnapshotApp: {'✅ WORKS' if result2 else '❌ FAILS'}")

    if result1 and not result2:
        print("\n⚠️  CONCLUSION: Problem is in QuoteSnapshotApp class")
    elif not result1 and not result2:
        print("\n⚠️  CONCLUSION: TWS connection issue (both fail)")
    elif result1 and result2:
        print("\n✅ CONCLUSION: Both work - problem may be timing/state related")

    return 0 if (result1 and result2) else 1


if __name__ == "__main__":
    sys.exit(main())
