#!/usr/bin/env python3
"""
ORATS Research Pipeline
Orchestrates the complete ORATS validation workflow.
"""

import sys
from pathlib import Path
from typing import Optional

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_orats_sample import extract_orats_data
from compare_orats_polygon import compare_datasets

# Try to import plotting, but make it optional
try:
    from plot_skew_comparison import create_all_plots
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
    print("⚠ Matplotlib not available - plots will be skipped")


def copy_polygon_reference_data(polygon_source_dir: Path, polygon_dest_dir: Path) -> int:
    """Copy Polygon reference data to research directory."""
    print(f"\n{'='*60}")
    print(f"COPYING POLYGON REFERENCE DATA")
    print(f"{'='*60}")
    print(f"Source: {polygon_source_dir}")
    print(f"Destination: {polygon_dest_dir}")
    print(f"{'='*60}\n")

    polygon_dest_dir.mkdir(parents=True, exist_ok=True)

    symbols = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]
    copied = 0

    for symbol in symbols:
        source_file = polygon_source_dir / f"{symbol}.json"
        dest_file = polygon_dest_dir / f"{symbol}.json"

        if not source_file.exists():
            print(f"  ⚠ {symbol}.json not found in source")
            continue

        try:
            import shutil
            shutil.copy2(source_file, dest_file)
            print(f"  ✓ Copied {symbol}.json")
            copied += 1
        except Exception as e:
            print(f"  ✗ Error copying {symbol}.json: {e}")

    print(f"\n{'='*60}")
    print(f"Copied {copied}/{len(symbols)} Polygon reference files")
    print(f"{'='*60}\n")

    return copied


def run_orats_research_pipeline(
    orats_input_dir: Optional[Path] = None,
    polygon_source_dir: Optional[Path] = None,
) -> bool:
    """Execute the complete ORATS research pipeline."""

    print("\n" + "="*60)
    print("🔬 ORATS DATA VALIDATION PIPELINE")
    print("="*60)
    print("This pipeline will:")
    print("  1. Extract ORATS data from CSV files")
    print("  2. Copy Polygon reference data")
    print("  3. Compare ORATS vs Polygon metrics")
    print("  4. Generate comparison plots")
    print("  5. Create validation report")
    print("="*60 + "\n")

    # Setup paths
    base_dir = SCRIPTS_DIR.parent
    extracts_dir = base_dir / "Extracts"
    orats_extracts_dir = extracts_dir / "Orats"
    polygon_extracts_dir = extracts_dir / "Polygon"
    results_dir = base_dir / "Results"

    # Default input directories
    if orats_input_dir is None:
        # Try Windows path first, fallback to Linux test path
        windows_path = Path(r"C:\Users\ArnevanVeen\Downloads\Orats5samplefilesOctober")
        linux_path = base_dir / "InputData"
        orats_input_dir = windows_path if windows_path.exists() else linux_path

    if polygon_source_dir is None:
        polygon_source_dir = Path(r"C:\Users\ArnevanVeen\PycharmProjects\Tomic\tomic\data\iv_daily_summary")
        if not polygon_source_dir.exists():
            # Fallback to local tomic installation
            polygon_source_dir = Path("/home/user/tomic/tomic/data/iv_daily_summary")

    # Validate input directories
    if not orats_input_dir.exists():
        print(f"✗ ERROR: ORATS input directory not found: {orats_input_dir}")
        print("Please provide CSV files in:")
        print(f"  - {base_dir / 'InputData'}")
        return False

    if not polygon_source_dir.exists():
        print(f"✗ ERROR: Polygon reference directory not found: {polygon_source_dir}")
        print("Cannot proceed without Polygon reference data")
        return False

    # Step 1: Extract ORATS data
    print("\n[STEP 1/4] Extracting ORATS data from CSV files...")
    try:
        stats = extract_orats_data(orats_input_dir, orats_extracts_dir)
        if not stats or sum(stats.values()) == 0:
            print("✗ No data extracted. Cannot continue.")
            return False
        print(f"✓ Successfully extracted data for {sum(stats.values())} symbol-date pairs")
    except Exception as e:
        print(f"✗ ORATS extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 2: Copy Polygon reference data
    print("\n[STEP 2/4] Copying Polygon reference data...")
    try:
        copied = copy_polygon_reference_data(polygon_source_dir, polygon_extracts_dir)
        if copied == 0:
            print("✗ No Polygon reference data copied. Cannot continue.")
            return False
        print(f"✓ Successfully copied {copied} reference files")
    except Exception as e:
        print(f"✗ Polygon copy failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 3: Compare datasets
    print("\n[STEP 3/4] Comparing ORATS vs Polygon...")
    try:
        results = compare_datasets(orats_extracts_dir, polygon_extracts_dir, results_dir)
        if not results:
            print("✗ No comparisons completed. Cannot continue.")
            return False
        print(f"✓ Successfully compared {len(results)} symbol-date pairs")
    except Exception as e:
        print(f"✗ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Create visualizations
    print("\n[STEP 4/4] Creating comparison plots...")
    if PLOTTING_AVAILABLE:
        try:
            create_all_plots(orats_extracts_dir, polygon_extracts_dir, results_dir)
            print(f"✓ Plots created successfully")
        except Exception as e:
            print(f"⚠ Plot creation failed: {e}")
            print("Continuing without plots...")
            import traceback
            traceback.print_exc()
    else:
        print("⚠ Plotting skipped (matplotlib not installed)")
        print("  Install matplotlib to enable plot generation")

    # Final summary
    print("\n" + "="*60)
    print("✅ ORATS VALIDATION PIPELINE COMPLETE")
    print("="*60)
    print(f"📁 Results saved in: {results_dir}")
    print("\nGenerated files:")
    print(f"  - comparison_report.md")
    print(f"  - plots/*.png (individual comparisons)")
    print(f"  - comparison_summary.png")
    print("\nNext steps:")
    print(f"  1. Review the comparison report: {results_dir / 'comparison_report.md'}")
    print(f"  2. Check plots for visual validation")
    print(f"  3. Make GO/NO-GO decision based on acceptance criteria")
    print("="*60 + "\n")

    return True


if __name__ == "__main__":
    success = run_orats_research_pipeline()
    sys.exit(0 if success else 1)
