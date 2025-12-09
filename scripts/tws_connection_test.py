"""
Simple TWS/IB Gateway Availability Test Script

Checks if IB Gateway is running and accepting connections on the configured port.
Uses a simple TCP socket check to avoid client ID conflicts with other running
applications (like the web backend).
"""

import socket
import sys


def check_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """Check if a TCP port is open and accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
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

    print("Checking if IB Gateway is accepting connections...")

    if check_port_open(host, port):
        print()
        print("SUCCESS: IB Gateway is reachable on port 4002!")
        print("(Using TCP check to avoid client ID conflicts with web backend)")
        return 0
    else:
        print()
        print("ERROR: IB Gateway not reachable on port 4002.")
        print("Make sure IB Gateway is running and API connections are enabled.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
