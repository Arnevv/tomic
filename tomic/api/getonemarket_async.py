from __future__ import annotations

import argparse
import asyncio
import sys

from tomic.logutils import logger, setup_logging
from .ib_connection import connect_ib
from .getonemarket import run_async


def main(args: list[str] | None = None) -> int:
    """Asynchronous entry point for ``getonemarket``."""

    parser = argparse.ArgumentParser(
        description="Exporteer optie- en marktdata (async prototype)"
    )
    parser.add_argument("symbol", help="Ticker symbool")
    parser.add_argument(
        "--output-dir",
        help="Map voor exports (standaard wordt automatisch bepaald)",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Gebruik eenvoudige writer voor optieketen",
    )
    parsed = parser.parse_args(args)

    setup_logging()
    try:
        app = connect_ib()
        app.disconnect()
    except Exception:
        logger.error(
            "❌ IB Gateway/TWS niet bereikbaar. Controleer of de service draait."
        )
        return 1

    ok = asyncio.run(run_async(parsed.symbol, parsed.output_dir, simple=parsed.simple))
    if ok:
        logger.success("✅ Async export afgerond")
    else:
        logger.error("❌ Export mislukt")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover - manual invocation
    sys.exit(main())
