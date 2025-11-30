"""
Simple TWS Connection Test Script

Connects to TWS with client ID 999, verifies the connection, and disconnects cleanly.
"""

import sys
import time
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tomic.api.ib_connection import connect_ib


def main():
    """Connect to TWS with client ID 999 and disconnect."""
    client_id = 999
    host = "127.0.0.1"
    port = 7497  # Paper trading port

    print(f"TWS Connection Test")
    print(f"==================")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Client ID: {client_id}")
    print()

    app = None
    try:
        print("Connecting to TWS...")
        app = connect_ib(
            client_id=client_id,
            host=host,
            port=port,
            timeout=10,
            connect_timeout=15.0,
        )

        print(f"Connected! Next valid order ID: {app.next_valid_id}")

        # Small delay to ensure connection is stable
        time.sleep(1)

        print("Disconnecting...")
        app.disconnect()
        app = None  # Mark as disconnected

        print()
        print("SUCCESS: TWS connection test completed successfully!")
        return 0

    except ConnectionRefusedError:
        print()
        print("ERROR: Connection refused.")
        print("Make sure TWS/IB Gateway is running and accepting connections.")
        return 1

    except TimeoutError as e:
        print()
        print(f"ERROR: Connection timed out: {e}")
        print("Check if TWS/IB Gateway is running on the correct port.")
        return 1

    except Exception as e:
        print()
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    finally:
        # Always clean up the connection to avoid leaving sessions open
        if app is not None:
            try:
                print("Cleaning up connection...")
                app.disconnect()
            except Exception:
                pass  # Ignore errors during cleanup


if __name__ == "__main__":
    sys.exit(main())
