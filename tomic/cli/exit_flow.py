"""Command line interface to orchestrate exit order execution."""

from __future__ import annotations

import argparse
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from tomic.journal.utils import load_json
from tomic.journal.service import update_trade
from tomic.logutils import logger, setup_logging


from tomic.services.exit_flow import (
    ExitFlowConfig,
    ExitFlowResult,
    execute_exit_flow,
    intent_strategy_name,
    intent_strategy_payload,
    intent_symbol,
    resolve_exit_intent_freshen_config,
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
    """Return a normalized symbol label consistent met servicebeslissingen."""

    keys = exit_intent_keys(intent)
    if keys:
        symbol, _ = sorted(keys, key=lambda item: (item[0] or "", item[1] or ""))[0]
        if symbol:
            text = str(symbol).strip()
            if text:
                return text.upper()

    symbol = intent_symbol(intent)
    label = str(symbol or "-").strip()
    return label.upper() if label else "-"


def _get_trade_id(intent: StrategyExitIntent) -> str | None:
    """Extract TradeID from the intent's strategy mapping."""
    strategy = intent.strategy
    if isinstance(strategy, dict):
        trade_id = strategy.get("trade_id") or strategy.get("TradeID")
        if trade_id:
            return str(trade_id)
    return None


def _update_journal_on_exit(
    intent: StrategyExitIntent,
    result: ExitFlowResult,
    *,
    journal_path: str | None = None,
) -> bool:
    """Update the journal entry after a successful exit.

    Marks the trade as closed with exit date, price, and order IDs.

    Returns:
        True if journal was updated, False otherwise.
    """
    trade_id = _get_trade_id(intent)
    if not trade_id:
        logger.warning(
            "Kan journal niet updaten: geen TradeID gevonden in intent voor %s",
            _intent_symbol(intent),
        )
        return False

    # Get exit price from the successful attempt
    exit_price = None
    if result.order_ids and result.attempts:
        # Find the attempt that resulted in a fill
        for attempt in reversed(result.attempts):
            if attempt.order_ids and attempt.limit_price is not None:
                exit_price = attempt.limit_price
                break

    if exit_price is None and result.limit_prices:
        exit_price = result.limit_prices[-1]

    updates: dict[str, Any] = {
        "Status": "Gesloten",
        "DatumUit": datetime.now().strftime("%Y-%m-%d"),
    }

    if exit_price is not None:
        updates["ExitPrice"] = exit_price

    if result.order_ids:
        updates["ExitOrderIDs"] = list(result.order_ids)

    try:
        success = update_trade(trade_id, updates, journal_path)
        if success:
            logger.info(
                "📔 Journal bijgewerkt: %s → Status=Gesloten, ExitPrice=%.2f",
                trade_id,
                exit_price or 0,
            )
        return success
    except Exception as exc:
        logger.error("Kon journal niet updaten voor %s: %s", trade_id, exc)
        return False


def _intent_label(intent: StrategyExitIntent) -> str:
    strategy = intent_strategy_payload(intent)
    symbol = strategy.get("symbol") or strategy.get("underlying")
    expiry = strategy.get("expiry")
    name = intent_strategy_name(intent)

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
    lines = list(dict.fromkeys(_progress_lines(intent, result)))
    if not lines:
        return
    for line in lines:
        logger.info(line)


def _log_final_summary(entries: list[tuple[StrategyExitIntent, ExitFlowResult, Path]]) -> None:
    if not entries:
        return

    success = failed = skipped = 0
    summary_lines: dict[str, None] = {}
    log_dirs: set[str] = set()

    for intent, result, path in entries:
        status = result.status
        if status == "success":
            success += 1
        elif status == "failed":
            failed += 1
        elif status == "fetch_only":
            skipped += 1
        summary_lines.setdefault(_final_summary_line(intent, result), None)
        log_dirs.add(str(path.parent))

    logger.info("=== RESULT ===")
    logger.info("✅ %d closed | ⚠️ %d failed | ⏭️ %d skipped", success, failed, skipped)

    for line in summary_lines.keys():
        logger.info(line)

    if log_dirs:
        formatted = [
            directory if directory.endswith("/") else f"{directory}/"
            for directory in sorted(log_dirs)
        ]
        logger.info("Logs: %s", ", ".join(formatted))


def _cached_loader(loader: Callable[[str], Any]) -> Callable[[str], Any]:
    cache: dict[str, Any] = {}

    def _load(path: str) -> Any:
        if path not in cache:
            cache[path] = loader(path)
        return deepcopy(cache[path])

    return _load


def _format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint for executing exit flows."""

    setup_logging()

    # ===== TIMING: Start totaal =====
    t_total_start = time.perf_counter()
    logger.info("=" * 60)
    logger.info("EXIT-FLOW GESTART - Diagnostische logging actief")
    logger.info("=" * 60)

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

    cached_loader = _cached_loader(load_json)

    # ===== TIMING: build_management_summary =====
    t_summary_start = time.perf_counter()
    logger.info("[FASE 1/5] Laden management summaries...")
    summaries = build_management_summary(
        positions_file=args.positions,
        journal_file=args.journal,
        loader=cached_loader,
    )
    alert_index = build_exit_alert_index(summaries)
    t_summary_elapsed = time.perf_counter() - t_summary_start
    logger.info(
        "[FASE 1/5] ✓ Summaries geladen: %d summaries, %d alerts (%s)",
        len(summaries),
        len(alert_index),
        _format_duration(t_summary_elapsed),
    )

    # ===== TIMING: resolve_exit_intent_freshen_config =====
    freshen_attempts, freshen_wait_s = resolve_exit_intent_freshen_config()
    logger.info(
        "[CONFIG] freshen_attempts=%d, freshen_wait_s=%.2f",
        freshen_attempts,
        freshen_wait_s,
    )

    # ===== TIMING: build_exit_intents =====
    t_intents_start = time.perf_counter()
    logger.info("[FASE 2/5] Bouwen exit intents (incl. quote refresh)...")
    intents = build_exit_intents(
        positions_file=args.positions,
        journal_file=args.journal,
        loader=cached_loader,
        freshen_attempts=freshen_attempts,
        freshen_wait_s=freshen_wait_s,
    )
    t_intents_elapsed = time.perf_counter() - t_intents_start
    logger.info(
        "[FASE 2/5] ✓ Exit intents gebouwd: %d intents (%s)",
        len(intents),
        _format_duration(t_intents_elapsed),
    )

    # ===== TIMING: Filtering =====
    t_filter_start = time.perf_counter()
    logger.info("[FASE 3/5] Filteren intents...")
    filtered: list[StrategyExitIntent] = []
    skipped_symbols: list[str] = []
    has_symbol_filter = bool(symbols)
    has_alerts = bool(alert_index)

    for intent in intents:
        symbol_label = _intent_symbol(intent)
        if has_symbol_filter and symbol_label.upper() not in symbols:
            continue

        if has_alerts and exit_intent_keys(intent) & alert_index:
            filtered.append(intent)
            continue

        skipped_symbols.append(symbol_label)

    t_filter_elapsed = time.perf_counter() - t_filter_start
    logger.info(
        "[FASE 3/5] ✓ Gefilterd: %d te verwerken, %d overgeslagen (%s)",
        len(filtered),
        len(skipped_symbols),
        _format_duration(t_filter_elapsed),
    )

    if not filtered:
        t_total_elapsed = time.perf_counter() - t_total_start
        logger.warning("Geen exit-intents gevonden voor de geselecteerde criteria.")
        logger.info("[TOTAAL] Exit-flow beëindigd in %s", _format_duration(t_total_elapsed))
        return 0

    if skipped_symbols:
        skipped_summary = sorted({symbol for symbol in skipped_symbols if symbol})
        logger.info(
            "Sla %d intent(s) over zonder actieve exit-alert: %s",
            len(skipped_symbols),
            ", ".join(skipped_summary),
        )

    # ===== TIMING: Config laden =====
    t_config_start = time.perf_counter()
    config = ExitFlowConfig.from_app_config()
    t_config_elapsed = time.perf_counter() - t_config_start
    logger.info(
        "[CONFIG] host=%s, port=%d, client_id=%d, fetch_only=%s (%s)",
        config.host,
        config.port,
        config.client_id,
        config.fetch_only,
        _format_duration(t_config_elapsed),
    )
    if config.fetch_only:
        logger.info("IB_FETCH_ONLY actief → orders worden niet verstuurd.")

    # ===== TIMING: Execute exit flows =====
    logger.info("[FASE 4/5] Uitvoeren exit flows voor %d intents...", len(filtered))
    exit_code = 0
    collected: list[tuple[StrategyExitIntent, ExitFlowResult, Path]] = []
    intent_timings: list[tuple[str, float]] = []

    for idx, intent in enumerate(filtered, start=1):
        symbol_label = _intent_symbol(intent)
        intent_label = _intent_label(intent)

        logger.info("-" * 50)
        logger.info(
            "[INTENT %d/%d] Start: %s",
            idx,
            len(filtered),
            intent_label,
        )
        t_intent_start = time.perf_counter()

        try:
            result = execute_exit_flow(intent, config=config)
        except Exception:  # pragma: no cover - defensive logging
            t_intent_elapsed = time.perf_counter() - t_intent_start
            logger.exception(
                "[INTENT %d/%d] ✗ EXCEPTION na %s voor %s",
                idx,
                len(filtered),
                _format_duration(t_intent_elapsed),
                symbol_label,
            )
            intent_timings.append((symbol_label, t_intent_elapsed))
            exit_code = 1
            continue

        t_intent_elapsed = time.perf_counter() - t_intent_start
        intent_timings.append((symbol_label, t_intent_elapsed))

        logger.info(
            "[INTENT %d/%d] ✓ Klaar: %s → %s (%d attempts) in %s",
            idx,
            len(filtered),
            symbol_label,
            result.status,
            len(result.attempts),
            _format_duration(t_intent_elapsed),
        )

        log_path = store_exit_flow_result(intent, result, directory=config.log_directory)
        _log_progress(intent, result)
        collected.append((intent, result, log_path))

        # Update journal for successful exits
        if result.status == "success":
            _update_journal_on_exit(intent, result, journal_path=args.journal)

        if result.status == "failed":
            exit_code = 1

    # ===== TIMING: Final summary =====
    logger.info("-" * 50)
    logger.info("[FASE 5/5] Genereren samenvatting...")
    _log_final_summary(collected)

    # ===== TIMING: Totaal overzicht =====
    t_total_elapsed = time.perf_counter() - t_total_start
    logger.info("=" * 60)
    logger.info("TIMING OVERZICHT")
    logger.info("=" * 60)
    logger.info("  Summaries laden:    %s", _format_duration(t_summary_elapsed))
    logger.info("  Intents bouwen:     %s", _format_duration(t_intents_elapsed))
    logger.info("  Filteren:           %s", _format_duration(t_filter_elapsed))

    if intent_timings:
        logger.info("  Per intent:")
        for symbol, duration in intent_timings:
            logger.info("    - %-15s %s", symbol, _format_duration(duration))
        total_intent_time = sum(d for _, d in intent_timings)
        logger.info("  Intent totaal:      %s", _format_duration(total_intent_time))

    logger.info("-" * 60)
    logger.info("  TOTALE RUNTIME:     %s", _format_duration(t_total_elapsed))
    logger.info("=" * 60)

    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    sys.exit(main(sys.argv[1:]))
