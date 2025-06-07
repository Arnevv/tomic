from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from tomic.logging import setup_logging, logger
from tomic.config import get as cfg_get
from tomic.analysis.proposal_engine import generate_proposals


def main(argv: List[str] | None = None) -> None:
    """Generate and print strategy proposals."""
    setup_logging()
    if argv is None:
        argv = []
    positions = Path(cfg_get("POSITIONS_FILE", "positions.json"))
    export_dir = Path(cfg_get("EXPORT_DIR", "exports"))
    if len(argv) >= 1:
        positions = Path(argv[0])
    if len(argv) >= 2:
        export_dir = Path(argv[1])
    if not positions.exists():
        logger.error(f"Positions file not found: {positions}")
        return
    proposals = generate_proposals(str(positions), str(export_dir))
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
