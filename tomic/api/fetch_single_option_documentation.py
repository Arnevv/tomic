from __future__ import annotations

import csv
import sys
from typing import List, Dict

import requests

BASE_URL = "http://localhost:5000/v1/api"


def fetch_contracts(symbol: str, expiry: str, base_url: str = BASE_URL) -> List[Dict]:
    """Fetch option contracts for ``symbol`` and ``expiry`` via WebAPI."""
    r = requests.get(f"{base_url}/iserver/secdef/search", params={"symbol": symbol})
    r.raise_for_status()
    search = r.json()
    if not search:
        return []
    conid = search[0].get("conid")
    r = requests.get(
        f"{base_url}/iserver/secdef/strikes",
        params={"conid": conid, "sectype": "OPT"},
    )
    r.raise_for_status()
    strikes = r.json().get("strikes", [])
    rows: List[Dict] = []
    for strike in strikes:
        for right in ("C", "P"):
            params = {
                "conid": conid,
                "sectype": "OPT",
                "month": expiry.replace("-", ""),
                "strike": strike,
                "right": right,
            }
            info_resp = requests.get(f"{base_url}/iserver/secdef/info", params=params)
            info_resp.raise_for_status()
            info = info_resp.json()
            if isinstance(info, list):
                if info:
                    info = info[0]
                else:
                    info = {}
            row = {
                "symbol": symbol,
                "expiry": expiry,
                "strike": strike,
                "right": right,
            }
            if isinstance(info, dict):
                row.update(info)
            rows.append(row)
    return rows


def save_contracts(rows: List[Dict], path: str) -> None:
    """Write option contracts to ``path`` as CSV."""
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run(symbol: str = "AAPL", expiry: str = "2025-06-20") -> str:
    """Fetch option contracts and save them to ``MayContracts.csv``."""
    rows = fetch_contracts(symbol, expiry)
    output = "MayContracts.csv"
    save_contracts(rows, output)
    return output


def main(argv: List[str] | None = None) -> None:
    """Command-line entry point."""
    if argv is None:
        argv = sys.argv[1:]
    symbol = argv[0] if len(argv) > 0 else "AAPL"
    expiry = argv[1] if len(argv) > 1 else "2025-06-20"
    run(symbol, expiry)


if __name__ == "__main__":
    main()
