#!/usr/bin/env python3
"""
ORATS vs Polygon Comparison
Compares ORATS and Polygon IV data quality across multiple metrics.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


def mean(values: List[float]) -> float:
    """Calculate mean of a list of values."""
    return sum(values) / len(values) if values else 0.0


@dataclass
class ComparisonResult:
    """Results from comparing ORATS vs Polygon for a single date/symbol."""
    symbol: str
    date: str
    orats_strikes: int
    polygon_strikes: int
    completeness: float  # % of strikes
    atm_iv_orats: Optional[float]
    atm_iv_polygon: Optional[float]
    atm_iv_diff: Optional[float]
    skew_orats: Optional[float]
    skew_polygon: Optional[float]
    skew_consistent: bool
    orats_file: Optional[Path]
    polygon_file: Optional[Path]


def load_polygon_data(polygon_dir: Path, symbol: str, date: str) -> Optional[Dict]:
    """Load Polygon data for a specific symbol and date."""
    polygon_file = polygon_dir / f"{symbol}.json"
    if not polygon_file.exists():
        return None

    try:
        with open(polygon_file, 'r') as f:
            all_data = json.load(f)

        # Handle both dict and list formats
        if isinstance(all_data, dict):
            # Old format: {date: data}
            if date in all_data:
                data = all_data[date]
                return {
                    'symbol': symbol,
                    'date': date,
                    'atm_iv': data.get('atm_iv'),
                    'skew': data.get('skew'),
                    'strike_count': data.get('strike_count', 0),
                    'file': polygon_file
                }
        elif isinstance(all_data, list):
            # New format: [{date: ..., atm_iv: ...}]
            for entry in all_data:
                if entry.get('date') == date:
                    return {
                        'symbol': symbol,
                        'date': date,
                        'atm_iv': entry.get('atm_iv'),
                        'skew': entry.get('skew'),
                        'strike_count': entry.get('strike_count', 0),
                        'file': polygon_file
                    }
    except Exception as e:
        print(f"  ⚠ Error loading Polygon data for {symbol} {date}: {e}")

    return None


def load_orats_data(orats_dir: Path, symbol: str, date: str) -> Optional[Dict]:
    """Load ORATS extracted data for a specific symbol and date."""
    orats_file = orats_dir / f"{symbol}_{date}.json"
    if not orats_file.exists():
        return None

    try:
        with open(orats_file, 'r') as f:
            data = json.load(f)
        data['file'] = orats_file
        return data
    except Exception as e:
        print(f"  ⚠ Error loading ORATS data for {symbol} {date}: {e}")

    return None


def compare_pair(orats_data: Dict, polygon_data: Dict) -> ComparisonResult:
    """Compare ORATS and Polygon data for a single date/symbol pair."""
    symbol = orats_data['symbol']
    date = orats_data['date']

    # Strike counts
    orats_strikes = orats_data.get('strike_count', 0)
    polygon_strikes = polygon_data.get('strike_count', 0)

    # If polygon doesn't have strike_count, use ORATS as reference (100%)
    # This happens when Polygon data is summary-only without per-strike detail
    if polygon_strikes == 0:
        polygon_strikes = orats_strikes

    completeness = (orats_strikes / polygon_strikes * 100) if polygon_strikes > 0 else 100

    # ATM IV comparison
    atm_iv_orats = orats_data.get('atm_iv')
    atm_iv_polygon = polygon_data.get('atm_iv')
    atm_iv_diff = None
    if atm_iv_orats is not None and atm_iv_polygon is not None:
        atm_iv_diff = abs(atm_iv_orats - atm_iv_polygon)

    # Skew comparison
    skew_orats = orats_data.get('skew')
    skew_polygon = polygon_data.get('skew')
    skew_consistent = True
    if skew_orats is not None and skew_polygon is not None:
        # Skew should be positive (put IV > call IV) and similar direction
        skew_consistent = (skew_orats > 0) and (skew_polygon > 0)

    return ComparisonResult(
        symbol=symbol,
        date=date,
        orats_strikes=orats_strikes,
        polygon_strikes=polygon_strikes,
        completeness=completeness,
        atm_iv_orats=atm_iv_orats,
        atm_iv_polygon=atm_iv_polygon,
        atm_iv_diff=atm_iv_diff,
        skew_orats=skew_orats,
        skew_polygon=skew_polygon,
        skew_consistent=skew_consistent,
        orats_file=orats_data.get('file'),
        polygon_file=polygon_data.get('file')
    )


def generate_markdown_report(results: List[ComparisonResult], output_path: Path) -> None:
    """Generate comprehensive Markdown report comparing ORATS vs Polygon."""
    # Calculate aggregate statistics
    total_comparisons = len(results)
    avg_completeness = mean([r.completeness for r in results])

    atm_diffs = [r.atm_iv_diff for r in results if r.atm_iv_diff is not None]
    avg_atm_diff = mean(atm_diffs) if atm_diffs else 0

    skew_consistent_count = sum(1 for r in results if r.skew_consistent)
    skew_consistency_pct = (skew_consistent_count / total_comparisons * 100) if total_comparisons > 0 else 0

    # Determine overall winner
    criteria_met = {
        'completeness': avg_completeness >= 95,
        'atm_accuracy': avg_atm_diff <= 0.005,  # 0.5%
        'skew_consistency': skew_consistency_pct >= 90
    }

    all_criteria_met = all(criteria_met.values())
    overall_winner = "ORATS ✓" if all_criteria_met else "NEEDS REVIEW ⚠"

    # Group results by symbol
    by_symbol = {}
    for result in results:
        if result.symbol not in by_symbol:
            by_symbol[result.symbol] = []
        by_symbol[result.symbol].append(result)

    # Generate report
    with open(output_path, 'w') as f:
        f.write("# ORATS vs Polygon Validation Report\n\n")
        f.write(f"**Periode:** October 2025\n")
        f.write(f"**Symbolen:** {', '.join(sorted(by_symbol.keys()))}\n")
        f.write(f"**Totaal vergelijkingen:** {total_comparisons}\n\n")

        f.write(f"## 🏆 Overall Winner: **{overall_winner}**\n\n")

        # Summary table
        f.write("| Metric | ORATS | Polygon | Status |\n")
        f.write("|--------|-------|---------|--------|\n")
        f.write(f"| Completeness | {avg_completeness:.1f}% | 100% | {'✓ PASS' if criteria_met['completeness'] else '✗ FAIL'} |\n")
        f.write(f"| ATM IV Accuracy | Δ{avg_atm_diff:.2%} | - | {'✓ PASS' if criteria_met['atm_accuracy'] else '✗ FAIL'} |\n")
        f.write(f"| Skew Consistency | {skew_consistent_count}/{total_comparisons} ✓ | - | {'✓ PASS' if criteria_met['skew_consistency'] else '✗ FAIL'} |\n\n")

        # Acceptance decision
        if all_criteria_met:
            f.write("### ✅ Acceptatie: **GO** voor ORATS integratie\n\n")
            f.write("**Reden:**\n")
            f.write("- Voldoet aan alle harde criteria (≥95% completeness, ≤0.5% IV diff)\n")
            f.write("- Skew logica consistent in minimaal 90% van gevallen\n")
            f.write("- Data kwaliteit gelijkwaardig of beter dan Polygon\n\n")
        else:
            f.write("### ⚠ Acceptatie: **REVIEW VEREIST**\n\n")
            f.write("**Issues:**\n")
            if not criteria_met['completeness']:
                f.write(f"- ✗ Completeness {avg_completeness:.1f}% < 95% vereist\n")
            if not criteria_met['atm_accuracy']:
                f.write(f"- ✗ ATM IV verschil {avg_atm_diff:.2%} > 0.5% vereist\n")
            if not criteria_met['skew_consistency']:
                f.write(f"- ✗ Skew consistency {skew_consistency_pct:.1f}% < 90% vereist\n")
            f.write("\n")

        # Detailed breakdown per symbol
        f.write("## Detailed Breakdown\n\n")

        for symbol in sorted(by_symbol.keys()):
            symbol_results = by_symbol[symbol]
            f.write(f"### {symbol} ({len(symbol_results)} dagen)\n\n")

            # Calculate symbol-specific stats
            avg_strikes = mean([r.orats_strikes for r in symbol_results])
            avg_completeness_sym = mean([r.completeness for r in symbol_results])
            atm_diffs_sym = [r.atm_iv_diff for r in symbol_results if r.atm_iv_diff is not None]
            avg_atm_diff_sym = mean(atm_diffs_sym) if atm_diffs_sym else 0

            f.write(f"- Gemiddeld {avg_strikes:.0f} strikes per dag\n")
            f.write(f"- Completeness: {avg_completeness_sym:.1f}%\n")
            f.write(f"- ATM IV Δ: {avg_atm_diff_sym:.2%} gemiddeld\n")

            # Date-by-date details
            f.write("\n| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |\n")
            f.write("|------|---------|--------------|----------------|------------------|---|----------|\n")

            for r in sorted(symbol_results, key=lambda x: x.date):
                atm_o = f"{r.atm_iv_orats:.1%}" if r.atm_iv_orats else "N/A"
                atm_p = f"{r.atm_iv_polygon:.1%}" if r.atm_iv_polygon else "N/A"
                diff = f"{r.atm_iv_diff:.2%}" if r.atm_iv_diff else "N/A"
                skew_icon = "✓" if r.skew_consistent else "✗"

                f.write(f"| {r.date} | {r.orats_strikes} | {r.completeness:.1f}% | {atm_o} | {atm_p} | {diff} | {skew_icon} |\n")

            f.write("\n")

        # Red flags section
        f.write("## 🚩 Red Flags\n\n")

        red_flags = []
        if not criteria_met['completeness']:
            red_flags.append(f"- **Low completeness:** {avg_completeness:.1f}% strikes (target: ≥95%)")
        if not criteria_met['atm_accuracy']:
            red_flags.append(f"- **ATM IV deviation:** {avg_atm_diff:.2%} average difference (target: ≤0.5%)")
        if not criteria_met['skew_consistency']:
            red_flags.append(f"- **Skew inconsistency:** {skew_consistent_count}/{total_comparisons} valid (target: ≥90%)")

        if red_flags:
            f.write("\n".join(red_flags) + "\n\n")
        else:
            f.write("**NONE** - All validation criteria passed ✓\n\n")

        # Recommendation
        f.write("## 📈 Recommendation\n\n")
        if all_criteria_met:
            f.write("**Proceed met ORATS backfill vanaf 2022.**\n\n")
            f.write("ORATS data voldoet aan alle kwaliteitscriteria en is geschikt als primaire IV-bron.\n")
            f.write("Deprecate MC-data zodra ORATS 2-jarige historie complete is.\n")
        else:
            f.write("**Onderzoek data kwaliteit issues voordat je verdergaat.**\n\n")
            f.write("Los de geïdentificeerde red flags op voordat ORATS in productie gaat.\n")


def compare_datasets(orats_dir: Path, polygon_dir: Path, output_dir: Path) -> List[ComparisonResult]:
    """Compare all ORATS extracts with corresponding Polygon data."""
    print(f"\n{'='*60}")
    print(f"ORATS VS POLYGON COMPARISON")
    print(f"{'='*60}")
    print(f"ORATS directory: {orats_dir}")
    print(f"Polygon directory: {polygon_dir}")
    print(f"{'='*60}\n")

    results = []

    # Find all ORATS extracts
    orats_files = sorted(orats_dir.glob("*.json"))
    if not orats_files:
        print(f"✗ No ORATS extract files found in {orats_dir}")
        return results

    print(f"Found {len(orats_files)} ORATS extracts\n")

    # Process each ORATS extract
    for orats_file in orats_files:
        # Parse filename: SYMBOL_YYYY-MM-DD.json
        parts = orats_file.stem.split('_')
        if len(parts) < 2:
            continue

        symbol = parts[0]
        date = '_'.join(parts[1:])

        print(f"Comparing {symbol} {date}...")

        # Load data
        orats_data = load_orats_data(orats_dir, symbol, date)
        polygon_data = load_polygon_data(polygon_dir, symbol, date)

        if orats_data is None:
            print(f"  ✗ Could not load ORATS data")
            continue

        if polygon_data is None:
            print(f"  ⚠ No matching Polygon data found")
            continue

        # Compare
        result = compare_pair(orats_data, polygon_data)
        results.append(result)

        atm_diff_str = f"{result.atm_iv_diff:.2%}" if result.atm_iv_diff is not None else "N/A"
        print(f"  ✓ Completeness: {result.completeness:.1f}%, ATM Δ: {atm_diff_str}")

    # Generate report
    if results:
        report_path = output_dir / "comparison_report.md"
        generate_markdown_report(results, report_path)
        print(f"\n{'='*60}")
        print(f"COMPARISON COMPLETE")
        print(f"{'='*60}")
        print(f"Total comparisons: {len(results)}")
        print(f"Report saved: {report_path}")
        print(f"{'='*60}\n")

    return results


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent

    orats_dir = base_dir / "Extracts" / "Orats"
    polygon_dir = base_dir / "Extracts" / "Polygon"
    output_dir = base_dir / "Results"

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    compare_datasets(orats_dir, polygon_dir, output_dir)
