from __future__ import annotations

import sys
from pathlib import Path
from typing import List
import json

from tomic.logutils import setup_logging, logger
from tomic.config import get as cfg_get
from tomic.analysis.proposal_engine import generate_proposals
from tomic.analysis.vol_db import init_db, load_latest_stats, VolRecord


def main(argv: List[str] | None = None) -> None:
    """Generate and print strategy proposals."""
    setup_logging()
    if argv is None:
        argv = []
    positions = Path(cfg_get("POSITIONS_FILE", "positions.json"))
    export_dir = Path(cfg_get("EXPORT_DIR", "exports"))
    metrics_file = None
    if len(argv) >= 1:
        positions = Path(argv[0])
    if len(argv) >= 2:
        export_dir = Path(argv[1])
    if len(argv) >= 3:
        metrics_file = Path(argv[2])
    if not positions.exists():
        logger.error(f"Positions file not found: {positions}")
        return
    metrics = None
    if metrics_file and metrics_file.exists():
        try:
            data = json.loads(metrics_file.read_text())
            metrics = {sym: VolRecord(**vals) for sym, vals in data.items()}
        except Exception as exc:
            logger.warning(f"Kan metrics niet laden: {exc}")
    else:
        try:
            raw_positions = json.loads(positions.read_text())
            symbols = {p.get("symbol") for p in raw_positions if p.get("symbol")}
            conn = init_db(cfg_get("VOLATILITY_DB", "data/volatility.db"))
            try:
                metrics = load_latest_stats(conn, symbols)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"Volatiliteitsdata niet beschikbaar: {exc}")
            metrics = None

    proposals = generate_proposals(
        str(positions),
        str(export_dir),
        metrics=metrics,
    )
    if not proposals:
        logger.warning("Geen strategievoorstellen gevonden.")
        return
    for sym, items in proposals.items():
        logger.info(f"=== {sym} ===")
        for prop in items:
            imp = prop["impact"]
            logger.info(
                f"{prop['strategy']:<15} Δ {imp['Delta']:+.2f} θ {imp['Theta']:+.2f} "
                f"ν {imp['Vega']:+.2f} Γ {imp['Gamma']:+.2f} | Score {prop['score']} "
                f"| {prop['reason']}"
            )


if __name__ == "__main__":
    main(sys.argv[1:])
