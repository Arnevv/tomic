from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from datetime import datetime
import csv

from tomic.logutils import setup_logging
from tomic.config import get as cfg_get
from tomic.api.getonemarket import run_async
from tomic.cli import csv_quality_check


async def bench_async(symbols: list[str]) -> float:
    start = time.perf_counter()
    await asyncio.gather(*(run_async(sym, simple=True) for sym in symbols))
    return time.perf_counter() - start


def find_latest_chain() -> Path | None:
    today = datetime.now().strftime("%Y%m%d")
    base = Path(cfg_get("EXPORT_DIR", "exports")) / today
    if not base.is_dir():
        return None
    chains = sorted(base.glob("option_chain_*.csv"), key=lambda p: p.stat().st_mtime)
    return chains[-1] if chains else None


def write_result_csv(
    symbols: list[str], runtime: float, quality: float | None, chain: Path | None
) -> Path | None:
    """Write benchmark results next to the latest option chain CSV."""

    if chain is None:
        return None

    export_dir = chain.parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_path = export_dir / f"benchmark_{timestamp}.csv"
    with open(out_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Symbols", "Runtime", "Quality", "ChainFile"])
        q_val = f"{quality:.1f}" if quality is not None else "-"
        writer.writerow([" ".join(symbols), f"{runtime:.2f}", q_val, chain.name])
    return out_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark async getonemarket and run quality check"
    )
    parser.add_argument("symbols", nargs="+", help="Symbolen om te verwerken")
    args = parser.parse_args(argv)

    setup_logging()
    runtime = asyncio.run(bench_async(args.symbols))
    latest = find_latest_chain()
    quality = None
    quality_str = "-"
    if latest:
        stats = csv_quality_check.analyze_csv(str(latest))
        total = stats.get("total", 0)
        valid = stats.get("valid", 0)
        quality = (valid / total * 100) if total else 0
        quality_str = f"{quality:.1f}% ({latest.name})"
    result_path = write_result_csv(args.symbols, runtime, quality, latest)
    print(f"async: {runtime:.2f}s")
    print(f"quality: {quality_str}")
    if result_path:
        print(f"csv: {result_path}")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
