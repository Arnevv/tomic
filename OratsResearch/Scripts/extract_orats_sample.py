#!/usr/bin/env python3
"""
ORATS Data Extractor
Extracts specific symbols from ORATS CSV files and converts to normalized JSON format.
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Optional


# Target symbols to extract
TARGET_SYMBOLS = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]


def safe_float(value) -> Optional[float]:
    """Safely convert value to float."""
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def calculate_atm_iv(rows: List[Dict], spot_px: float) -> Optional[float]:
    """Calculate ATM IV from strikes closest to spot price."""
    if not rows:
        return None

    # Find strikes closest to ATM with distance
    rows_with_distance = []
    for row in rows:
        strike = safe_float(row.get('strike'))
        if strike is not None:
            distance = abs(strike - spot_px)
            rows_with_distance.append((distance, row))

    # Sort by distance and take top 5
    rows_with_distance.sort(key=lambda x: x[0])
    atm_options = [row for _, row in rows_with_distance[:5]]

    # Use mid IV (average of call and put)
    valid_ivs = []
    for row in atm_options:
        c_mid_iv = safe_float(row.get('cMidIv'))
        p_mid_iv = safe_float(row.get('pMidIv'))
        if c_mid_iv is not None:
            valid_ivs.append(c_mid_iv)
        if p_mid_iv is not None:
            valid_ivs.append(p_mid_iv)

    return sum(valid_ivs) / len(valid_ivs) if valid_ivs else None


def find_delta_iv(rows: List[Dict], target_delta: float, option_type: str) -> Optional[float]:
    """Find IV for specific delta level (0.25 for 25 delta)."""
    if not rows:
        return None

    iv_col = 'cMidIv' if option_type == 'call' else 'pMidIv'

    # For puts, delta is negative, so we look for -0.25
    if option_type == 'put':
        target_delta = -abs(target_delta)

    # Filter valid rows and find closest delta match
    valid_rows = []
    for row in rows:
        delta = safe_float(row.get('delta'))
        iv = safe_float(row.get(iv_col))
        if delta is not None and iv is not None:
            delta_distance = abs(delta - target_delta)
            valid_rows.append((delta_distance, iv))

    if not valid_rows:
        return None

    # Sort by delta distance and take top 3
    valid_rows.sort(key=lambda x: x[0])
    closest_ivs = [iv for _, iv in valid_rows[:3]]

    return sum(closest_ivs) / len(closest_ivs) if closest_ivs else None


def process_orats_date(csv_path: Path, symbol: str, output_dir: Path) -> bool:
    """Process single ORATS CSV file for a specific symbol."""
    try:
        print(f"  Processing {csv_path.name} for {symbol}...")

        # Read CSV and filter for target symbol
        symbol_rows = []
        with open(csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get('ticker') == symbol:
                    symbol_rows.append(row)

        if not symbol_rows:
            print(f"    ⚠ No data found for {symbol}")
            return False

        # Get trade date and spot price from first row
        trade_date = symbol_rows[0]['trade_date']
        spot_price = safe_float(symbol_rows[0]['spot_px'])

        if spot_price is None:
            print(f"    ⚠ Invalid spot price for {symbol}")
            return False

        # Calculate metrics
        atm_iv = calculate_atm_iv(symbol_rows, spot_price)
        put_25d_iv = find_delta_iv(symbol_rows, 0.25, 'put')
        call_25d_iv = find_delta_iv(symbol_rows, 0.25, 'call')

        # Calculate skew
        skew = None
        if put_25d_iv is not None and call_25d_iv is not None:
            skew = put_25d_iv - call_25d_iv

        # Build strikes array
        strikes = []
        for row in symbol_rows:
            strike = safe_float(row.get('strike'))
            if strike is None:
                continue

            strike_data = {
                'strike': strike,
                'delta': safe_float(row.get('delta')),
                'call_iv': safe_float(row.get('cMidIv')),
                'put_iv': safe_float(row.get('pMidIv')),
                'call_volume': int(safe_float(row.get('cVolu')) or 0),
                'put_volume': int(safe_float(row.get('pVolu')) or 0),
            }
            strikes.append(strike_data)

        # Build output JSON
        output_data = {
            'symbol': symbol,
            'date': trade_date,
            'spot_price': spot_price,
            'atm_iv': atm_iv,
            'put_25d_iv': put_25d_iv,
            'call_25d_iv': call_25d_iv,
            'skew': skew,
            'strike_count': len(strikes),
            'strikes': strikes
        }

        # Write to JSON
        output_file = output_dir / f"{symbol}_{trade_date}.json"
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        atm_display = f"{atm_iv:.1%}" if atm_iv else "N/A"
        print(f"    ✓ {symbol} {trade_date}: {len(strikes)} strikes, ATM {atm_display}")
        return True

    except Exception as e:
        print(f"    ✗ Error processing {csv_path.name} for {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return False


def extract_orats_data(input_dir: Path, output_dir: Path) -> Dict[str, int]:
    """Extract ORATS data for all target symbols."""
    print(f"\n{'='*60}")
    print(f"ORATS DATA EXTRACTOR")
    print(f"{'='*60}")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Target symbols: {', '.join(TARGET_SYMBOLS)}")
    print(f"{'='*60}\n")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all CSV files
    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        print(f"✗ No CSV files found in {input_dir}")
        return {}

    print(f"Found {len(csv_files)} CSV files\n")

    # Process each file
    stats = {symbol: 0 for symbol in TARGET_SYMBOLS}

    for csv_file in csv_files:
        for symbol in TARGET_SYMBOLS:
            if process_orats_date(csv_file, symbol, output_dir):
                stats[symbol] += 1

    # Print summary
    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    for symbol, count in stats.items():
        print(f"  {symbol}: {count} dates extracted")
    print(f"{'='*60}\n")

    return stats


if __name__ == "__main__":
    import sys

    # Default paths
    if len(sys.argv) > 1:
        input_dir = Path(sys.argv[1])
    else:
        # Try Windows path first, fallback to Linux test path
        windows_path = Path(r"C:\Users\ArnevanVeen\Downloads\Orats5samplefilesOctober")
        linux_path = Path("/home/user/tomic/OratsResearch/InputData")
        input_dir = windows_path if windows_path.exists() else linux_path

    output_dir = Path(__file__).parent.parent / "Extracts" / "Orats"

    extract_orats_data(input_dir, output_dir)
