"""Validate exported CSV option chain files."""

import csv
import os
import sys
from typing import Any, Dict, List, Set

from tomic.logging import logger

from tomic.logging import setup_logging
from .common import prompt


def is_empty(val: str) -> bool:
    """Return True if the value is None or only whitespace."""
    return val is None or val.strip() == ""


def guess_symbol(path: str) -> str:
    """Derive a ticker symbol from ``path``."""
    name = os.path.basename(path)
    parts = [p for p in name.split("_") if p.isalpha() and p.isupper()]
    return parts[0] if parts else os.path.splitext(name)[0]


def analyze_csv(path: str) -> Dict[str, Any]:
    """Return basic quality metrics for a CSV file."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        total = 0
        complete = 0
        valid = 0
        expiries: Set[str] = set()
        bad_delta = 0
        bad_price_fields = 0
        minus_one_quotes = 0
        duplicates = 0
        empty_counts = {
            "bid": 0,
            "ask": 0,
            "iv": 0,
            "delta": 0,
            "gamma": 0,
            "vega": 0,
            "theta": 0,
        }
        seen: Set[tuple] = set()
        fieldnames = reader.fieldnames or []
        for row in reader:
            total += 1
            row_key = tuple(row.get(h, "").strip() for h in fieldnames)
            is_duplicate = row_key in seen
            if is_duplicate:
                duplicates += 1
            else:
                seen.add(row_key)
            row_invalid = is_duplicate
            # collect expiries
            for k in row.keys():
                if k.lower() == "expiry":
                    val = row[k].strip()
                    if val:
                        expiries.add(val)
                    break
            # count empty fields case-insensitively
            for field in row:
                key_l = field.strip().lower()
                if key_l in empty_counts and is_empty(row[field]):
                    empty_counts[key_l] += 1
                    row_invalid = True

            # delta validation, only check non-empty values
            delta_val = None
            for k in row.keys():
                if k.lower() == "delta":
                    val = row[k].strip()
                    if not is_empty(val):
                        try:
                            delta_val = float(val)
                            if not (-1.0 <= delta_val <= 1.0):
                                bad_delta += 1
                                row_invalid = True
                        except (ValueError, TypeError):
                            bad_delta += 1
                            row_invalid = True
                    else:
                        row_invalid = True
                    break

            # price field checks only on non-empty fields
            invalid = False
            for k in row.keys():
                key_l = k.lower()
                if key_l in {"strike", "bid", "ask"}:
                    val = row[k].strip()
                    if not is_empty(val):
                        try:
                            num = float(val)
                            if key_l in {"bid", "ask"} and num == -1:
                                minus_one_quotes += 1
                                invalid = True
                            if num < 0:
                                raise ValueError
                        except (ValueError, TypeError):
                            invalid = True
                            break
            if invalid:
                bad_price_fields += 1
                row_invalid = True
            # determine completeness
            values = [v.strip() for v in row.values()]
            filled = [v != "" for v in values]
            if all(filled):
                complete += 1
            else:
                row_invalid = True
            if not row_invalid:
                valid += 1
        return {
            "total": total,
            "complete": complete,
            "valid": valid,
            "expiries": sorted(expiries),
            "bad_delta": bad_delta,
            "bad_price_fields": bad_price_fields,
            "duplicates": duplicates,
            "empty_counts": empty_counts,
            "minus_one_quotes": minus_one_quotes,
        }


def main(argv: List[str] | None = None) -> None:
    """Check a CSV export and print quality metrics."""
    if argv is None:
        argv = []
    setup_logging()
    logger.info("🚀 CSV kwaliteitscontrole")
    if argv:
        raw_path = argv[0]
        path = raw_path.strip().strip("'\"")
        symbol = argv[1] if len(argv) > 1 else guess_symbol(path)
    else:
        print("Geen pad meegegeven. Vul handmatig in:")
        raw_path = prompt("Pad naar CSV-bestand: ")
        path = raw_path.strip("'\"")
        if not path:
            print("Geen pad opgegeven.")
            return
        symbol_input = prompt("Symbool (enter voor auto-detect): ")
        symbol = symbol_input or guess_symbol(path)
    if not os.path.isfile(path):

        logger.warning(f"Bestand niet gevonden: {path}")
        return
    stats = analyze_csv(path)
    quality = (stats["valid"] / stats["total"] * 100) if stats["total"] else 0
    expiries_str = " / ".join(stats["expiries"]) if stats["expiries"] else "-"
    logger.warning(f"Markt: {symbol}")
    logger.warning(f"Expiries: {expiries_str}")
    logger.warning(f"Aantal regels: {stats['total']}")
    logger.warning(f"Aantal complete regels: {stats['complete']}")
    logger.warning(f"Aantal geldige regels: {stats['valid']}")
    logger.warning(f"Delta buiten [-1,1]: {stats['bad_delta']}")
    logger.warning(f"Ongeldige Strike/Bid/Ask: {stats['bad_price_fields']}")
    logger.warning(f"Duplicaten: {stats['duplicates']}")
    logger.warning(f"Bid/Ask == -1: {stats['minus_one_quotes']}")
    logger.warning(f"Lege Bid: {stats['empty_counts']['bid']}")
    logger.warning(f"Lege Ask: {stats['empty_counts']['ask']}")
    logger.warning(f"Lege IV: {stats['empty_counts']['iv']}")
    logger.warning(f"Lege Delta: {stats['empty_counts']['delta']}")
    logger.warning(f"Lege Gamma: {stats['empty_counts']['gamma']}")
    logger.warning(f"Lege Vega: {stats['empty_counts']['vega']}")
    logger.warning(f"Lege Theta: {stats['empty_counts']['theta']}")
    logger.warning(f"Kwaliteit: {quality:.1f}%")
    logger.success("✅ Controle afgerond")


if __name__ == "__main__":
    main(sys.argv[1:])
