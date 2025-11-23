#!/usr/bin/env python3
"""Generate test ORATS CSV data based on Polygon data."""

import json
import csv
import random
import math
from pathlib import Path


def generate_orats_test_data():
    """Generate test ORATS CSV files based on Polygon data."""

    polygon_dir = Path("/home/user/tomic/tomic/data/iv_daily_summary")
    output_dir = Path("/home/user/tomic/OratsResearch/InputData")
    output_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]
    test_dates = ["2025-11-19", "2025-11-20", "2025-11-21"]

    # Typical spot prices (approximate)
    spot_prices = {
        "SPY": 590.0,
        "AAPL": 230.0,
        "MSFT": 420.0,
        "NVDA": 145.0,
        "TSLA": 340.0,
    }

    for date in test_dates:
        csv_filename = output_dir / f"orats_{date.replace('-', '')}.csv"

        with open(csv_filename, 'w', newline='') as csvfile:
            fieldnames = [
                'ticker', 'cOpra', 'pOpra', 'stkPx', 'expirDate', 'yte', 'strike',
                'cVolu', 'cOi', 'pVolu', 'pOi', 'cBidPx', 'cValue', 'cAskPx',
                'pBidPx', 'pValue', 'pAskPx', 'cBidIv', 'cMidIv', 'cAskIv',
                'smoothSmvVol', 'pBidIv', 'pMidIv', 'pAskIv', 'iRate', 'divRate',
                'residualRateData', 'delta', 'gamma', 'theta', 'vega', 'rho',
                'phi', 'driftlessTheta', 'extVol', 'extCTheo', 'extPTheo',
                'spot_px', 'trade_date'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for symbol in symbols:
                spot = spot_prices[symbol]

                # Load Polygon data for reference ATM IV
                polygon_file = polygon_dir / f"{symbol}.json"
                atm_iv_base = 0.20  # Default

                if polygon_file.exists():
                    with open(polygon_file, 'r') as f:
                        polygon_data = json.load(f)
                        for entry in polygon_data:
                            if entry.get('date') == date and entry.get('atm_iv'):
                                atm_iv_base = entry['atm_iv']
                                break

                # Generate strikes around spot (90% to 110% of spot)
                num_strikes = 50
                strikes = [spot * 0.90 + (spot * 0.20 / (num_strikes - 1)) * i for i in range(num_strikes)]

                for strike in strikes:
                    # Calculate moneyness
                    moneyness = strike / spot

                    # Approximate delta (simplified Black-Scholes)
                    if moneyness < 1:
                        # ITM call, OTM put
                        call_delta = 0.5 + (1 - moneyness) * 0.4
                        put_delta = -(0.5 - (1 - moneyness) * 0.4)
                    else:
                        # OTM call, ITM put
                        call_delta = 0.5 - (moneyness - 1) * 0.4
                        put_delta = -(0.5 + (moneyness - 1) * 0.4)

                    # Clip delta to valid range
                    call_delta = max(0.01, min(0.99, call_delta))
                    put_delta = max(-0.99, min(-0.01, put_delta))

                    # IV skew: put IV > ATM IV > call IV
                    # OTM puts have higher IV, OTM calls have lower IV
                    if moneyness < 1:
                        # ITM call, OTM put
                        call_iv = atm_iv_base * 0.95  # Slightly lower
                        put_iv = atm_iv_base * (1 + (1 - moneyness) * 0.5)  # Higher for OTM puts
                    else:
                        # OTM call, ITM put
                        call_iv = atm_iv_base * (1 - (moneyness - 1) * 0.3)  # Lower for OTM calls
                        put_iv = atm_iv_base * 1.05  # Slightly higher

                    # Add some noise
                    call_iv *= (1 + random.uniform(-0.02, 0.02))
                    put_iv *= (1 + random.uniform(-0.02, 0.02))

                    # Generate volumes (more volume near ATM)
                    volume_factor = math.exp(-5 * (moneyness - 1)**2)
                    call_volume = int(random.uniform(10, 500) * volume_factor)
                    put_volume = int(random.uniform(10, 500) * volume_factor)

                    row = {
                        'ticker': symbol,
                        'cOpra': f'{symbol}{date[2:4]}{date[5:7]}{date[8:10]}C{int(strike*1000):08d}',
                        'pOpra': f'{symbol}{date[2:4]}{date[5:7]}{date[8:10]}P{int(strike*1000):08d}',
                        'stkPx': spot,
                        'expirDate': '2025-12-19',  # 30 DTE
                        'yte': 0.082,  # ~30 days
                        'strike': strike,
                        'cVolu': call_volume,
                        'cOi': int(call_volume * 3),
                        'pVolu': put_volume,
                        'pOi': int(put_volume * 3),
                        'cBidPx': max(0.05, (spot - strike) * 0.9) if strike < spot else 0.10,
                        'cValue': max(0.10, spot - strike) if strike < spot else 0.15,
                        'cAskPx': max(0.15, (spot - strike) * 1.1) if strike < spot else 0.20,
                        'pBidPx': max(0.05, (strike - spot) * 0.9) if strike > spot else 0.10,
                        'pValue': max(0.10, strike - spot) if strike > spot else 0.15,
                        'pAskPx': max(0.15, (strike - spot) * 1.1) if strike > spot else 0.20,
                        'cBidIv': call_iv * 0.98,
                        'cMidIv': call_iv,
                        'cAskIv': call_iv * 1.02,
                        'smoothSmvVol': (call_iv + put_iv) / 2,
                        'pBidIv': put_iv * 0.98,
                        'pMidIv': put_iv,
                        'pAskIv': put_iv * 1.02,
                        'iRate': 0.045,
                        'divRate': 0.015,
                        'residualRateData': 0.030,
                        'delta': call_delta,  # Using call delta
                        'gamma': 0.01,
                        'theta': -0.05,
                        'vega': 0.20,
                        'rho': 0.15,
                        'phi': -0.10,
                        'driftlessTheta': -0.04,
                        'extVol': (call_iv + put_iv) / 2,
                        'extCTheo': max(0.10, spot - strike) if strike < spot else 0.15,
                        'extPTheo': max(0.10, strike - spot) if strike > spot else 0.15,
                        'spot_px': spot,
                        'trade_date': date
                    }

                    writer.writerow(row)

        print(f"✓ Generated {csv_filename.name} with {len(symbols) * len(strikes)} rows")

    print(f"\n✅ Test ORATS data generated in {output_dir}")


if __name__ == "__main__":
    generate_orats_test_data()
