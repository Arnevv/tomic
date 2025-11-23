#!/usr/bin/env python3
"""
ORATS vs Polygon Skew Visualization
Creates visual comparisons of IV skew curves.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend


def load_json_data(file_path: Path) -> Optional[Dict]:
    """Load JSON data from file."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠ Error loading {file_path}: {e}")
        return None


def plot_skew_comparison(orats_data: Dict, polygon_data: Dict, output_path: Path) -> bool:
    """Create skew comparison plot for a single date/symbol."""
    try:
        symbol = orats_data['symbol']
        date = orats_data['date']
        spot = orats_data['spot_price']

        # Extract ORATS strikes
        orats_strikes = []
        orats_ivs = []
        for strike_data in orats_data.get('strikes', []):
            strike = strike_data['strike']
            # Use call IV for OTM calls, put IV for OTM puts
            if strike >= spot:
                iv = strike_data.get('call_iv')
            else:
                iv = strike_data.get('put_iv')

            if iv is not None and iv > 0:
                orats_strikes.append(strike / spot * 100)  # % of spot
                orats_ivs.append(iv * 100)  # Convert to percentage

        # Note: Polygon data format is per-date summary, not per-strike
        # We'll just show the ORATS curve and metrics comparison
        fig, ax = plt.subplots(figsize=(12, 7))

        # Plot ORATS skew curve
        if orats_strikes and orats_ivs:
            sorted_pairs = sorted(zip(orats_strikes, orats_ivs))
            orats_strikes_sorted = [p[0] for p in sorted_pairs]
            orats_ivs_sorted = [p[1] for p in sorted_pairs]

            ax.plot(orats_strikes_sorted, orats_ivs_sorted, 'o-',
                   color='#2E86DE', linewidth=2, markersize=4,
                   label='ORATS', alpha=0.8)

        # Add vertical line at ATM
        ax.axvline(x=100, color='gray', linestyle='--', alpha=0.5, label='ATM')

        # Add annotations
        textbox = []
        textbox.append(f"Symbol: {symbol}")
        textbox.append(f"Date: {date}")
        textbox.append(f"Spot: ${spot:.2f}")
        textbox.append("")

        # ORATS metrics
        if orats_data.get('atm_iv'):
            textbox.append(f"ORATS ATM IV: {orats_data['atm_iv']:.1%}")
        if orats_data.get('skew'):
            textbox.append(f"ORATS Skew: {orats_data['skew']:.1%}")
        textbox.append(f"ORATS Strikes: {orats_data.get('strike_count', 0)}")

        # Polygon metrics
        textbox.append("")
        if polygon_data.get('atm_iv'):
            textbox.append(f"Polygon ATM IV: {polygon_data['atm_iv']:.1%}")
        if polygon_data.get('skew'):
            textbox.append(f"Polygon Skew: {polygon_data['skew']:.1%}")
        if polygon_data.get('strike_count'):
            textbox.append(f"Polygon Strikes: {polygon_data['strike_count']}")

        # Add comparison
        if orats_data.get('atm_iv') and polygon_data.get('atm_iv'):
            diff = abs(orats_data['atm_iv'] - polygon_data['atm_iv'])
            textbox.append("")
            textbox.append(f"ATM IV Δ: {diff:.2%}")

        # Place textbox
        ax.text(0.02, 0.98, '\n'.join(textbox),
               transform=ax.transAxes,
               verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
               fontfamily='monospace',
               fontsize=9)

        # Styling
        ax.set_xlabel('Strike (% of Spot)', fontsize=12)
        ax.set_ylabel('Implied Volatility (%)', fontsize=12)
        ax.set_title(f'{symbol} IV Skew - {date}', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right')

        # Save
        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close()

        return True

    except Exception as e:
        print(f"  ✗ Error creating plot: {e}")
        return False


def create_summary_plot(all_results: List[Dict], output_path: Path) -> bool:
    """Create summary plot comparing ORATS vs Polygon across all dates."""
    try:
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))

        symbols = sorted(set(r['symbol'] for r in all_results))
        colors = plt.cm.tab10(range(len(symbols)))
        symbol_colors = dict(zip(symbols, colors))

        # Plot 1: Completeness over time
        for symbol in symbols:
            symbol_results = [r for r in all_results if r['symbol'] == symbol]
            dates = [r['date'] for r in symbol_results]
            completeness = [r['completeness'] for r in symbol_results]

            ax1.plot(range(len(dates)), completeness, 'o-',
                    color=symbol_colors[symbol], label=symbol, linewidth=2)

        ax1.axhline(y=95, color='green', linestyle='--', alpha=0.5, label='Target (95%)')
        ax1.set_ylabel('Completeness (%)', fontsize=11)
        ax1.set_title('Strike Completeness (ORATS vs Polygon)', fontsize=12, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Plot 2: ATM IV Accuracy
        for symbol in symbols:
            symbol_results = [r for r in all_results if r['symbol'] == symbol]
            dates = [r['date'] for r in symbol_results]
            atm_diffs = [r.get('atm_diff', 0) * 100 for r in symbol_results]  # To percentage

            ax2.plot(range(len(dates)), atm_diffs, 'o-',
                    color=symbol_colors[symbol], label=symbol, linewidth=2)

        ax2.axhline(y=0.5, color='green', linestyle='--', alpha=0.5, label='Target (0.5%)')
        ax2.set_ylabel('ATM IV Difference (%)', fontsize=11)
        ax2.set_title('ATM IV Accuracy', fontsize=12, fontweight='bold')
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # Plot 3: Strike counts comparison
        orats_counts = []
        polygon_counts = []
        labels = []

        for symbol in symbols:
            symbol_results = [r for r in all_results if r['symbol'] == symbol]
            avg_orats = sum(r['orats_strikes'] for r in symbol_results) / len(symbol_results)
            avg_polygon = sum(r['polygon_strikes'] for r in symbol_results) / len(symbol_results)

            orats_counts.append(avg_orats)
            polygon_counts.append(avg_polygon)
            labels.append(symbol)

        x = range(len(labels))
        width = 0.35

        ax3.bar([i - width/2 for i in x], orats_counts, width, label='ORATS', color='#2E86DE', alpha=0.8)
        ax3.bar([i + width/2 for i in x], polygon_counts, width, label='Polygon', color='#FF6B6B', alpha=0.8)

        ax3.set_ylabel('Average Strikes', fontsize=11)
        ax3.set_title('Average Strike Count per Symbol', fontsize=12, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels(labels)
        ax3.legend()
        ax3.grid(True, alpha=0.3, axis='y')

        # Plot 4: Overall quality score
        quality_scores = []
        for symbol in symbols:
            symbol_results = [r for r in all_results if r['symbol'] == symbol]

            # Calculate quality score (0-100)
            avg_completeness = sum(r['completeness'] for r in symbol_results) / len(symbol_results)
            avg_atm_diff = sum(r.get('atm_diff', 0) for r in symbol_results) / len(symbol_results)

            # Score: completeness weight 50%, accuracy weight 50%
            completeness_score = avg_completeness * 0.5
            accuracy_score = max(0, (1 - avg_atm_diff * 200)) * 50  # 0.5% diff = full score

            quality_score = completeness_score + accuracy_score
            quality_scores.append(quality_score)

        ax4.barh(labels, quality_scores, color=[symbol_colors[s] for s in symbols], alpha=0.8)
        ax4.axvline(x=90, color='green', linestyle='--', alpha=0.5, label='Excellent (90+)')
        ax4.set_xlabel('Quality Score', fontsize=11)
        ax4.set_title('Overall Data Quality Score by Symbol', fontsize=12, fontweight='bold')
        ax4.set_xlim(0, 100)
        ax4.legend()
        ax4.grid(True, alpha=0.3, axis='x')

        plt.suptitle('ORATS vs Polygon - Quality Comparison Summary',
                    fontsize=16, fontweight='bold', y=1.00)

        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches='tight')
        plt.close()

        return True

    except Exception as e:
        print(f"  ✗ Error creating summary plot: {e}")
        return False


def create_all_plots(orats_dir: Path, polygon_dir: Path, output_dir: Path) -> None:
    """Create all comparison plots."""
    print(f"\n{'='*60}")
    print(f"SKEW VISUALIZATION")
    print(f"{'='*60}\n")

    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Find all ORATS extracts
    orats_files = sorted(orats_dir.glob("*.json"))
    if not orats_files:
        print(f"✗ No ORATS files found")
        return

    plot_count = 0
    all_results = []

    for orats_file in orats_files:
        # Parse filename
        parts = orats_file.stem.split('_')
        if len(parts) < 2:
            continue

        symbol = parts[0]
        date = '_'.join(parts[1:])

        # Load ORATS data
        orats_data = load_json_data(orats_file)
        if not orats_data:
            continue

        # Load Polygon data
        polygon_file = polygon_dir / f"{symbol}.json"
        if not polygon_file.exists():
            print(f"  ⚠ No Polygon data for {symbol}")
            continue

        with open(polygon_file, 'r') as f:
            polygon_all = json.load(f)

        # Handle both dict and list formats
        polygon_data = None
        if isinstance(polygon_all, dict):
            if date in polygon_all:
                polygon_data = polygon_all[date]
        elif isinstance(polygon_all, list):
            for entry in polygon_all:
                if entry.get('date') == date:
                    polygon_data = entry
                    break

        if not polygon_data:
            print(f"  ⚠ No Polygon data for {symbol} {date}")
            continue

        polygon_data['symbol'] = symbol
        polygon_data['date'] = date

        # Create plot
        output_path = plots_dir / f"{symbol}_{date}.png"
        if plot_skew_comparison(orats_data, polygon_data, output_path):
            print(f"  ✓ Created plot: {output_path.name}")
            plot_count += 1

            # Collect data for summary
            all_results.append({
                'symbol': symbol,
                'date': date,
                'orats_strikes': orats_data.get('strike_count', 0),
                'polygon_strikes': polygon_data.get('strike_count', 0),
                'completeness': (orats_data.get('strike_count', 0) /
                               polygon_data.get('strike_count', 1) * 100),
                'atm_diff': abs(orats_data.get('atm_iv', 0) - polygon_data.get('atm_iv', 0))
            })

    # Create summary plot
    if all_results:
        summary_path = output_dir / "comparison_summary.png"
        if create_summary_plot(all_results, summary_path):
            print(f"\n  ✓ Created summary plot: {summary_path.name}")

    print(f"\n{'='*60}")
    print(f"Created {plot_count} comparison plots")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent

    orats_dir = base_dir / "Extracts" / "Orats"
    polygon_dir = base_dir / "Extracts" / "Polygon"
    output_dir = base_dir / "Results"

    create_all_plots(orats_dir, polygon_dir, output_dir)
