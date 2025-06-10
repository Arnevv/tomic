from __future__ import annotations

import argparse
import asyncio
import time

from tomic.logutils import setup_logging
from tomic.api.getonemarket import run, run_async


def bench_sync(symbols: list[str]) -> float:
    start = time.perf_counter()
    for sym in symbols:
        run(sym, simple=True)
    return time.perf_counter() - start


async def bench_async(symbols: list[str]) -> float:
    start = time.perf_counter()
    await asyncio.gather(*(run_async(sym, simple=True) for sym in symbols))
    return time.perf_counter() - start


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Vergelijk runtijd van sync vs async getonemarket"
    )
    parser.add_argument("symbols", nargs="+", help="Symbolen om te verwerken")
    args = parser.parse_args(argv)

    setup_logging()
    s = bench_sync(args.symbols)
    a = asyncio.run(bench_async(args.symbols))
    print(f"sync: {s:.2f}s")
    print(f"async: {a:.2f}s")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
