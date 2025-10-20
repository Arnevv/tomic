from __future__ import annotations

import sys
from typing import List

from tomic.logutils import setup_logging, logger
from tomic.services.proposal_generation import (
    ProposalGenerationError,
    generate_proposal_overview,
)


def main(argv: List[str] | None = None) -> None:
    """Generate and print strategy proposals."""
    setup_logging()
    if argv is None:
        argv = []
    positions_arg = argv[0] if len(argv) >= 1 else None
    export_arg = argv[1] if len(argv) >= 2 else None
    metrics_arg = argv[2] if len(argv) >= 3 else None

    try:
        result = generate_proposal_overview(
            positions_path=positions_arg,
            export_dir=export_arg,
            metrics_path=metrics_arg,
        )
    except ProposalGenerationError as exc:
        logger.error(str(exc))
        return

    for warning in result.warnings:
        logger.warning(warning)

    if not result.proposals:
        logger.warning("Geen strategievoorstellen gevonden.")
        return

    for sym, items in result.proposals.items():
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
