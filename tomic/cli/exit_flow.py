"""Command line interface to orchestrate exit order execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from tomic.logutils import logger, setup_logging
from tomic.services.exit_flow import (
    ExitFlowConfig,
    ExitFlowResult,
    execute_exit_flow,
    store_exit_flow_result,
)
from tomic.services.trade_management_service import (
    StrategyExitIntent,
    build_exit_alert_index,
    build_exit_intents,
    build_management_summary,
    exit_intent_keys,
)


def _intent_symbol(intent: StrategyExitIntent) -> str:
    strategy = intent.strategy or {}
    return str(strategy.get("symbol") or strategy.get("underlying") or "-")


def _intent_label(intent: StrategyExitIntent) -> str:
    strategy = intent.strategy or {}
    symbol = strategy.get("symbol") or strategy.get("underlying")
    expiry = strategy.get("expiry")
    name = strategy.get("type") or strategy.get("strategy")

    parts = [
        str(symbol).upper() if symbol else None,
        str(expiry) if expiry else None,
        str(name).upper() if name else None,
    ]
    return " ".join(part for part in parts if part)


def _format_price(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}"


def _format_order_suffix(order_ids: Iterable[int] | None) -> str:
    ids = [int(order_id) for order_id in (order_ids or [])]
    if not ids:
        return ""
    if len(ids) == 1:
        return f" (order #{ids[0]})"
    return " (orders #" + ", ".join(map(str, ids)) + ")"


def _describe_ladder(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    attempts = [attempt for attempt in result.attempts if attempt.stage == "primary" or attempt.stage.startswith("ladder:")]
    if not attempts:
        return []

    label = _intent_label(intent)
    prices = [attempt.limit_price for attempt in attempts if attempt.limit_price is not None]
    price_sequence: str | None = None
    if prices:
        formatted = [_format_price(price) or "-" for price in prices]
        preview = formatted[:3]
        price_sequence = " → ".join(preview)
        if len(formatted) > 3:
            price_sequence += " → …"

    filled_attempt = next((attempt for attempt in attempts if attempt.order_ids), None)
    if filled_attempt is not None:
        status = "FILLED"
        final_price = _format_price(filled_attempt.limit_price)
        if final_price:
            status += f" @ {final_price}"
        status += _format_order_suffix(filled_attempt.order_ids)
    else:
        status = result.reason or "failed"

    steps_count = len(prices) if prices else len(attempts)
    sequence_part = f" @ {price_sequence}" if price_sequence else ""
    return [f"{label} | Ladder {steps_count} steps{sequence_part} {status}"]


def _fallback_reason_label(reason: str | None) -> str:
    mapping = {
        "gate_failure": "Gate=FAIL",
        "main_bag_failure": "Primary=FAIL",
        "repricer_timeout": "Repricer timeout",
        "cancel_on_no_fill": "Cancelled",
        "manual_trigger": "Fallback",
    }
    if not reason:
        return "Fallback"
    return mapping.get(reason, reason.replace("_", " "))


def _describe_fallback(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    attempts = [attempt for attempt in result.attempts if attempt.stage.startswith("fallback:")]
    if not attempts:
        return []

    label = _intent_label(intent)
    reason = None
    if result.reason and result.reason.startswith("fallback:"):
        reason = result.reason.split(":", 1)[1]
    lines = [
        f"{label} | {_fallback_reason_label(reason)} → Fallback: {len(attempts)} verticals"
    ]

    for attempt in attempts:
        wing = attempt.stage.split(":", 1)[1] if ":" in attempt.stage else attempt.stage
        detail: str
        if attempt.order_ids:
            price = _format_price(attempt.limit_price)
            detail = "FILLED"
            if price:
                detail += f" @ {price}"
            detail += _format_order_suffix(attempt.order_ids)
        elif attempt.status == "skipped":
            detail = f"gate=FAIL ({attempt.reason or 'skipped'})"
        elif attempt.reason:
            detail = f"gate=FAIL ({attempt.reason})"
        else:
            detail = attempt.status
        lines.append(f"{label} | Fallback({wing}) {detail}")

    return lines


def _describe_fetch_only(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    label = _intent_label(intent)
    limit = None
    if result.limit_prices:
        limit = _format_price(result.limit_prices[-1])
    limit_part = f" @ {limit}" if limit else ""
    return [f"{label} | Fetch-only{limit_part}"]


def _describe_generic(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    label = _intent_label(intent)
    price = None
    if result.limit_prices:
        price = _format_price(result.limit_prices[-1])
    order_suffix = _format_order_suffix(result.order_ids)
    reason = result.reason or result.status
    price_part = f" @ {price}" if price else ""
    return [f"{label} | {result.status}{price_part}{order_suffix} ({reason})"]


def _progress_lines(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    if result.status == "fetch_only":
        return _describe_fetch_only(intent, result)

    lines: list[str] = []
    lines.extend(_describe_ladder(intent, result))
    lines.extend(_describe_fallback(intent, result))

    if lines:
        return lines
    return _describe_generic(intent, result)


def _final_summary_line(intent: StrategyExitIntent, result: ExitFlowResult) -> str:
    label = _intent_label(intent)
    if result.status == "success":
        emoji = "✅"
        price = None
        if result.order_ids:
            attempt = next(
                (item for item in reversed(result.attempts) if item.order_ids),
                None,
            )
            if attempt and attempt.limit_price is not None:
                price = _format_price(attempt.limit_price)
        if not price and result.limit_prices:
            price = _format_price(result.limit_prices[-1])
        order_suffix = _format_order_suffix(result.order_ids)
        price_part = f" @ {price}" if price else ""
        return f"{emoji} {label}{price_part}{order_suffix}"

    if result.status == "fetch_only":
        return f"⏭️ {label} | fetch-only"

    reason = result.reason or "failed"
    return f"⚠️ {label} | failed: {reason}"


def _log_progress(intent: StrategyExitIntent, result: ExitFlowResult) -> None:
    for line in _progress_lines(intent, result):
        logger.info(line)


def _log_final_summary(entries: list[tuple[StrategyExitIntent, ExitFlowResult, Path]]) -> None:
    if not entries:
        return

    success = sum(1 for _, result, _ in entries if result.status == "success")
    failed = sum(1 for _, result, _ in entries if result.status == "failed")
    skipped = sum(1 for _, result, _ in entries if result.status == "fetch_only")

    logger.info("=== RESULT ===")
    logger.info("✅ %d closed | ⚠️ %d failed | ⏭️ %d skipped", success, failed, skipped)

    for intent, result, _ in entries:
        logger.info(_final_summary_line(intent, result))

    log_dirs = sorted({str(path.parent) for _, _, path in entries})
    if log_dirs:
        formatted = [directory if directory.endswith("/") else f"{directory}/" for directory in log_dirs]
        logger.info("Logs: %s", ", ".join(formatted))


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

    summaries = build_management_summary(
        positions_file=args.positions,
        journal_file=args.journal,
    )
    alert_index = build_exit_alert_index(summaries)

    intents = build_exit_intents(
        positions_file=args.positions,
        journal_file=args.journal,
        freshen_attempts=3,
        freshen_wait_s=0.3,
    )

    filtered: list[StrategyExitIntent] = []
    skipped_without_alert: list[str] = []
    for intent in intents:
        symbol_label = _intent_symbol(intent)
        symbol_key = symbol_label.upper()
        if symbols and symbol_key not in symbols:
            continue

        keys = exit_intent_keys(intent)
        has_alert = bool(alert_index and (keys & alert_index))
        if not has_alert:
            skipped_without_alert.append(symbol_label)
            continue

        filtered.append(intent)

    if not filtered:
        logger.warning("Geen exit-intents gevonden voor de geselecteerde criteria.")
        return 0

    if skipped_without_alert:
        logger.info(
            "Sla %d intent(s) over zonder actieve exit-alert: %s",
            len(skipped_without_alert),
            ", ".join(filter(None, skipped_without_alert)),
        )

    config = ExitFlowConfig.from_app_config()
    if config.fetch_only:
        logger.info("IB_FETCH_ONLY actief → orders worden niet verstuurd.")

    exit_code = 0
    collected: list[tuple[StrategyExitIntent, ExitFlowResult, Path]] = []
    for intent in filtered:
        try:
            result = execute_exit_flow(intent, config=config)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Exit-flow mislukte voor %s", _intent_symbol(intent))
            exit_code = 1
            continue
        log_path = store_exit_flow_result(intent, result, directory=config.log_directory)
        _log_progress(intent, result)
        collected.append((intent, result, log_path))
        if result.status == "failed":
            exit_code = 1
    _log_final_summary(collected)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    sys.exit(main(sys.argv[1:]))
