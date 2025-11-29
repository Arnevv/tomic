"""
TWS Connection Test using QuoteSnapshotApp

This test uses the same app class as exit_flow to isolate the problem.
"""

import sys
import time
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tomic.api.ib_connection import connect_ib
from tomic.services.ib_marketdata import QuoteSnapshotApp


def main():
    """Connect to TWS using QuoteSnapshotApp (same as exit_flow)."""
    client_id = 998  # Different from 999 to avoid conflicts
    host = "127.0.0.1"
    port = 7497

    print("TWS Connection Test (QuoteSnapshotApp)")
    print("=" * 45)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Client ID: {client_id}")
    print(f"App class: QuoteSnapshotApp")
    print()

    try:
        # Create QuoteSnapshotApp instance - same as exit_flow does
        print("Creating QuoteSnapshotApp instance...")
        app = QuoteSnapshotApp()

        print("Connecting to TWS...")
        connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=10,
            app=app,  # Pass the app instance - same as exit_flow
            connect_timeout=15.0,
        )

        print(f"Connected! isConnected={app.isConnected()}")

        # Small delay to ensure connection is stable
        time.sleep(1)

        print("Disconnecting...")
        app.disconnect()

        print()
        print("SUCCESS: QuoteSnapshotApp connection test completed!")
        return 0

    except Exception as e:
        print()
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
