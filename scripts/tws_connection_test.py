"""
Simple TWS/IB Gateway Availability Test Script

Checks if IB Gateway is running and accepting connections on the configured port.
Uses a proper IB API connection with handshake to avoid leaving the gateway in a
bad state that could cause subsequent connections to fail.
"""

import sys
import os

# Add the project root to the path so we can import tomic modules
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def check_ib_connection(host: str = "127.0.0.1", port: int = 4002, timeout: float = 5.0) -> bool:
    """Check if IB Gateway is accepting API connections with proper handshake."""
    try:
        from tomic.api.ib_connection import connect_ib

        # Use a unique client ID to avoid conflicts
        # Connect with a short timeout to fail fast if gateway is not ready
        app = connect_ib(
            client_id=999,  # Use a dedicated test client ID
            host=host,
            port=port,
            timeout=int(timeout),
            connect_timeout=timeout,
        )
        # If we get here, connection succeeded - clean up properly
        try:
            app.disconnect()
        except Exception:
            pass
        return True
    except Exception as e:
        # Connection failed - could be timeout, refused, or handshake failure
        print(f"Connection check failed: {e}")
        return False


def main():
    """Check if IB Gateway is reachable on port 4002."""
    host = "127.0.0.1"
    port = 4002  # IB Gateway paper trading port

    print("IB Gateway Availability Test")
    print("=============================")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print()

    print("Checking if IB Gateway is accepting API connections...")

    if check_ib_connection(host, port):
        print()
        print("SUCCESS: IB Gateway is reachable and accepting API connections!")
        return 0
    else:
        print()
        print("ERROR: IB Gateway not reachable or not accepting API connections.")
        print("Make sure IB Gateway is running and API connections are enabled.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
