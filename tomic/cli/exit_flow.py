"""Command line interface to orchestrate exit order execution."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

from tomic.logutils import logger, setup_logging
from tomic.services.exit_flow import (
    ExitFlowConfig,
    ExitFlowResult,
    execute_exit_flow,
    store_exit_flow_result,
)
from tomic.services.trade_management_service import StrategyExitIntent, build_exit_intents


def _intent_symbol(intent: StrategyExitIntent) -> str:
    strategy = intent.strategy or {}
    return str(strategy.get("symbol") or strategy.get("underlying") or "-")


def _should_include(intent: StrategyExitIntent, symbols: set[str] | None) -> bool:
    if not symbols:
        return True
    symbol = _intent_symbol(intent).upper()
    return symbol in symbols


def _log_summary(intent: StrategyExitIntent, result: ExitFlowResult, log_path) -> None:
    strategy = intent.strategy or {}
    symbol = strategy.get("symbol") or strategy.get("underlying") or "-"
    expiry = strategy.get("expiry") or "-"
    order_ids = list(result.order_ids)
    limit_prices = [round(lp, 4) for lp in result.limit_prices]
    logger.info(
        "Exit %s %s status=%s reason=%s order_ids=%s limits=%s log=%s",
        symbol,
        expiry,
        result.status,
        result.reason or "-",
        order_ids,
        limit_prices,
        log_path,
    )


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint for executing exit flows."""

    setup_logging()

    parser = argparse.ArgumentParser(description="Run the exit workflow for current positions")
    parser.add_argument("--positions", help="Pad naar positions.json", default=None)
    parser.add_argument("--journal", help="Pad naar journal.json", default=None)
    parser.add_argument(
        "--symbol",
        action="append",
        help="Beperk uitvoering tot deze symbolen (meervoudig)",
        default=None,
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    symbols = {s.upper() for s in args.symbol or [] if s}

    intents = build_exit_intents(
        positions_file=args.positions,
        journal_file=args.journal,
    )

    filtered = [intent for intent in intents if _should_include(intent, symbols)]
    if not filtered:
        logger.warning("Geen exit-intents gevonden voor de geselecteerde criteria.")
        return 0

    config = ExitFlowConfig.from_app_config()
    if config.fetch_only:
        logger.info("IB_FETCH_ONLY actief → orders worden niet verstuurd.")

    exit_code = 0
    for intent in filtered:
        try:
            result = execute_exit_flow(intent, config=config)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Exit-flow mislukte voor %s", _intent_symbol(intent))
            exit_code = 1
            continue
        log_path = store_exit_flow_result(intent, result, directory=config.log_directory)
        _log_summary(intent, result, log_path)
        if result.status == "failed":
            exit_code = 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    sys.exit(main(sys.argv[1:]))
