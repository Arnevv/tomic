"""Interactive command line interface for TOMIC utilities."""

import argparse
import subprocess
import sys
from datetime import datetime, date
import hashlib
import json
import uuid
from pathlib import Path
import os
import csv
from collections import defaultdict
import math
import inspect
from typing import Any, Mapping, Sequence
from tomic.helpers.dateutils import parse_date

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

    def tabulate(
        rows: list[list[str]],
        headers: list[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        if headers:
            table_rows = [headers] + rows
        else:
            table_rows = rows
        col_w = [max(len(str(c)) for c in col) for col in zip(*table_rows)]

        def fmt(row: list[str]) -> str:
            return (
                "| "
                + " | ".join(str(c).ljust(col_w[i]) for i, c in enumerate(row))
                + " |"
            )

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append(
                "|-" + "-|-".join("-" * col_w[i] for i in range(len(col_w))) + "-|"
            )
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)


if __package__ is None:
    # Allow running this file directly without ``-m`` by adjusting ``sys.path``
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from tomic.cli.common import Menu, prompt, prompt_yes_no

from tomic.api.ib_connection import connect_ib
from tomic.api.earnings_importer import (
    load_json as load_earnings_json,
    parse_earnings_csv,
    save_json as save_earnings_json,
    update_next_earnings,
)

from tomic import config as cfg
from tomic.config import save_symbols
from tomic.logutils import capture_combo_evaluations, normalize_reason, setup_logging, logger
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.journal.utils import load_json, save_json
from tomic.utils import today
from tomic.analysis.volatility_fetcher import fetch_volatility_metrics
from tomic.analysis.market_overview import build_market_overview
from tomic.api.market_export import load_exported_chain
from tomic.cli.app_services import ControlPanelServices, create_controlpanel_services
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.export import (
    RunMetadata,
    build_export_path,
    export_proposals_csv,
    export_proposals_json,
    render_journal_entries,
)
from tomic.helpers.price_utils import _load_latest_close
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.polygon_client import PolygonClient
from tomic.strike_selector import StrikeSelector, filter_by_expiry
from tomic.loader import load_strike_config
from tomic.utils import get_option_mid_price, latest_atr, load_price_history, normalize_leg
from tomic.metrics import calculate_edge, calculate_ev, calculate_pos, calculate_rom
from tomic.services.chain_processing import (
    ChainEvaluationConfig,
    ChainPreparationConfig,
    ChainPreparationError,
    evaluate_chain,
    load_and_prepare_chain,
    resolve_spot_price as resolve_chain_spot_price,
)
import pandas as pd
from tomic.formatting import PROPOSALS_SPEC, proposals_table, sort_records
from tomic.services.strategy_pipeline import StrategyProposal, RejectionSummary
from tomic.services.ib_marketdata import fetch_quote_snapshot, SnapshotResult
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tomic.scripts.backfill_hv import run_backfill_hv
from tomic.cli.iv_backfill_flow import run_iv_backfill_flow
from tomic.services.portfolio_service import CandidateRankingError
from tomic.services.market_scan_service import (
    MarketScanError,
    MarketScanRequest,
    MarketScanService,
    select_chain_source,
)
from tomic.strategy.reasons import ReasonCategory, ReasonDetail
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.core import config as runtime_config
from tomic.criteria import load_criteria
from tomic.reporting import (
    EvaluationSummary,
    ReasonAggregator,
    build_rejection_table,
    format_dtes,
    format_money,
    format_reject_reasons,
    reason_label,
    summarize_evaluations,
    to_float,
)
from tomic.reporting.rejections import (
    ExpiryBreakdown,
    _format_leg_summary as _reporting_format_leg_summary,
)
from tomic.services.pipeline_refresh import (
    ORIGINAL_INDEX_KEY,
    RefreshContext,
    RefreshParams,
    RefreshSource,
    Proposal as RefreshProposal,
    refresh_pipeline,
    build_proposal_from_entry,
)
from tomic.services.proposal_details import (
    ProposalCore,
    ProposalVM,
    build_proposal_core,
    build_proposal_viewmodel,
)
from tomic.formatting.table_builders import (
    proposal_earnings_table,
    proposal_legs_table,
    proposal_summary_table,
)

setup_logging(stdout=True)


POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
STRATEGY_DASHBOARD_MODULE = "tomic.cli.strategy_dashboard"

def _build_run_metadata(
    session: ControlPanelSession,
    *,
    symbol: str | None = None,
    strategy: str | None = None,
) -> RunMetadata:
    """Return consistent metadata for the current CLI session."""

    if not session.run_id:
        session.run_id = uuid.uuid4().hex[:12]
    run_id = str(session.run_id)

    config_hash = session.config_hash
    if not isinstance(config_hash, str) or not config_hash:
        try:
            cfg_model = runtime_config.load()
            cfg_dump = cfg_model.model_dump(by_alias=True)
            config_hash = hashlib.sha256(
                json.dumps(cfg_dump, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:12]
        except Exception:
            config_hash = "unknown"
        session.config_hash = config_hash

    schema_version = cfg.get("EXPORT_SCHEMA_VERSION")
    schema_version_str = str(schema_version) if schema_version else None

    return RunMetadata(
        timestamp=datetime.now(),
        run_id=run_id,
        config_hash=config_hash,
        symbol=symbol,
        strategy=strategy,
        schema_version=schema_version_str,
    )


def _format_leg_summary(legs: Sequence[Mapping[str, Any]] | None) -> str:
    """Expose leg summary formatting used in tests and CLI flows."""

    return _reporting_format_leg_summary(legs)


def _format_reject_reasons(summary: EvaluationSummary) -> str:
    """Return a formatted summary of rejection reasons."""

    return format_reject_reasons(summary)


def _strike_selector_factory(*args, **kwargs):
    try:
        selector = StrikeSelector(*args, **kwargs)
    except TypeError:
        # Compatibility for tests that monkeypatch ``StrikeSelector`` with a simple
        # callable that only accepts the configuration positional argument.
        if kwargs:
            selector = StrikeSelector(kwargs.get("config"))
        else:
            raise
    return _wrap_selector(selector)


def _wrap_selector(selector):
    select = getattr(selector, "select", None)
    if not callable(select):
        return selector
    try:
        params = inspect.signature(select).parameters
    except (TypeError, ValueError):
        params = {}
    if "dte_range" not in params:

        def _adapted_select(data, *, dte_range=None, debug_csv=None, return_info=False):
            return select(data, debug_csv=debug_csv, return_info=return_info)

        selector.select = _adapted_select  # type: ignore[attr-defined]
    return selector




def _print_evaluation_overview(symbol: str, spot: float | None, summary: EvaluationSummary | None) -> None:
    if summary is None or summary.total <= 0:
        return
    sym = symbol.upper() if symbol else "—"
    if isinstance(spot, (int, float)) and spot > 0:
        header = f"Evaluatieoverzicht: {sym} @ {spot:.2f}"
    else:
        header = f"Evaluatieoverzicht: {sym}"
    print(header)
    print(f"Totaal combinaties: {summary.total}")
    if summary.expiries:
        print("Expiry breakdown:")
        for breakdown in summary.sorted_expiries():
            print(f"• {breakdown.label}: {breakdown.format_counts()}")
    print(f"Top reason for reject: {format_reject_reasons(summary)}")


def _generate_with_capture(
    session: ControlPanelSession, *args: Any, **kwargs: Any
):
    session.clear_combo_results()
    with capture_combo_evaluations() as captured:
        try:
            result = generate_strategy_candidates(*args, **kwargs)
        finally:
            summary = summarize_evaluations(captured)
            session.set_combo_results(captured, summary)
    return result


def _create_services(session: ControlPanelSession) -> ControlPanelServices:
    return create_controlpanel_services(
        strike_selector_factory=_strike_selector_factory,
        strategy_generator=lambda *args, **kwargs: _generate_with_capture(
            session, *args, **kwargs
        ),
    )

def _format_leg_position(raw: Any) -> str:
    num = to_float(raw)
    if num is None:
        return "?"
    return "S" if num < 0 else "L"



def _show_rejection_detail(session: ControlPanelSession, entry: Mapping[str, Any]) -> None:
    strategy = entry.get("strategy") or "—"
    status = entry.get("status") or "—"
    anchor = entry.get("description") or "—"
    reason_value = entry.get("reason")
    raw_reason = entry.get("raw_reason")
    detail = normalize_reason(reason_value or raw_reason)
    reason_label_text = detail.message or ReasonAggregator.label_for(detail.category)
    original = None
    if isinstance(reason_value, ReasonDetail):
        original = reason_value.data.get("original_message")
    if original is None:
        original = detail.data.get("original_message")
    note = raw_reason or original or reason_label_text

    print(f"Strategie: {strategy}")
    print(f"Status: {status}")
    print(f"Anchor: {anchor}")
    print(f"Reden: {reason_label_text}")
    if note and note != reason_label_text:
        print(f"Detail: {note}")

    metrics = entry.get("metrics") or {}
    if metrics:
        metric_rows = []
        for key in sorted(metrics):
            metric_rows.append([key, metrics[key]])
        print("Metrics:")
        print(tabulate(metric_rows, headers=["Metric", "Waarde"], tablefmt="github"))

    meta = entry.get("meta")
    if isinstance(meta, Mapping) and meta:
        meta_rows = [[key, value] for key, value in meta.items()]
        print("Flags:")
        print(tabulate(meta_rows, headers=["Sleutel", "Waarde"], tablefmt="github"))

    legs = entry.get("legs")
    legs_list = (
        list(legs)
        if isinstance(legs, Sequence) and not isinstance(legs, (str, bytes))
        else []
    )
    if legs_list:
        dte_info = format_dtes(legs_list)
        if dte_info:
            print(f"DTEs: {dte_info}")
        leg_rows: list[list[str]] = []
        headers = [
            "#",
            "Expiry",
            "Type",
            "Strike",
            "Pos",
            "Qty",
            "Volume",
            "OI",
            "Bid",
            "Ask",
            "Mid",
        ]
        for idx, leg in enumerate(legs_list, start=1):
            strike = leg.get("strike")
            try:
                strike_str = f"{float(strike):g}"
            except (TypeError, ValueError):
                strike_str = str(strike or "—")
            pos_label = _format_leg_position(leg.get("position"))
            qty = leg.get("quantity") or leg.get("qty") or ""
            volume = leg.get("volume") or leg.get("totalVolume") or ""
            oi = leg.get("open_interest") or leg.get("openInterest") or ""
            bid = leg.get("bid")
            ask = leg.get("ask")
            mid = leg.get("mid")
            leg_rows.append(
                [
                    str(idx),
                    str(leg.get("expiry") or "—"),
                    str(leg.get("type") or "—"),
                    strike_str,
                    pos_label,
                    str(qty or ""),
                    str(volume or ""),
                    str(oi or ""),
                    format_money(bid) if bid not in {None, ""} else "",
                    format_money(ask) if ask not in {None, ""} else "",
                    format_money(mid) if mid not in {None, ""} else "",
                ]
            )
        print("Legs:")
        print(tabulate(leg_rows, headers=headers, tablefmt="github"))

    proposal = build_proposal_from_entry(entry)
    if not proposal:
        return

    meta = entry.get("meta") if isinstance(entry, Mapping) else None
    symbol_hint: str | None = None
    if isinstance(meta, Mapping):
        raw_symbol = meta.get("symbol")
        if raw_symbol:
            symbol_hint = str(raw_symbol)

    print("\nActies:")
    print("1. Haal orderinformatie van IB op")
    while True:
        selection = prompt("Kies actie (0 om terug): ")
        if selection in {"", "0"}:
            break
        if selection == "1":
            _display_rejection_proposal(session, proposal, symbol_hint)
        else:
            print("❌ Ongeldige keuze")


def _entry_symbol(entry: Mapping[str, Any]) -> str | None:
    symbol = entry.get("symbol") if isinstance(entry, Mapping) else None
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip().upper()

    meta = entry.get("meta") if isinstance(entry, Mapping) else None
    if isinstance(meta, Mapping):
        raw_symbol = meta.get("symbol") or meta.get("underlying")
        if isinstance(raw_symbol, str) and raw_symbol.strip():
            return raw_symbol.strip().upper()
    return None


def _refresh_reject_entries(
    session: ControlPanelSession, entries: Sequence[Mapping[str, Any]]
) -> None:
    prepared_entries: list[dict[str, Any]] = []
    proposal_cache: dict[int, StrategyProposal | None] = {}
    original_map: dict[int, Mapping[str, Any]] = {}
    original_proposals: dict[int, StrategyProposal] = {}

    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        prepared = dict(entry)
        prepared[ORIGINAL_INDEX_KEY] = idx
        proposal = build_proposal_from_entry(prepared)
        proposal_cache[id(prepared)] = proposal
        if not proposal:
            continue
        prepared_entries.append(prepared)
        original_map[idx] = entry
        original_proposals[idx] = proposal

    if not prepared_entries:
        print("⚠️ Geen geschikte voorstellen om te verversen.")
        return

    criteria_cfg = load_criteria()
    spot_price = to_float(session.spot_price)
    try:
        timeout = float(cfg.get("MARKET_DATA_TIMEOUT", 15))
    except Exception:
        timeout = 15.0
    try:
        max_attempts = int(cfg.get("PIPELINE_REFRESH_ATTEMPTS", 1) or 1)
    except Exception:
        max_attempts = 1
    if max_attempts < 1:
        max_attempts = 1
    try:
        retry_delay = float(cfg.get("PIPELINE_REFRESH_RETRY_DELAY", 0.0) or 0.0)
    except Exception:
        retry_delay = 0.0
    parallel = bool(cfg.get("PIPELINE_REFRESH_PARALLEL", False))

    def _cached_builder(entry: Mapping[str, Any]) -> StrategyProposal | None:
        cached = proposal_cache.get(id(entry))
        if cached is None:
            cached = build_proposal_from_entry(entry)
            proposal_cache[id(entry)] = cached
        return cached

    params = RefreshParams(
        entries=prepared_entries,
        criteria=criteria_cfg,
        spot_price=spot_price,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_delay=retry_delay if retry_delay > 0 else 0.0,
        parallel=parallel,
        proposal_builder=_cached_builder,
    )

    run_id = session.run_id
    trace_id = str(run_id) if isinstance(run_id, str) else None
    context = RefreshContext(trace_id=trace_id)

    total = len(prepared_entries)
    print(f"📡 Ververs orderinformatie via IB voor {total} voorstel(len)...")
    result = refresh_pipeline(context, params=params)

    refreshed_count = result.stats.accepted + result.stats.rejected
    accepted_count = len(result.accepted)
    failures = sum(1 for item in result.rejections if item.error is not None)

    fallback_symbol = str(session.symbol or "—")

    for item in result.accepted:
        target = original_map.get(item.source.index)
        if target is None:
            continue
        proposal = item.proposal
        symbol_label = item.source.symbol or _entry_symbol(target) or fallback_symbol
        target["refreshed_proposal"] = proposal
        target["refreshed_reasons"] = item.reasons
        target["refreshed_missing_quotes"] = item.missing_quotes
        target["refreshed_accepted"] = True
        target["refreshed_symbol"] = symbol_label
        print(f"✅ {symbol_label} – {proposal.strategy}: voorstel voldoet na refresh.")

    for item in result.rejections:
        target = original_map.get(item.source.index)
        if target is None:
            continue
        proposal = item.proposal or original_proposals.get(item.source.index)
        symbol_label = item.source.symbol or _entry_symbol(target) or fallback_symbol
        target["refreshed_accepted"] = False
        if proposal:
            target["refreshed_proposal"] = proposal
        target["refreshed_reasons"] = item.reasons
        target["refreshed_missing_quotes"] = item.missing_quotes
        target["refreshed_symbol"] = symbol_label
        strategy_label = (
            proposal.strategy
            if isinstance(proposal, StrategyProposal)
            else str(target.get("strategy") or "?")
        )
        if item.error is not None:
            logger.error(
                "Refresh mislukt voor %s (%s): %s",
                strategy_label,
                symbol_label,
                item.error,
            )
            print(f"❌ {symbol_label} – {strategy_label}: {item.error}")
        else:
            reason_labels = ", ".join(reason_label(reason) for reason in item.reasons)
            if not reason_labels:
                reason_labels = "Onbekende reden"
            print(
                "⚠️ "
                + f"{symbol_label} – {strategy_label}: afgewezen ({reason_labels})."
            )

    summary_parts = [f"{refreshed_count}/{total} ververst"]
    summary_parts.append(f"geaccepteerd: {accepted_count}")
    if failures:
        summary_parts.append(f"fouten: {failures}")
    print("Samenvatting: " + ", ".join(summary_parts))

    accepted_entries: list[Mapping[str, Any]] = [
        entry
        for entry in entries
        if entry.get("refreshed_accepted") and isinstance(entry.get("refreshed_proposal"), StrategyProposal)
    ]
    if not accepted_entries:
        return

    vm_pairs: list[tuple[ProposalVM, Mapping[str, Any]]] = []
    for idx, entry in enumerate(accepted_entries):
        refreshed: StrategyProposal = entry["refreshed_proposal"]  # type: ignore[assignment]
        symbol_label = (
            (entry.get("refreshed_symbol") or _entry_symbol(entry))
            if isinstance(entry, Mapping)
            else None
        )
        source = RefreshSource(index=idx, entry=entry, symbol=symbol_label)
        candidate = RefreshProposal(
            proposal=refreshed,
            source=source,
            reasons=list(entry.get("refreshed_reasons") or []),
            missing_quotes=list(entry.get("refreshed_missing_quotes") or []),
            core=entry.get("refreshed_core") if isinstance(entry.get("refreshed_core"), ProposalCore) else None,
            accepted=True,
        )
        vm = build_proposal_viewmodel(candidate)
        vm_pairs.append((vm, entry))

    viewmodels = [vm for vm, _ in vm_pairs]
    if not viewmodels:
        return

    sorted_vms = sort_records(viewmodels, PROPOSALS_SPEC)
    vm_map = {id(vm): entry for vm, entry in vm_pairs}
    headers, rows = proposals_table(sorted_vms, spec=PROPOSALS_SPEC)
    indexed_rows: list[list[str]] = []
    ordered_entries: list[Mapping[str, Any]] = []
    for index, (vm, row) in enumerate(zip(sorted_vms, rows), start=1):
        indexed_rows.append([str(index), *row])
        mapped_entry = vm_map.get(id(vm))
        if mapped_entry is not None:
            ordered_entries.append(mapped_entry)

    print("Geaccepteerde voorstellen:")
    print(tabulate(indexed_rows, headers=["#", *headers], tablefmt="github"))

    if not ordered_entries:
        return

    while True:
        try:
            selection = prompt("Kies voorstel (0 om terug): ")
        except (EOFError, OSError):  # pragma: no cover - interactive fallback
            logger.debug("Prompt afgebroken tijdens selectie geaccepteerd voorstel")
            break
        if selection in {"", "0"}:
            break
        try:
            index = int(selection)
        except ValueError:
            print("❌ Ongeldige keuze")
            continue
        if index < 1 or index > len(ordered_entries):
            print("❌ Ongeldige keuze")
            continue
        chosen_entry = ordered_entries[index - 1]
        refreshed: StrategyProposal = chosen_entry["refreshed_proposal"]  # type: ignore[assignment]
        symbol_hint = (
            chosen_entry.get("refreshed_symbol")
            or _entry_symbol(chosen_entry)
            or (refreshed.legs[0].get("symbol") if refreshed.legs else None)
        )
        print()
        _display_rejection_proposal(
            session,
            refreshed,
            symbol_hint if isinstance(symbol_hint, str) else None,
        )
        print()


def _display_rejection_proposal(
    session: ControlPanelSession,
    proposal: StrategyProposal,
    symbol_hint: str | None,
) -> None:
    previous_symbol = session.symbol
    previous_strategy = session.strategy
    try:
        if symbol_hint:
            session.symbol = symbol_hint
        session.strategy = proposal.strategy
        _show_proposal_details(session, proposal)
    finally:
        session.symbol = previous_symbol
        session.strategy = previous_strategy


def _show_proposal_details(
    session: ControlPanelSession, proposal: StrategyProposal
) -> None:
    criteria_cfg = load_criteria()
    symbol = (
        str(session.symbol or proposal.legs[0].get("symbol", ""))
        if proposal.legs
        else str(session.symbol or "")
    )
    symbol = symbol or None
    spot_price = session.spot_price
    fetch_only_mode = bool(cfg.get("IB_FETCH_ONLY", False))
    refresh_result: SnapshotResult | None = None
    should_fetch = fetch_only_mode or prompt_yes_no("Haal orderinformatie van IB op?", True)
    if should_fetch:
        try:
            refresh_result = fetch_quote_snapshot(
                proposal,
                criteria=criteria_cfg,
                spot_price=spot_price if isinstance(spot_price, (int, float)) else None,
                timeout=float(cfg.get("MARKET_DATA_TIMEOUT", 15)),
            )
            proposal = refresh_result.proposal
        except Exception as exc:
            logger.exception("IB marktdata refresh mislukt: %s", exc)
            print(f"❌ Marktdata ophalen mislukt: {exc}")

    entry_stub: dict[str, Any] = {"symbol": symbol} if symbol else {}
    core = build_proposal_core(proposal, symbol=symbol, entry=entry_stub)
    candidate = RefreshProposal(
        proposal=proposal,
        source=RefreshSource(index=0, entry=entry_stub, symbol=symbol),
        reasons=list(refresh_result.reasons) if refresh_result else [],
        missing_quotes=list(refresh_result.missing_quotes) if refresh_result else [],
        core=core,
        accepted=refresh_result.accepted if refresh_result else None,
    )

    earnings_ctx = {
        "symbol": symbol,
        "next_earnings": session.next_earnings,
        "days_until_earnings": session.days_until_earnings,
    }
    vm = build_proposal_viewmodel(candidate, earnings_ctx)

    leg_headers, leg_rows = proposal_legs_table(vm)
    if leg_rows:
        print(tabulate(leg_rows, headers=leg_headers, tablefmt="github"))

    summary_headers, summary_rows = proposal_summary_table(vm)
    if summary_rows:
        print(tabulate(summary_rows, headers=summary_headers, tablefmt="github"))

    earnings_headers, earnings_rows = proposal_earnings_table(vm)
    if earnings_rows:
        print(tabulate(earnings_rows, headers=earnings_headers, tablefmt="github"))

    for warning in vm.warnings:
        print(warning)

    acceptance_failed = vm.accepted is False
    if acceptance_failed:
        print("❌ Acceptatiecriteria niet gehaald na IB-refresh.")
        for detail in vm.reasons:
            msg = getattr(detail, "message", None) or getattr(detail, "code", None)
            if not msg:
                msg = str(detail)
            print(f"  - {msg}")

    if vm.has_missing_edge and not cfg.get("ALLOW_INCOMPLETE_METRICS", False):
        if not prompt_yes_no(
            "⚠️ Deze strategie bevat onvolledige edge-informatie. Toch accepteren?",
            False,
        ):
            return

    if prompt_yes_no("Voorstel opslaan naar CSV?", False):
        _export_proposal_csv(session, proposal)
    if prompt_yes_no("Voorstel opslaan naar JSON?", False):
        _export_proposal_json(session, proposal)

    can_send_order = not acceptance_failed and not fetch_only_mode
    if can_send_order and prompt_yes_no("Order naar IB sturen?", False):
        _submit_ib_order(session, proposal, symbol=symbol)
    elif fetch_only_mode:
        print("ℹ️ fetch_only modus actief – orders worden niet verstuurd.")

    proposal_strategy = getattr(proposal, "strategy", None)
    strategy_label = str(session.strategy or proposal_strategy or "") or None
    journal_lines = render_journal_entries(
        {"proposal": proposal, "symbol": symbol, "strategy": strategy_label}
    )
    print("\nJournal entry voorstel:\n" + "\n".join(journal_lines))


def _submit_ib_order(
    session: ControlPanelSession, proposal: StrategyProposal, *, symbol: str | None = None
) -> None:
    ticker = symbol or str(session.symbol or "")
    if not ticker:
        print("❌ Geen symbool beschikbaar voor orderplaatsing.")
        return
    account = str(cfg.get("IB_ACCOUNT_ALIAS") or "") or None
    order_type = str(cfg.get("DEFAULT_ORDER_TYPE", "LMT"))
    tif = str(cfg.get("DEFAULT_TIME_IN_FORCE", "DAY"))
    try:
        instructions = prepare_order_instructions(
            proposal,
            symbol=ticker,
            account=account,
            order_type=order_type,
            tif=tif,
        )
    except Exception as exc:
        logger.exception("Ordervoorbereiding mislukt: %s", exc)
        print(f"❌ Kon order niet voorbereiden: {exc}")
        return

    export_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    log_path = OrderSubmissionService.dump_order_log(instructions, directory=export_dir)
    print(f"📝 Orderstructuur opgeslagen in: {log_path}")

    if cfg.get("IB_FETCH_ONLY", False):
        logger.info("fetch_only-modus actief; orders niet verzonden")
        return

    host = str(cfg.get("IB_HOST", "127.0.0.1"))
    paper_mode = bool(cfg.get("IB_PAPER_MODE", True))
    port_key = "IB_PORT" if paper_mode else "IB_LIVE_PORT"
    port = int(cfg.get(port_key, 7497 if paper_mode else 7496))
    client_id = int(cfg.get("IB_ORDER_CLIENT_ID", cfg.get("IB_CLIENT_ID", 100)))
    timeout = int(cfg.get("DOWNLOAD_TIMEOUT", 5))
    service = OrderSubmissionService()
    app = None
    try:
        app, order_ids = service.place_orders(
            instructions,
            host=host,
            port=port,
            client_id=client_id,
            timeout=timeout,
        )
    except Exception as exc:
        print(f"❌ Verzenden naar IB mislukt: {exc}")
        return
    finally:
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                logger.debug("Probleem bij sluiten IB-verbinding", exc_info=True)

    print(f"✅ {len(order_ids)} order(s) als concept verstuurd naar IB (client {client_id}).")


def _save_trades(session: ControlPanelSession, trades: list[dict[str, object]]) -> None:
    symbol = str(session.symbol or "SYMB")
    strat = str(session.strategy or "strategy").replace(" ", "_")
    expiry = str(trades[0].get("expiry", "")) if trades else ""
    base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = base / f"trade_candidates_{symbol}_{strat}_{expiry}_{ts}.csv"
    fieldnames = [k for k in trades[0].keys() if k not in {"rom", "ev"}]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in trades:
            out: dict[str, object] = {}
            for k, v in row.items():
                if k not in fieldnames:
                    continue
                if k in {"pos", "rom", "ev", "edge", "mid", "model", "delta", "margin"}:
                    try:
                        out[k] = f"{float(v):.2f}"
                    except Exception:
                        out[k] = ""
                else:
                    out[k] = v
            writer.writerow(out)
    print(f"✅ Trades opgeslagen in: {path.resolve()}")


def _export_proposal_csv(
    session: ControlPanelSession, proposal: StrategyProposal
) -> Path:
    symbol = str(session.symbol or "").strip() or None
    strategy_name = str(session.strategy or proposal.strategy or "").strip() or None

    run_meta = _build_run_metadata(session, symbol=symbol, strategy=strategy_name)
    footer_rows: list[tuple[str, object]] = [
        ("credit", proposal.credit),
        ("margin", proposal.margin),
        ("max_profit", proposal.max_profit),
        ("max_loss", proposal.max_loss),
        ("rom", proposal.rom),
        ("pos", proposal.pos),
        ("ev", proposal.ev),
        ("edge", proposal.edge),
        ("score", proposal.score),
        ("profit_estimated", proposal.profit_estimated),
        ("scenario_info", proposal.scenario_info),
        ("breakevens", proposal.breakevens or []),
        ("atr", proposal.atr),
        ("iv_rank", proposal.iv_rank),
        ("iv_percentile", proposal.iv_percentile),
        ("hv20", proposal.hv20),
        ("hv30", proposal.hv30),
        ("hv90", proposal.hv90),
        ("dte", proposal.dte),
        ("breakeven_distances", proposal.breakeven_distances or {"dollar": [], "percent": []}),
        ("wing_width", proposal.wing_width),
        ("wing_symmetry", proposal.wing_symmetry),
    ]
    run_meta = run_meta.with_extra(footer_rows=footer_rows)

    export_dir = Path(cfg.get("EXPORT_DIR", "exports"))
    strategy_tag = [strategy_name.replace(" ", "_")] if strategy_name else None
    export_path = build_export_path(
        "proposal",
        run_meta,
        extension="csv",
        directory=export_dir,
        tags=strategy_tag,
    )

    columns = [
        "expiry",
        "strike",
        "type",
        "position",
        "bid",
        "ask",
        "mid",
        "delta",
        "theta",
        "vega",
        "edge",
        "manual_override",
        "missing_metrics",
        "metrics_ignored",
    ]

    records: list[dict[str, object]] = []
    for leg in proposal.legs:
        row = dict(leg)
        metrics = leg.get("missing_metrics") or []
        if isinstance(metrics, (list, tuple)):
            row["missing_metrics"] = ",".join(str(m) for m in metrics)
        records.append(row)

    result_path = export_proposals_csv(
        records,
        columns=columns,
        path=export_path,
        run_meta=run_meta,
    )
    print(f"✅ Voorstel opgeslagen in: {result_path.resolve()}")
    return result_path


def _load_acceptance_criteria(strategy: str) -> dict[str, Any]:
    """Return current acceptance criteria for ``strategy``."""

    config_data = cfg.get("STRATEGY_CONFIG") or {}
    rules = load_strike_config(strategy, config_data) if config_data else {}
    try:
        min_rom = (
            float(rules.get("min_rom"))
            if rules.get("min_rom") is not None
            else None
        )
    except Exception:
        min_rom = None
    return {
        "min_rom": min_rom,
        "min_pos": 0.0,
        "require_positive_ev": True,
        "allow_missing_edge": bool(cfg.get("ALLOW_INCOMPLETE_METRICS", False)),
    }


def _load_portfolio_context() -> tuple[dict[str, Any], bool]:
    """Return portfolio context and availability flag."""

    ctx = {
        "net_delta": None,
        "net_theta": None,
        "net_vega": None,
        "margin_used": None,
        "positions_open": None,
    }
    if not POSITIONS_FILE.exists() or not ACCOUNT_INFO_FILE.exists():
        return ctx, False
    try:
        positions = json.loads(POSITIONS_FILE.read_text())
        account = json.loads(ACCOUNT_INFO_FILE.read_text())
        greeks = compute_portfolio_greeks(positions)
        ctx.update(
            {
                "net_delta": greeks.get("Delta"),
                "net_theta": greeks.get("Theta"),
                "net_vega": greeks.get("Vega"),
                "positions_open": len(positions),
                "margin_used": (
                    float(account.get("FullInitMarginReq"))
                    if account.get("FullInitMarginReq") is not None
                    else None
                ),
            }
        )
    except Exception:
        return ctx, False
    return ctx, True


def _export_proposal_json(
    session: ControlPanelSession, proposal: StrategyProposal
) -> Path:
    symbol = str(session.symbol or "").strip() or None
    strategy_name = str(session.strategy or proposal.strategy or "").strip() or None
    strategy_file = strategy_name.replace(" ", "_") if strategy_name else None

    run_meta = _build_run_metadata(session, symbol=symbol, strategy=strategy_name)

    accept = _load_acceptance_criteria(strategy_file or proposal.strategy)
    portfolio_ctx, portfolio_available = _load_portfolio_context()
    spot_price = session.spot_price

    earnings_dict = load_json(
        cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
    )
    next_earn = None
    if isinstance(earnings_dict, dict) and symbol:
        earnings_list = earnings_dict.get(symbol)
        if isinstance(earnings_list, list):
            upcoming: list[datetime] = []
            for ds in earnings_list:
                try:
                    d = datetime.strptime(ds, "%Y-%m-%d").date()
                except Exception:
                    continue
                if d >= today():
                    upcoming.append(d)
            if upcoming:
                next_earn = min(upcoming).strftime("%Y-%m-%d")

    data = {
        "symbol": symbol,
        "spot_price": spot_price,
        "strategy": strategy_file or proposal.strategy,
        "next_earnings_date": next_earn,
        "legs": proposal.legs,
        "metrics": {
            "credit": proposal.credit,
            "margin": proposal.margin,
            "pos": proposal.pos,
            "rom": proposal.rom,
            "ev": proposal.ev,
            "average_edge": proposal.edge,
            "max_profit": (
                proposal.max_profit if proposal.max_profit is not None else "unlimited"
            ),
            "max_loss": (
                proposal.max_loss if proposal.max_loss is not None else "unlimited"
            ),
            "breakevens": proposal.breakevens or [],
            "score": proposal.score,
            "profit_estimated": proposal.profit_estimated,
            "scenario_info": proposal.scenario_info,
            "atr": proposal.atr,
            "iv_rank": proposal.iv_rank,
            "iv_percentile": proposal.iv_percentile,
            "hv": {
                "hv20": proposal.hv20,
                "hv30": proposal.hv30,
                "hv90": proposal.hv90,
            },
            "dte": proposal.dte,
            "breakeven_distances": (
                proposal.breakeven_distances
                if proposal.breakeven_distances is not None
                else {"dollar": [], "percent": []}
            ),
            "missing_data": {
                "missing_bidask": any(
                    (
                        (b := l.get("bid")) is None
                        or (
                            isinstance(b, (int, float))
                            and (math.isnan(b) or b <= 0)
                        )
                    )
                    or (
                        (a := l.get("ask")) is None
                        or (
                            isinstance(a, (int, float))
                            and (math.isnan(a) or a <= 0)
                        )
                    )
                    for l in proposal.legs
                ),
                "missing_edge": proposal.edge is None,
                "fallback_mid": any(
                    l.get("mid_fallback") in {"close", "parity_close", "model"}
                    or (
                        l.get("mid") is not None
                        and (
                            (
                                (b := l.get("bid")) is None
                                or (
                                    isinstance(b, (int, float))
                                    and (math.isnan(b) or b <= 0)
                                )
                            )
                            or (
                                (a := l.get("ask")) is None
                                or (
                                    isinstance(a, (int, float))
                                    and (math.isnan(a) or a <= 0)
                                )
                            )
                        )
                    )
                    for l in proposal.legs
                ),
            },
        },
        "tomic_acceptance_criteria": accept,
        "portfolio_context": portfolio_ctx,
        "portfolio_context_available": portfolio_available,
        "wing_width": proposal.wing_width,
        "wing_symmetry": proposal.wing_symmetry,
    }

    export_dir = Path(cfg.get("EXPORT_DIR", "exports"))
    strategy_tag = [strategy_file] if strategy_file else None
    export_path = build_export_path(
        "proposal",
        run_meta,
        extension="json",
        directory=export_dir,
        tags=strategy_tag,
    )

    result_path = export_proposals_json(
        data,
        path=export_path,
        run_meta=run_meta,
    )
    print(f"✅ Voorstel opgeslagen in: {result_path.resolve()}")
    return result_path
def _print_reason_summary(
    session: ControlPanelSession, summary: RejectionSummary | None
) -> None:
    """Display aggregated rejection information."""

    entries = session.combo_evaluations
    eval_entries = list(entries) if isinstance(entries, Sequence) else []
    headers, rows, rejects = build_rejection_table(eval_entries)

    has_summary_data = bool(
        summary
        and (
            (summary.by_filter and len(summary.by_filter) > 0)
            or (summary.by_reason and len(summary.by_reason) > 0)
            or (summary.by_strategy and len(summary.by_strategy) > 0)
        )
    )

    if not has_summary_data and not rejects:
        print("Geen opties door filters afgewezen")
        return

    if has_summary_data and (
        SHOW_REASONS
        or prompt_yes_no("Wil je een samenvatting van rejection reasons (y/n)?", False)
    ):
        if summary.by_filter:
            rows_filter = sorted(summary.by_filter.items(), key=lambda x: x[1], reverse=True)
            print("Afwijzingen per filter:")
            print(tabulate(rows_filter, headers=["Filter", "Aantal"], tablefmt="github"))
        if summary.by_reason:
            rows_reason = sorted(summary.by_reason.items(), key=lambda x: x[1], reverse=True)
            print("Redenen:")
            print(tabulate(rows_reason, headers=["Reden", "Aantal"], tablefmt="github"))
            agg = ReasonAggregator()
            agg.extend_reason_counts(summary.by_reason)
            if agg.by_category:
                total_counts = sum(max(int(c), 0) for c in summary.by_reason.values())
                ordered_categories = sorted(
                    agg.by_category.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
                category_rows: list[list[str]] = []
                for category, count in ordered_categories:
                    label = ReasonAggregator.label_for(category)
                    pct = (
                        f"{round((count / total_counts) * 100)}%"
                        if total_counts
                        else "0%"
                    )
                    category_rows.append([label, count, pct])
                if category_rows:
                    print("Redenen per categorie:")
                    print(
                        tabulate(
                            category_rows,
                            headers=["Categorie", "Aantal", "%"],
                            tablefmt="github",
                        )
                    )
        if summary.by_strategy:
            print("Redenen per strategie:")
            for strat, reasons in summary.by_strategy.items():
                print(f"{strat}:")
                for r in reasons:
                    print(f"• {reason_label(r)}")

    if not rejects:
        return

    if not (SHOW_REASONS or prompt_yes_no("Wil je meer details opvraagbaar per rij (y/n)?", False)):
        return

    if not headers or not rows:
        print("Geen detailgegevens beschikbaar.")
        return

    print(tabulate(rows, headers=headers, tablefmt="github"))

    if len(rejects) > 1:
        print("Voer 'A' in om IB-orderinformatie voor alle regels te verversen.")

    while True:
        selection = prompt("Kies nummer (0 om terug, A voor alles):")
        normalized = selection.strip().lower() if isinstance(selection, str) else ""
        if normalized in {"", "0"}:
            break
        if normalized in {"a", "all"}:
            _refresh_reject_entries(session, rejects)
            continue
        try:
            idx = int(selection)
        except ValueError:
            print("❌ Ongeldige keuze")
            continue
        if idx < 1 or idx > len(rejects):
            print("❌ Ongeldige keuze")
            continue
        print()
        _show_rejection_detail(session, rejects[idx - 1])
        print()


SHOW_REASONS = False


def _load_spot_from_metrics(directory: Path, symbol: str) -> float | None:
    """Return spot price from a metrics CSV in ``directory`` if available."""
    pattern = f"other_data_{symbol.upper()}_*.csv"
    files = list(directory.glob(pattern))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        with latest.open(newline="") as f:
            row = next(csv.DictReader(f))
            spot = row.get("SpotPrice") or row.get("spotprice")
            return float(spot) if spot is not None else None
    except Exception:
        return None


def _spot_from_chain(chain: list[dict]) -> float | None:
    """Return first positive spot-like value from option ``chain``.

    The option chain may include fields such as ``spot``, ``underlying_price`` or
    ``underlying`` that reflect the underlying price at the time the chain was
    generated. This helper scans known keys and returns the first valid value.
    If no suitable value is found, ``None`` is returned.
    """

    keys = ("spot", "underlying_price", "underlying", "underlying_close", "close")
    for rec in chain:
        for key in keys:
            val = rec.get(key)
            try:
                num = float(val)
            except Exception:
                continue
            if num > 0:
                return num
    return None

def refresh_spot_price(symbol: str) -> float | None:
    """Fetch and cache the current spot price for ``symbol``.

    Uses :class:`PolygonClient` to retrieve the delayed last trade price and
    caches it under :data:`PRICE_HISTORY_DIR` as ``<SYMBOL>_spot.json``.
    When existing data is newer than roughly ten minutes the cached value is
    reused.
    """

    sym = symbol.upper()
    base = Path(cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    base.mkdir(parents=True, exist_ok=True)
    spot_file = base / f"{sym}_spot.json"

    meta = load_price_meta()
    now = datetime.now()
    meta_key = f"spot_{sym}"
    ts_str = meta.get(meta_key)
    if spot_file.exists() and ts_str:
        try:
            ts = datetime.fromisoformat(ts_str)
            if (now - ts).total_seconds() < 600:
                data = load_json(spot_file)
                price = None
                if isinstance(data, dict):
                    price = data.get("price") or data.get("close")
                elif isinstance(data, list) and data:
                    rec = data[-1]
                    price = rec.get("price") or rec.get("close")
                if price is not None:
                    return float(price)
        except Exception:
            pass

    client = PolygonClient()
    try:
        client.connect()
        price = client.fetch_spot_price(sym)
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning(f"⚠️ Spot price fetch failed for {sym}: {exc}")
        price = None
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    if price is None:
        return None

    save_json({"price": float(price), "timestamp": now.isoformat()}, spot_file)
    meta[meta_key] = now.isoformat()
    save_price_meta(meta)
    return float(price)


def run_module(module_name: str, *args: str) -> None:
    """Run a Python module using ``python -m``."""
    subprocess.run([sys.executable, "-m", module_name, *args], check=True)


def save_portfolio_timestamp() -> None:
    """Store the datetime of the latest portfolio fetch."""
    META_FILE.write_text(json.dumps({"last_update": datetime.now().isoformat()}))


def load_portfolio_timestamp() -> str | None:
    """Return the ISO timestamp of the last portfolio update if available."""
    if not META_FILE.exists():
        return None
    try:
        data = json.loads(META_FILE.read_text())
        return data.get("last_update")
    except Exception:
        return None


def print_saved_portfolio_greeks() -> None:
    """Compute and display portfolio Greeks from saved positions."""
    if not POSITIONS_FILE.exists():
        return
    try:
        positions = json.loads(POSITIONS_FILE.read_text())
    except Exception:
        print("⚠️ Kan portfolio niet laden voor Greeks-overzicht.")
        return
    portfolio = compute_portfolio_greeks(positions)
    print("📐 Portfolio Greeks:")
    for key, val in portfolio.items():
        print(f"{key}: {val:+.4f}")


def print_api_version() -> None:
    """Connect to TWS and display the server version information."""
    try:
        app = connect_ib()
        print(f"Server versie: {app.serverVersion()}")
        print(f"Verbindingstijd: {app.twsConnectionTime()}")
    except Exception:
        print("❌ Geen verbinding met TWS")
        return
    finally:
        try:
            app.disconnect()
        except Exception:
            pass


def check_ib_connection() -> None:
    """Test whether the IB API is reachable."""
    try:
        app = connect_ib()
        app.disconnect()
        print("✅ Verbinding met TWS beschikbaar")
    except Exception:
        print("❌ Geen verbinding met TWS")


def run_dataexporter(services: ControlPanelServices | None = None) -> None:
    """Menu for export and CSV validation utilities."""

    if services is None:
        services = _create_services(ControlPanelSession())

    def export_one() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        try:
            run_module("tomic.api.getonemarket", symbol)
        except subprocess.CalledProcessError:
            print("❌ Export mislukt")

    def export_chain_bulk() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        try:
            run_module("tomic.cli.option_lookup_bulk", symbol)
        except subprocess.CalledProcessError:
            print("❌ Export mislukt")

    def csv_check() -> None:
        path = prompt("Pad naar CSV-bestand: ")
        if not path:
            print("Geen pad opgegeven")
            return
        try:
            run_module("tomic.cli.csv_quality_check", path)
        except subprocess.CalledProcessError:
            print("❌ Kwaliteitscheck mislukt")

    def export_all() -> None:
        sub = Menu("Selecteer exporttype")
        sub.add(
            "Alleen marktdata",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-metrics"),
        )
        sub.add(
            "Alleen optionchains",
            lambda: run_module("tomic.api.getallmarkets_async", "--only-chains"),
        )
        sub.add(
            "Marktdata en optionchains",
            lambda: run_module("tomic.api.getallmarkets_async"),
        )
        sub.run()

    def bench_getonemarket() -> None:
        raw = prompt("Symbolen (spatiegescheiden): ")
        symbols = [s.strip().upper() for s in raw.split() if s.strip()]
        if not symbols:
            print("Geen symbolen opgegeven")
            return
        try:
            run_module("tomic.analysis.bench_getonemarket", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Benchmark mislukt")

    def fetch_prices() -> None:
        raw = prompt("Symbolen (spatiegescheiden, leeg=default): ")
        symbols = [s.strip().upper() for s in raw.split() if s.strip()]
        try:
            run_module("tomic.cli.fetch_prices", *symbols)
        except subprocess.CalledProcessError:
            print("❌ Ophalen van prijzen mislukt")

    def show_history() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        data = load_price_history(symbol.upper())
        rows = [[rec.get("date"), rec.get("close")] for rec in data[-10:]] if data else []
        if not rows:
            print("⚠️ Geen data gevonden")
            return
        rows.sort(key=lambda r: r[0], reverse=True)
        print(tabulate(rows, headers=["Datum", "Close"], tablefmt="github"))

    def polygon_chain() -> None:
        symbol = prompt("Ticker symbool: ").strip().upper()
        if not symbol:
            print("❌ Geen symbool opgegeven")
            return

        try:
            path = services.export.fetch_polygon_chain(symbol)
        except Exception as exc:
            print(f"❌ Ophalen van optionchain mislukt: {exc}")
            return

        if path:
            print(f"✅ Option chain opgeslagen in: {path.resolve()}")
        else:
            date_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime(
                "%Y%m%d"
            )
            print(f"⚠️ Geen exportbestand gevonden in {date_dir.resolve()}")

    def polygon_metrics() -> None:
        symbol = prompt("Ticker symbool: ")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        from tomic.polygon_client import PolygonClient

        client = PolygonClient()
        client.connect()
        try:
            metrics = client.fetch_market_metrics(symbol)
            print(json.dumps(metrics, indent=2))
        except Exception:
            print("❌ Ophalen van metrics mislukt")
        finally:
            client.disconnect()

    def run_github_action() -> None:
        """Run the 'Update price history' GitHub Action locally."""
        try:
            run_module("tomic.cli.fetch_prices_polygon")
        except subprocess.CalledProcessError:
            print("❌ Ophalen van prijzen mislukt")
            return

        try:
            changed = services.export.git_commit(
                "Update price history",
                Path("tomic/data/spot_prices"),
                Path("tomic/data/iv_daily_summary"),
                Path("tomic/data/historical_volatility"),
            )
            if not changed:
                print("No changes to commit")
        except subprocess.CalledProcessError:
            print("❌ Git-commando mislukt")

    def run_intraday_action() -> None:
        """Run the intraday price update GitHub Action locally."""
        try:
            run_module("tomic.cli.fetch_intraday_polygon")
        except subprocess.CalledProcessError:
            print("❌ Ophalen van intraday prijzen mislukt")
            return

        try:
            changed = services.export.git_commit(
                "Update intraday prices", Path("tomic/data/spot_prices")
            )
            if not changed:
                print("No changes to commit")
        except subprocess.CalledProcessError:
            print("❌ Git-commando mislukt")

    def fetch_earnings() -> None:
        try:
            run_module("tomic.cli.fetch_earnings_alpha")
        except subprocess.CalledProcessError:
            print("❌ Earnings ophalen mislukt")

    def import_market_chameleon_earnings() -> None:
        runtime_config.load()
        last_csv = runtime_config.get("import.last_earnings_csv_path") or ""
        csv_input = prompt(
            "Voer pad in naar MarketChameleon-CSV (ENTER voor laatst gebruikt): ",
            last_csv,
        )
        if not csv_input:
            print("❌ Geen pad opgegeven")
            return

        csv_path = Path(csv_input).expanduser()
        if not csv_path.exists():
            print(f"❌ CSV niet gevonden: {csv_path}")
            return

        runtime_config.set_value("import.last_earnings_csv_path", str(csv_path))

        symbol_col = runtime_config.get("earnings_import.symbol_col", "Symbol")
        next_candidates = runtime_config.get(
            "earnings_import.next_col_candidates",
            ["Next Earnings", "Next Earnings "],
        )
        if isinstance(next_candidates, str):
            next_cols = [next_candidates]
        else:
            next_cols = [str(col) for col in next_candidates]

        try:
            csv_map = parse_earnings_csv(
                str(csv_path),
                symbol_col=symbol_col or "Symbol",
                next_col_candidates=next_cols,
            )
        except Exception as exc:  # pragma: no cover - user feedback path
            logger.error(f"CSV import mislukt: {exc}")
            print(f"❌ CSV import mislukt: {exc}")
            return

        if not csv_map:
            print("ℹ️ Geen geldige earnings gevonden in CSV.")
            return

        json_path_cfg = runtime_config.get("data.earnings_json_path")
        json_path = Path(
            json_path_cfg
            or cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
        ).expanduser()

        try:
            json_data = load_earnings_json(json_path)
        except Exception as exc:  # pragma: no cover - invalid JSON path
            logger.error(f"Laden van earnings JSON mislukt: {exc}")
            print(f"❌ Laden van earnings JSON mislukt: {exc}")
            return

        today_override = runtime_config.get("earnings_import.today_override")
        if isinstance(today_override, str) and today_override:
            try:
                today_date = datetime.strptime(today_override, "%Y-%m-%d").date()
            except ValueError:
                today_date = date.today()
        elif isinstance(today_override, date):
            today_date = today_override
        else:
            today_date = date.today()

        _, changes = update_next_earnings(
            json_data,
            csv_map,
            today_date,
            dry_run=True,
        )

        if not changes:
            print("ℹ️ Geen wijzigingen nodig volgens CSV.")
            return

        rows = []
        removed_total = 0
        for idx, change in enumerate(changes, start=1):
            removed = int(change.get("removed_same_month", 0))
            removed_total += removed
            rows.append(
                [
                    idx,
                    change.get("symbol", ""),
                    change.get("old_future") or "-",
                    change.get("new_future") or "-",
                    change.get("action", ""),
                    removed,
                ]
            )

        headers = [
            "#",
            "Symbol",
            "Old Closest Future",
            "New Next",
            "Action",
            "RemovedSameMonthCount",
        ]
        print("\nDry-run wijzigingen:")
        print(tabulate(rows, headers=headers, tablefmt="github"))
        print(f"\nVerwijderd vanwege dezelfde maand: {removed_total}")

        replaced_count = sum(1 for c in changes if c.get("action") == "replaced_closest_future")
        inserted_count = sum(
            1 for c in changes if c.get("action") in {"inserted_as_next", "created_symbol"}
        )
        print(
            f"Samenvatting: totaal={len(changes)} vervangen={replaced_count}"
            f" ingevoegd={inserted_count}"
        )

        if not prompt_yes_no("Doorvoeren?"):
            print("Import geannuleerd.")
            return

        try:
            updated_data, _ = update_next_earnings(
                json_data,
                csv_map,
                today_date,
                dry_run=False,
            )
            save_earnings_json(updated_data, json_path)
        except Exception as exc:  # pragma: no cover - file write errors
            logger.error(f"Opslaan van earnings JSON mislukt: {exc}")
            print(f"❌ Opslaan mislukt: {exc}")
            return

        runtime_config.set_value("data.earnings_json_path", str(json_path))

        backup_path = save_earnings_json.last_backup_path
        if backup_path:
            print(f"Klaar. Backup: {backup_path}")
        else:
            print("Klaar. JSON bestand aangemaakt zonder backup.")

        logger.success(
            f"Earnings import voltooid voor {len(changes)} symbolen naar {json_path}"
        )

    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("OptionChain ophalen via TWS API", export_chain_bulk)
    menu.add("OptionChain ophalen via Polygon API", polygon_chain)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Run GitHub Action lokaal", run_github_action)
    menu.add("Run GitHub Action lokaal - intraday", run_intraday_action)
    menu.add("Backfill historical_volatility obv spotprices", run_backfill_hv)
    menu.add("IV backfill", run_iv_backfill_flow)
    menu.add("Fetch Earnings", fetch_earnings)
    menu.add("Import nieuwe earning dates van MarketChameleon", import_market_chameleon_earnings)

    menu.run()


def run_trade_management() -> None:
    """Menu for journal management tasks."""

    menu = Menu("⚙️ TRADES & JOURNAL")
    menu.add(
        "Overzicht bekijken", lambda: run_module("tomic.journal.journal_inspector")
    )
    menu.add(
        "Nieuwe trade aanmaken", lambda: run_module("tomic.journal.journal_updater")
    )
    menu.add(
        "Trade aanpassen / snapshot toevoegen",
        lambda: run_module("tomic.journal.journal_inspector"),
    )
    menu.add(
        "Journal updaten met positie IDs",
        lambda: run_module("tomic.cli.link_positions"),
    )

    menu.add("Trade afsluiten", lambda: run_module("tomic.cli.close_trade"))
    menu.run()


def run_risk_tools() -> None:
    """Menu for risk analysis helpers."""

    menu = Menu("🚦 RISICO TOOLS & SYNTHETICA")
    menu.add("Entry checker", lambda: run_module("tomic.cli.entry_checker"))
    menu.add("Scenario-analyse", lambda: run_module("tomic.cli.portfolio_scenario"))
    menu.add("Event watcher", lambda: run_module("tomic.cli.event_watcher"))
    menu.add("Synthetics detector", lambda: run_module("tomic.cli.synthetics_detector"))
    menu.add("ATR Calculator", lambda: run_module("tomic.cli.atr_calculator"))
    menu.add(
        "Theoretical value calculator",
        lambda: run_module("tomic.cli.bs_calculator"),
    )
    menu.run()


def run_portfolio_menu(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    session = session or ControlPanelSession()
    services = services or _create_services(session)
    """Menu to fetch and display portfolio information."""

    def fetch_and_show() -> None:
        print("ℹ️ Haal portfolio op...")
        try:
            run_module("tomic.api.getaccountinfo")
            save_portfolio_timestamp()
        except subprocess.CalledProcessError:
            print("❌ Ophalen van portfolio mislukt")
            return
        view = prompt("Weergavemodus (compact/full/alerts): ", "full").strip().lower()
        try:
            run_module(
                STRATEGY_DASHBOARD_MODULE,
                str(POSITIONS_FILE),
                str(ACCOUNT_INFO_FILE),
                f"--view={view}",
            )
            run_module("tomic.analysis.performance_analyzer")
        except subprocess.CalledProcessError:
            print("❌ Dashboard kon niet worden gestart")

    def show_saved() -> None:
        if not (POSITIONS_FILE.exists() and ACCOUNT_INFO_FILE.exists()):
            print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
            return
        ts = load_portfolio_timestamp()
        if ts:
            print(f"ℹ️ Laatste update: {ts}")
        print_saved_portfolio_greeks()
        view = prompt("Weergavemodus (compact/full/alerts): ", "full").strip().lower()
        try:
            run_module(
                STRATEGY_DASHBOARD_MODULE,
                str(POSITIONS_FILE),
                str(ACCOUNT_INFO_FILE),
                f"--view={view}",
            )
            run_module("tomic.analysis.performance_analyzer")
        except subprocess.CalledProcessError:
            print("❌ Dashboard kon niet worden gestart")

    def show_greeks() -> None:
        if not POSITIONS_FILE.exists():
            print("⚠️ Geen opgeslagen portfolio gevonden. Kies optie 1 om te verversen.")
            return
        try:
            run_module("tomic.cli.portfolio_greeks", str(POSITIONS_FILE))
        except subprocess.CalledProcessError:
            print("❌ Greeks-overzicht kon niet worden getoond")
    def print_factsheet(chosen: dict[str, object]) -> None:
        """Print key metrics for the selected recommendation."""

        def fmt(val: object, digits: int = 4) -> str:
            return f"{val:.{digits}f}" if isinstance(val, (int, float)) else ""

        def fmt_pct(val: object) -> str:
            return f"{val * 100:.0f}" if isinstance(val, (int, float)) else ""

        factsheet = services.portfolio.build_factsheet(chosen)
        earn_str = ""
        if isinstance(factsheet.next_earnings, date):
            earn_str = factsheet.next_earnings.isoformat()
            if isinstance(factsheet.days_until_earnings, int):
                earn_str += f" ({factsheet.days_until_earnings}d)"

        rows = [
            ["Symbool", factsheet.symbol],
            ["Strategie", factsheet.strategy or ""],
            ["Spot", fmt(factsheet.spot)],
            ["IV", fmt(factsheet.iv)],
            ["HV20", fmt(factsheet.hv20)],
            ["HV30", fmt(factsheet.hv30)],
            ["HV90", fmt(factsheet.hv90)],
            ["HV252", fmt(factsheet.hv252)],
            ["Term m1/m2", fmt(factsheet.term_m1_m2, 2)],
            ["Term m1/m3", fmt(factsheet.term_m1_m3, 2)],
            ["IV Rank", fmt_pct(factsheet.iv_rank)],
            ["IV Perc", fmt_pct(factsheet.iv_percentile)],
            ["Skew", fmt(factsheet.skew, 2)],
            ["Earnings", earn_str],
            ["Criteria", factsheet.criteria or ""],
        ]

        print(tabulate(rows, headers=["Veld", "Waarde"], tablefmt="github"))

    def show_market_info() -> None:
        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]

        vix_value = None
        try:
            metrics = fetch_volatility_metrics(symbols[0] if symbols else "SPY")
            vix_value = metrics.get("vix")
        except Exception:
            vix_value = None
        if isinstance(vix_value, (int, float)):
            print(f"VIX {vix_value:.2f}")

        snapshot = services.market_snapshot.load_snapshot({"symbols": symbols})

        def _as_overview_row(data: object) -> list[object]:
            return [
                getattr(data, "symbol", None),
                getattr(data, "spot", None),
                getattr(data, "iv", None),
                getattr(data, "hv20", None),
                getattr(data, "hv30", None),
                getattr(data, "hv90", None),
                getattr(data, "hv252", None),
                getattr(data, "iv_rank", None),
                getattr(data, "iv_percentile", None),
                getattr(data, "term_m1_m2", None),
                getattr(data, "term_m1_m3", None),
                getattr(data, "skew", None),
                getattr(data, "next_earnings", None),
                getattr(data, "days_until_earnings", None),
            ]

        rows = [_as_overview_row(row) for row in snapshot.rows]

        recs, table_rows, meta = build_market_overview(rows)

        earnings_filtered = {}
        if isinstance(meta, dict):
            earnings_filtered = meta.get("earnings_filtered", {}) or {}
        if isinstance(earnings_filtered, dict) and earnings_filtered:
            total_hidden = sum(len(strategies) for strategies in earnings_filtered.values())
            detail_parts = []
            for symbol in sorted(earnings_filtered):
                strategies = ", ".join(earnings_filtered[symbol])
                detail_parts.append(f"{symbol}: {strategies}")
            detail_msg = "; ".join(detail_parts)
            print(
                f"ℹ️ {total_hidden} aanbevelingen verborgen vanwege earnings-filter"
                + (f" ({detail_msg})" if detail_msg else "")
            )

        def _run_market_scan() -> None:
            if not recs:
                print("⚠️ Geen aanbevelingen beschikbaar voor scan.")
                return

            top_raw = cfg.get("MARKET_SCAN_TOP_N", 10)
            try:
                top_n = int(top_raw)
            except Exception:
                print(f"⚠️ Markt scan overgeslagen: ongeldige MARKET_SCAN_TOP_N ({top_raw!r})")
                return
            if top_n <= 0:
                print("⚠️ MARKET_SCAN_TOP_N is 0 — scan overgeslagen.")
                return

            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for rec in recs:
                symbol = str(rec.get("symbol") or "").upper()
                strategy_name = str(rec.get("strategy") or "")
                if not symbol or not strategy_name:
                    continue
                grouped[symbol].append(rec)

            if not grouped:
                print("⚠️ Geen symbolen om te scannen.")
                return

            existing_chain_dir: Path | None = None

            def _select_existing_chain_dir() -> Path | None:
                while True:
                    raw = prompt(
                        "Map met bestaande optionchains (enter om opnieuw te downloaden): "
                    )
                    if not raw:
                        return None
                    candidate = Path(raw).expanduser()
                    if candidate.exists() and candidate.is_dir():
                        return candidate
                    print(f"❌ Map niet gevonden: {raw}")

            existing_chain_dir = _select_existing_chain_dir()
            if existing_chain_dir:
                try:
                    display_path = existing_chain_dir.resolve()
                except Exception:
                    display_path = existing_chain_dir
                print(f"📂 Gebruik bestaande optionchains uit: {display_path}")
            else:
                print("🔍 Markt scan via Polygon gestart…")

            pipeline = services.get_pipeline()
            config_data = cfg.get("STRATEGY_CONFIG") or {}
            interest_rate = float(cfg.get("INTEREST_RATE", 0.05))
            prep_config = ChainPreparationConfig.from_app_config()

            scan_requests: list[MarketScanRequest] = []
            for symbol, symbol_recs in grouped.items():
                for rec in symbol_recs:
                    raw_strategy = str(rec.get("strategy") or "")
                    strategy = raw_strategy.lower().replace(" ", "_")
                    if not strategy:
                        continue
                    earnings_value = rec.get("next_earnings")
                    earnings_date: date | None = None
                    if isinstance(earnings_value, date):
                        earnings_date = earnings_value
                    elif isinstance(earnings_value, str):
                        earnings_date = parse_date(earnings_value)
                    scan_requests.append(
                        MarketScanRequest(
                            symbol=symbol,
                            strategy=strategy,
                            metrics=dict(rec),
                            next_earnings=earnings_date,
                        )
                    )

            if not scan_requests:
                print("⚠️ Geen voorstellen gevonden tijdens scan.")
                return

            scan_service = MarketScanService(
                pipeline,
                services.portfolio,
                interest_rate=interest_rate,
                strategy_config=config_data,
                chain_config=prep_config,
                refresh_spot_price=refresh_spot_price,
                load_spot_from_metrics=_load_spot_from_metrics,
                load_latest_close=_load_latest_close,
                spot_from_chain=_spot_from_chain,
                atr_loader=latest_atr,
            )

            def _chain_source(symbol: str) -> Path | None:
                return select_chain_source(
                    symbol,
                    existing_dir=existing_chain_dir,
                    fetch_chain=services.export.fetch_polygon_chain,
                )

            try:
                candidates = scan_service.run_market_scan(
                    scan_requests,
                    chain_source=_chain_source,
                    top_n=top_n,
                )
            except MarketScanError as exc:
                logger.exception("Market scan pipeline failed")
                print(f"❌ Markt scan mislukt: {exc}")
                return
            except CandidateRankingError as exc:
                logger.exception("Candidate ranking failed")
                print(f"❌ Rangschikking van voorstellen mislukt: {exc}")
                return

            if not candidates:
                print("⚠️ Geen voorstellen gevonden tijdens scan.")
                return

            def _fmt_pct(value: float | None) -> str:
                if value is None:
                    return "—"
                return f"{value:.0f}%"

            def _fmt_ratio(value: float | None) -> str:
                if value is None:
                    return "—"
                return f"{value:.2f}"

            def _fmt_money(value: float | None) -> str:
                if value is None:
                    return "—"
                return f"{value:.2f}"

            rows_out: list[list[str]] = []
            for idx, cand in enumerate(candidates, 1):
                prop = cand.proposal
                iv_rank_pct = (
                    float(cand.iv_rank) * 100 if cand.iv_rank is not None else None
                )
                skew_fmt = "—"
                if cand.skew is not None:
                    try:
                        skew_fmt = f"{float(cand.skew):.2f}"
                    except Exception:
                        skew_fmt = "—"
                earnings = "—"
                earn_val = cand.next_earnings
                if isinstance(earn_val, date):
                    earnings = earn_val.isoformat()
                elif isinstance(earn_val, str) and earn_val:
                    earnings = earn_val
                mid_sources = ",".join(cand.mid_sources) if cand.mid_sources else "quotes"
                dte_summary = cand.dte_summary or format_dtes(prop.legs)
                rows_out.append(
                    [
                        idx,
                        cand.symbol,
                        cand.strategy,
                        _fmt_money(prop.score),
                        _fmt_money(prop.ev),
                        _fmt_ratio(cand.risk_reward),
                        dte_summary,
                        _fmt_pct(iv_rank_pct),
                        skew_fmt,
                        _fmt_pct(cand.bid_ask_pct),
                        mid_sources,
                        earnings,
                    ]
                )

            table_headers = [
                "Nr",
                "Symbool",
                "Strategie",
                "Score",
                "EV",
                "R/R",
                "DTE",
                "IV Rank",
                "Skew",
                "Bid/Ask%",
                "MidSrc",
                "Earnings",
            ]
            table_output = tabulate(
                rows_out,
                headers=table_headers,
                tablefmt="github",
                colalign=(
                    "right",
                    "left",
                    "left",
                    "right",
                    "right",
                    "right",
                    "left",
                    "right",
                    "right",
                    "right",
                    "left",
                    "left",
                ),
            )
            print(table_output)

            while True:
                sel = prompt("Selectie scan (0 om terug): ")
                if sel in {"", "0"}:
                    break
                try:
                    idx = int(sel) - 1
                    chosen = candidates[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                session.update_from_mapping(
                    {
                        "symbol": chosen.symbol,
                        "strategy": chosen.strategy,
                        "spot_price": chosen.spot,
                    }
                )
                _show_proposal_details(session, chosen.proposal)
                print()
                print(table_output)

        if recs:
            print(
                tabulate(
                    table_rows,
                    headers=[
                        "Nr",
                        "Symbool",
                        "Strategie",
                        "IV",
                        "Delta",
                        "Vega",
                        "Theta",
                        "IV Rank (HV)",
                        "Skew",
                        "Earnings",
                    ],
                    tablefmt="github",
                    colalign=(
                        "right",
                        "left",
                        "left",
                        "right",
                        "left",
                        "left",
                        "left",
                        "right",
                        "right",
                        "left",
                    ),
                )
            )

            while True:
                sel = prompt("Selectie (0 om terug, 999 voor scan): ")
                if sel == "999":
                    _run_market_scan()
                    continue
                if sel in {"", "0"}:
                    break
                try:
                    idx = int(sel) - 1
                    chosen = recs[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                session.update_from_mapping(chosen)
                symbol_label = session.symbol or "—"
                strategy_label = session.strategy or "—"
                print(f"\n🎯 Gekozen strategie: {symbol_label} – {strategy_label}\n")
                print_factsheet(chosen)
                choose_chain_source()
                return

    def show_informative_market_info() -> None:
        symbols = [s.upper() for s in cfg.get("DEFAULT_SYMBOLS", [])]

        vix_value = None
        try:
            metrics = fetch_volatility_metrics(symbols[0] if symbols else "SPY")
            vix_value = metrics.get("vix")
        except Exception:
            vix_value = None
        if isinstance(vix_value, (int, float)):
            print(f"VIX {vix_value:.2f}")

        snapshot = MARKET_SNAPSHOT_SERVICE.load_snapshot({"symbols": symbols})

        def fmt4(val: float | None) -> str:
            return f"{val:.4f}" if val is not None else ""

        def fmt2(val: float | None) -> str:
            return f"{val:.2f}" if val is not None else ""

        formatted_rows = []
        for row in snapshot.rows:
            formatted_rows.append(
                [
                    getattr(row, "symbol", None),
                    getattr(row, "spot", None),
                    fmt4(getattr(row, "iv", None)),
                    fmt4(getattr(row, "hv20", None)),
                    fmt4(getattr(row, "hv30", None)),
                    fmt4(getattr(row, "hv90", None)),
                    fmt4(getattr(row, "hv252", None)),
                    fmt2(getattr(row, "iv_rank", None)),
                    fmt2(getattr(row, "iv_percentile", None)),
                    getattr(row, "term_m1_m2", None),
                    getattr(row, "term_m1_m3", None),
                    getattr(row, "skew", None),
                    getattr(row, "next_earnings", None),
                ]
            )

        headers = [
            "symbol",
            "spotprice",
            "IV",
            "hv20",
            "hv30",
            "hv90",
            "hv252",
            "iv_rank (HV)",
            "iv_percentile (HV)",
            "term_m1_m2",
            "term_m1_m3",
            "skew",
            "next_earnings",
        ]

        print(tabulate(formatted_rows, headers=headers, tablefmt="github"))

    def _process_chain(path: Path) -> None:
        prep_config = ChainPreparationConfig.from_app_config()
        try:
            prepared = load_and_prepare_chain(path, prep_config)
        except ChainPreparationError as exc:
            print(f"⚠️ {exc}")
            return

        if prepared.quality < prep_config.min_quality:
            print(
                f"⚠️ CSV kwaliteit {prepared.quality:.1f}% lager dan {prep_config.min_quality}%"
            )
        else:
            print(f"CSV kwaliteit {prepared.quality:.1f}%")

        if not prompt_yes_no("Doorgaan?", False):
            return

        if prompt_yes_no("Wil je delta/iv interpoleren om de data te verbeteren?", False):
            try:
                prepared = load_and_prepare_chain(
                    path, prep_config, apply_interpolation=True
                )
            except ChainPreparationError as exc:
                print(f"⚠️ {exc}")
                return
            print("✅ Interpolatie toegepast op ontbrekende delta/iv.")
            print(f"Nieuwe CSV kwaliteit {prepared.quality:.1f}%")

        symbol = str(session.symbol or "")
        spot_price = resolve_chain_spot_price(
            symbol,
            prepared,
            refresh_quote=refresh_spot_price,
            load_metrics_spot=_load_spot_from_metrics,
            load_latest_close=_load_latest_close,
            chain_spot_fallback=_spot_from_chain,
        )
        if not isinstance(spot_price, (int, float)) or spot_price <= 0:
            spot_price = _spot_from_chain(prepared.records) or 0.0
        session.spot_price = spot_price

        strategy_name = str(session.strategy or "").lower().replace(" ", "_")
        pipeline = services.get_pipeline()
        atr_val = latest_atr(symbol) or 0.0
        eval_config = ChainEvaluationConfig.from_app_config(
            symbol=symbol,
            strategy=strategy_name,
            spot_price=float(spot_price or 0.0),
            atr=atr_val,
        )

        evaluation = evaluate_chain(prepared, pipeline, eval_config)
        evaluation_summary = session.combo_evaluation_summary
        if isinstance(evaluation_summary, EvaluationSummary) or evaluation_summary is None:
            _print_evaluation_overview(
                evaluation.context.symbol,
                evaluation.context.spot_price,
                evaluation_summary,
            )
        _print_reason_summary(session, evaluation.filter_preview)

        evaluated = evaluation.evaluated_trades
        session.evaluated_trades = list(evaluated)
        session.spot_price = evaluation.context.spot_price

        if evaluated:
            close_price, close_date = _load_latest_close(symbol)
            if close_price is not None and close_date:
                print(f"Close {close_date}: {close_price}")
            if atr_val:
                print(f"ATR: {atr_val:.2f}")
            else:
                print("ATR: n.v.t.")

            rows = []
            for row in evaluated[:10]:
                rows.append(
                    [
                        row.get("expiry"),
                        row.get("strike"),
                        row.get("type"),
                        (
                            f"{row.get('delta'):+.2f}"
                            if row.get("delta") is not None
                            else ""
                        ),
                        f"{row.get('edge'):.2f}" if row.get("edge") is not None else "",
                        f"{row.get('pos'):.1f}%" if row.get("pos") is not None else "",
                    ]
                )
            print(
                tabulate(
                    rows,
                    headers=[
                        "Expiry",
                        "Strike",
                        "Type",
                        "Delta",
                        "Edge",
                        "PoS",
                    ],
                    tablefmt="github",
                )
            )
            if prompt_yes_no("Opslaan naar CSV?", False):
                _save_trades(session, evaluated)
            if prompt_yes_no("Doorgaan naar strategie voorstellen?", False):
                global SHOW_REASONS
                SHOW_REASONS = True

                latest_spot = refresh_spot_price(symbol)
                if isinstance(latest_spot, (int, float)) and latest_spot > 0:
                    session.spot_price = float(latest_spot)
                    evaluation.context.spot_price = float(latest_spot)

                if evaluation.context.spot_price > 0:
                    print(f"Spotprice: {evaluation.context.spot_price:.2f}")
                else:
                    print("Spotprice: onbekend")

                proposals = evaluation.proposals
                summary = evaluation.summary
                if proposals:
                    rom_w = cfg.get("SCORE_WEIGHT_ROM", 0.5)
                    pos_w = cfg.get("SCORE_WEIGHT_POS", 0.3)
                    ev_w = cfg.get("SCORE_WEIGHT_EV", 0.2)
                    print(
                        f"Scoregewichten: ROM {rom_w*100:.0f}% | PoS {pos_w*100:.0f}% | EV {ev_w*100:.0f}%"
                    )
                    rows2 = []
                    warn_edge = False
                    no_scenario = False
                    for prop in proposals:
                        legs_desc = "; ".join(
                            f"{'S' if leg.get('position',0)<0 else 'L'}{leg.get('type')}{leg.get('strike')} {leg.get('expiry', '?')}"
                            for leg in prop.legs
                        )
                        for leg in prop.legs:
                            if leg.get("edge") is None:
                                logger.debug(
                                    f"[EDGE missing] {leg.get('position')} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')}"
                                )
                        if any(leg.get("edge") is None for leg in prop.legs):
                            warn_edge = True
                        edge_vals = [
                            float(leg.get("edge"))
                            for leg in prop.legs
                            if leg.get("edge") is not None
                        ]
                        if not edge_vals:
                            edge_display = "—"
                        elif len(edge_vals) < len(prop.legs):
                            mn = min(edge_vals)
                            if mn < 0:
                                edge_display = f"min={mn:.2f}"
                            else:
                                edge_display = (
                                    f"avg={sum(edge_vals)/len(edge_vals):.2f}"
                                )
                        else:
                            edge_display = f"{sum(edge_vals)/len(edge_vals):.2f}"

                        label = None
                        if getattr(prop, "scenario_info", None):
                            label = prop.scenario_info.get("scenario_label")
                            if prop.scenario_info.get("error") == "no scenario defined":
                                no_scenario = True
                        suffix = ""
                        if prop.profit_estimated:
                            suffix = f" {label} (geschat)" if label else " (geschat)"

                        ev_display = (
                            f"{prop.ev:.2f}{suffix}" if prop.ev is not None else "—"
                        )
                        rom_display = (
                            f"{prop.rom:.2f}{suffix}" if prop.rom is not None else "—"
                        )

                        rows2.append(
                            [
                                f"{prop.score:.2f}" if prop.score is not None else "—",
                                f"{prop.pos:.1f}" if prop.pos is not None else "—",
                                ev_display,
                                rom_display,
                                edge_display,
                                legs_desc,
                            ]
                        )
                    print(
                        tabulate(
                            rows2,
                            headers=["Score", "PoS", "EV", "ROM", "Edge", "Legs"],
                            tablefmt="github",
                        )
                    )
                    if no_scenario:
                        print("no scenario defined")
                    if warn_edge:
                        print("⚠️ Eén of meerdere edges niet beschikbaar")
                    if SHOW_REASONS:
                        _print_reason_summary(session, summary)
                    while True:
                        sel = prompt("Kies voorstel (0 om terug): ")
                        if sel in {"", "0"}:
                            break
                        try:
                            idx = int(sel) - 1
                            chosen_prop = proposals[idx]
                        except (ValueError, IndexError):
                            print("❌ Ongeldige keuze")
                            continue
                        _show_proposal_details(session, chosen_prop)
                        break
                else:
                    print("⚠️ Geen voorstellen gevonden")
                    _print_reason_summary(session, summary)
        else:
            print("⚠️ Geen geschikte strikes gevonden.")
            _print_reason_summary(session, evaluation.summary)
            print("➤ Controleer of de juiste expiraties beschikbaar zijn in de chain.")
            print("➤ Of pas je selectiecriteria aan in strike_selection_rules.yaml.")

    def choose_chain_source() -> None:
        symbol = session.symbol
        if not symbol:
            print("⚠️ Geen strategie geselecteerd")
            return

        def use_ib() -> None:
            path = services.export.export_chain(str(symbol))
            if not path:
                print("⚠️ Geen chain gevonden")
                return
            _process_chain(path)

        def use_polygon() -> None:
            path = services.export.fetch_polygon_chain(str(symbol))
            if not path:
                print("⚠️ Geen polygon chain gevonden")
                return
            _process_chain(path)

        def manual() -> None:
            p = prompt("Pad naar CSV: ")
            if not p:
                return
            _process_chain(Path(p))

        menu = Menu("Chain ophalen")
        menu.add("Download nieuwe chain via TWS", use_ib)
        menu.add("Download nieuwe chain via Polygon", use_polygon)
        menu.add("CSV handmatig kiezen", manual)
        menu.run()

    menu = Menu("📊 ANALYSE & STRATEGIE")
    menu.add("Trading Plan", lambda: run_module("tomic.cli.trading_plan"))
    menu.add("Portfolio ophalen en tonen", fetch_and_show)
    menu.add("Laatst opgehaalde portfolio tonen", show_saved)
    menu.add(
        "Trademanagement (controleer exitcriteria)",
        lambda: run_module("tomic.cli.trade_management"),
    )
    menu.add("Toon marktinformatie", show_market_info)

    def _show_earnings_info() -> None:
        try:
            run_module("tomic.cli.earnings_info")
        except subprocess.CalledProcessError:
            print("❌ Earnings-informatie kon niet worden getoond")

    menu.add("Earnings-informatie", _show_earnings_info)
    menu.run()


def run_settings_menu() -> None:
    """Menu to view and edit configuration."""

    def show_config() -> None:
        asdict = (
            cfg.CONFIG.model_dump
            if hasattr(cfg.CONFIG, "model_dump")
            else cfg.CONFIG.dict
        )
        for key, value in asdict().items():
            print(f"{key}: {value}")

    def change_host() -> None:
        host_default = cfg.get("IB_HOST")
        port_default = cfg.get("IB_PORT")
        host = prompt(f"Host ({host_default}): ", host_default)
        port_str = prompt(f"Poort ({port_default}): ")
        port = int(port_str) if port_str else port_default
        cfg.update({"IB_HOST": host, "IB_PORT": port})

    def change_symbols() -> None:
        print("Huidige symbols:", ", ".join(cfg.get("DEFAULT_SYMBOLS", [])))
        raw = prompt("Nieuw lijst (comma-sep): ")
        if raw:
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
            save_symbols(symbols)

    def change_rate() -> None:
        rate_default = cfg.get("INTEREST_RATE")
        rate_str = prompt(f"Rente ({rate_default}): ")
        if rate_str:
            try:
                rate = float(rate_str)
            except ValueError:
                print("❌ Ongeldige rente")
                return
            cfg.update({"INTEREST_RATE": rate})

    def change_path(key: str) -> None:
        current = cfg.get(key)
        value = prompt(f"{key} ({current}): ")
        if value:
            cfg.update({key: value})

    def change_int(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: int(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_float(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ")
        if val:
            try:
                cfg.update({key: float(val)})
            except ValueError:
                print("❌ Ongeldige waarde")

    def change_str(key: str) -> None:
        current = cfg.get(key)
        val = prompt(f"{key} ({current}): ", current)
        if val:
            cfg.update({key: val})

    def change_bool(key: str) -> None:
        current = cfg.get(key)
        val = prompt_yes_no(f"{key}?", current)
        cfg.update({key: val})

    def run_connection_menu() -> None:
        sub = Menu("\U0001f50c Verbinding & API – TWS instellingen en tests")
        sub.add("Pas IB host/poort aan", change_host)
        sub.add("Wijzig client ID", lambda: change_int("IB_CLIENT_ID"))
        sub.add("Test TWS-verbinding", check_ib_connection)
        sub.add("Haal TWS API-versie op", print_api_version)
        sub.run()

    def run_general_menu() -> None:
        sub = Menu("\U0001f4c8 Portfolio & Analyse")
        sub.add("Pas default symbols aan", change_symbols)
        sub.add("Pas interest rate aan", change_rate)
        sub.add(
            "USE_HISTORICAL_IV_WHEN_CLOSED",
            lambda: change_bool("USE_HISTORICAL_IV_WHEN_CLOSED"),
        )
        sub.add(
            "INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN",
            lambda: change_bool("INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN"),
        )
        sub.run()

    def run_logging_menu() -> None:
        sub = Menu("\U0001fab5 Logging & Gedrag")

        def set_info() -> None:
            cfg.update({"LOG_LEVEL": "INFO"})
            os.environ["TOMIC_LOG_LEVEL"] = "INFO"
            setup_logging()

        def set_debug() -> None:
            cfg.update({"LOG_LEVEL": "DEBUG"})
            os.environ["TOMIC_LOG_LEVEL"] = "DEBUG"
            setup_logging()

        sub.add("Stel logniveau in op INFO", set_info)
        sub.add("Stel logniveau in op DEBUG", set_debug)
        sub.run()

    def run_paths_menu() -> None:
        sub = Menu("\U0001f4c1 Bestandslocaties")
        sub.add("ACCOUNT_INFO_FILE", lambda: change_path("ACCOUNT_INFO_FILE"))
        sub.add("JOURNAL_FILE", lambda: change_path("JOURNAL_FILE"))
        sub.add("POSITIONS_FILE", lambda: change_path("POSITIONS_FILE"))
        sub.add("PORTFOLIO_META_FILE", lambda: change_path("PORTFOLIO_META_FILE"))
        sub.add("VOLATILITY_DB", lambda: change_path("VOLATILITY_DB"))
        sub.add("EXPORT_DIR", lambda: change_path("EXPORT_DIR"))
        sub.run()

    def run_network_menu() -> None:
        sub = Menu("\U0001f310 Netwerk & Snelheid")
        sub.add(
            "CONTRACT_DETAILS_TIMEOUT",
            lambda: change_int("CONTRACT_DETAILS_TIMEOUT"),
        )
        sub.add(
            "CONTRACT_DETAILS_RETRIES",
            lambda: change_int("CONTRACT_DETAILS_RETRIES"),
        )
        sub.add("DOWNLOAD_TIMEOUT", lambda: change_int("DOWNLOAD_TIMEOUT"))
        sub.add("DOWNLOAD_RETRIES", lambda: change_int("DOWNLOAD_RETRIES"))
        sub.add(
            "MAX_CONCURRENT_REQUESTS",
            lambda: change_int("MAX_CONCURRENT_REQUESTS"),
        )
        sub.add("BID_ASK_TIMEOUT", lambda: change_int("BID_ASK_TIMEOUT"))
        sub.add("MARKET_DATA_TIMEOUT", lambda: change_int("MARKET_DATA_TIMEOUT"))
        sub.add("OPTION_DATA_RETRIES", lambda: change_int("OPTION_DATA_RETRIES"))
        sub.add("OPTION_RETRY_WAIT", lambda: change_int("OPTION_RETRY_WAIT"))
        sub.run()

    def run_option_menu() -> None:
        def show_open_settings() -> None:
            print("Huidige reqMktData instellingen:")
            print(f"MKT_GENERIC_TICKS: {cfg.get('MKT_GENERIC_TICKS', '100,101,106')}")
            print(
                f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}"
            )
            print(
                f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}"
            )

        def show_closed_settings() -> None:
            print("Huidige reqHistoricalData instellingen:")
            print(
                f"USE_HISTORICAL_IV_WHEN_CLOSED: {cfg.get('USE_HISTORICAL_IV_WHEN_CLOSED', True)}"
            )
            print(f"HIST_DURATION: {cfg.get('HIST_DURATION', '1 D')}")
            print(f"HIST_BARSIZE: {cfg.get('HIST_BARSIZE', '1 day')}")
            print(f"HIST_WHAT: {cfg.get('HIST_WHAT', 'TRADES')}")
            print(
                f"UNDERLYING_PRIMARY_EXCHANGE: {cfg.get('UNDERLYING_PRIMARY_EXCHANGE', '')}"
            )
            print(
                f"OPTIONS_PRIMARY_EXCHANGE: {cfg.get('OPTIONS_PRIMARY_EXCHANGE', '')}"
            )

        def run_open_menu() -> None:
            show_open_settings()
            menu = Menu("Markt open – reqMktData")
            menu.add("MKT_GENERIC_TICKS", lambda: change_str("MKT_GENERIC_TICKS"))
            menu.add(
                "UNDERLYING_PRIMARY_EXCHANGE",
                lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
            )
            menu.add(
                "OPTIONS_PRIMARY_EXCHANGE",
                lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
            )
            menu.run()

        def run_closed_menu() -> None:
            show_closed_settings()
            menu = Menu("Markt dicht – reqHistoricalData")
            menu.add(
                "USE_HISTORICAL_IV_WHEN_CLOSED",
                lambda: change_bool("USE_HISTORICAL_IV_WHEN_CLOSED"),
            )
            menu.add("HIST_DURATION", lambda: change_str("HIST_DURATION"))
            menu.add("HIST_BARSIZE", lambda: change_str("HIST_BARSIZE"))
            menu.add("HIST_WHAT", lambda: change_str("HIST_WHAT"))
            menu.add(
                "UNDERLYING_PRIMARY_EXCHANGE",
                lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
            )
            menu.add(
                "OPTIONS_PRIMARY_EXCHANGE",
                lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
            )
            menu.run()

        sub = Menu("\U0001f4dd Optie-strategie parameters")
        sub.add("STRIKE_RANGE", lambda: change_int("STRIKE_RANGE"))
        sub.add("FIRST_EXPIRY_MIN_DTE", lambda: change_int("FIRST_EXPIRY_MIN_DTE"))
        sub.add("DELTA_MIN", lambda: change_float("DELTA_MIN"))
        sub.add("DELTA_MAX", lambda: change_float("DELTA_MAX"))
        sub.add("AMOUNT_REGULARS", lambda: change_int("AMOUNT_REGULARS"))
        sub.add("AMOUNT_WEEKLIES", lambda: change_int("AMOUNT_WEEKLIES"))
        sub.add("UNDERLYING_EXCHANGE", lambda: change_str("UNDERLYING_EXCHANGE"))
        sub.add(
            "UNDERLYING_PRIMARY_EXCHANGE",
            lambda: change_str("UNDERLYING_PRIMARY_EXCHANGE"),
        )
        sub.add("OPTIONS_EXCHANGE", lambda: change_str("OPTIONS_EXCHANGE"))
        sub.add(
            "OPTIONS_PRIMARY_EXCHANGE",
            lambda: change_str("OPTIONS_PRIMARY_EXCHANGE"),
        )
        sub.add("Markt open – reqMktData", run_open_menu)
        sub.add("Markt dicht – reqHistoricalData", run_closed_menu)
        sub.run()

    def run_rules_menu() -> None:
        path = prompt("Pad naar criteria.yaml (optioneel): ")
        sub = Menu("\U0001f4dc Criteria beheren")

        sub.add("Toon criteria", lambda: run_module("tomic.cli.rules", "show"))

        def _validate() -> None:
            if path:
                run_module("tomic.cli.rules", "validate", path)
            else:
                run_module("tomic.cli.rules", "validate")

        def _validate_reload() -> None:
            if path:
                run_module("tomic.cli.rules", "validate", path, "--reload")
            else:
                run_module("tomic.cli.rules", "validate", "--reload")

        sub.add("Valideer criteria.yaml", _validate)
        sub.add("Valideer & reload", _validate_reload)
        sub.add(
            "Reload zonder validatie", lambda: run_module("tomic.cli.rules", "reload")
        )
        sub.run()

    def run_strategy_criteria_menu() -> None:
        sub = Menu("\U0001f3af Strategie & Criteria")
        sub.add("Optie-strategie parameters", run_option_menu)
        sub.add("Criteria beheren", run_rules_menu)
        sub.run()

    menu = Menu("\u2699\ufe0f INSTELLINGEN & CONFIGURATIE")
    menu.add("Portfolio & Analyse", run_general_menu)
    menu.add("Verbinding & API", run_connection_menu)
    menu.add("Netwerk & Snelheid", run_network_menu)
    menu.add("Bestandslocaties", run_paths_menu)
    menu.add("Strategie & Criteria", run_strategy_criteria_menu)
    menu.add("Logging & Gedrag", run_logging_menu)
    menu.add("Toon volledige configuratie", show_config)
    menu.run()


def run_controlpanel(
    session: ControlPanelSession | None = None,
    services: ControlPanelServices | None = None,
) -> None:
    """Render the main control panel menu with injected dependencies."""

    session = session or ControlPanelSession()
    services = services or _create_services(session)

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    menu.add("Analyse & Strategie", lambda: run_portfolio_menu(session, services))
    menu.add("Data & Marktdata", lambda: run_dataexporter(services))
    menu.add("Trades & Journal", run_trade_management)
    menu.add("Risicotools & Synthetica", run_risk_tools)
    menu.add("Configuratie", run_settings_menu)
    menu.run()
    print("Tot ziens.")


def main(argv: list[str] | None = None) -> None:
    """Start the interactive control panel."""

    parser = argparse.ArgumentParser(description="TOMIC control panel")
    parser.add_argument(
        "--show-reasons",
        action="store_true",
        help="Toon selectie- en strategie-redenen",
    )
    args = parser.parse_args(argv or [])

    global SHOW_REASONS
    SHOW_REASONS = args.show_reasons

    session = ControlPanelSession()
    services = _create_services(session)
    run_controlpanel(session, services)


if __name__ == "__main__":
    main(sys.argv[1:])
