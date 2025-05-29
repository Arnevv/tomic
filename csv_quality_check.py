import csv
import os
import sys
from typing import List, Dict, Set, Any


def is_empty(val: str) -> bool:
    """Return True if the value is None or only whitespace."""
    return val is None or val.strip() == ''


def guess_symbol(path: str) -> str:
    name = os.path.basename(path)
    parts = [p for p in name.split('_') if p.isalpha() and p.isupper()]
    return parts[0] if parts else os.path.splitext(name)[0]


def analyze_csv(path: str) -> Dict[str, Any]:
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        total = 0
        complete = 0
        expiries: Set[str] = set()
        bad_delta = 0
        bad_price_fields = 0
        duplicates = 0
        empty_counts = {
            'bid': 0,
            'ask': 0,
            'iv': 0,
            'delta': 0,
            'gamma': 0,
            'vega': 0,
            'theta': 0,
        }
        seen: Set[tuple] = set()
        fieldnames = reader.fieldnames or []
        for row in reader:
            total += 1
            key = tuple(row.get(h, '').strip() for h in fieldnames)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
            # collect expiries
            for k in row.keys():
                if k.lower() == 'expiry':
                    val = row[k].strip()
                    if val:
                        expiries.add(val)
                    break
            # count empty fields case-insensitively
            for key in row:
                key_l = key.strip().lower()
                if key_l in empty_counts and is_empty(row[key]):
                    empty_counts[key_l] += 1

            # delta validation, only check non-empty values
            delta_val = None
            for k in row.keys():
                if k.lower() == 'delta':
                    val = row[k].strip()
                    if not is_empty(val):
                        try:
                            delta_val = float(val)
                            if not (-1.0 <= delta_val <= 1.0):
                                bad_delta += 1
                        except (ValueError, TypeError):
                            bad_delta += 1
                    break

            # price field checks only on non-empty fields
            invalid = False
            for k in row.keys():
                if k.lower() in {'strike', 'bid', 'ask'}:
                    val = row[k].strip()
                    if not is_empty(val):
                        try:
                            num = float(val)
                            if num < 0:
                                raise ValueError
                        except (ValueError, TypeError):
                            invalid = True
                            break
            if invalid:
                bad_price_fields += 1
            # determine completeness
            values = [v.strip() for v in row.values()]
            filled = [v != '' for v in values]
            if all(filled):
                complete += 1
        return {
            'total': total,
            'complete': complete,
            'expiries': sorted(expiries),
            'bad_delta': bad_delta,
            'bad_price_fields': bad_price_fields,
            'duplicates': duplicates,
            'empty_counts': empty_counts,
        }


def main(argv: List[str]) -> None:
    if argv:
        raw_path = argv[0]
        path = raw_path.strip().strip("'\"")
        symbol = argv[1] if len(argv) > 1 else guess_symbol(path)
    else:
        print('Geen pad meegegeven. Vul handmatig in:')
        raw_path = input('Pad naar CSV-bestand: ').strip()
        path = raw_path.strip("'\"")
        if not path:
            print('Geen pad opgegeven.')
            return
        symbol_input = input('Symbool (enter voor auto-detect): ').strip()
        symbol = symbol_input or guess_symbol(path)
    if not os.path.isfile(path):
        print(f'Bestand niet gevonden: {path}')
        return
    stats = analyze_csv(path)
    quality = (stats['complete'] / stats['total'] * 100) if stats['total'] else 0
    expiries_str = ' / '.join(stats['expiries']) if stats['expiries'] else '-'
    print(f"Markt: {symbol}")
    print(f"Expiries: {expiries_str}")
    print(f"Aantal regels: {stats['total']}")
    print(f"Aantal complete regels: {stats['complete']}")
    print(f"Delta buiten [-1,1]: {stats['bad_delta']}")
    print(f"Ongeldige Strike/Bid/Ask: {stats['bad_price_fields']}")
    print(f"Duplicaten: {stats['duplicates']}")
    print(f"Lege Bid: {stats['empty_counts']['bid']}")
    print(f"Lege Ask: {stats['empty_counts']['ask']}")
    print(f"Lege IV: {stats['empty_counts']['iv']}")
    print(f"Lege Delta: {stats['empty_counts']['delta']}")
    print(f"Lege Gamma: {stats['empty_counts']['gamma']}")
    print(f"Lege Vega: {stats['empty_counts']['vega']}")
    print(f"Lege Theta: {stats['empty_counts']['theta']}")
    print(f"Kwaliteit: {quality:.1f}%")


if __name__ == '__main__':
    main(sys.argv[1:])
