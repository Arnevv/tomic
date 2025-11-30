"""Automated entry flow for opening new option positions.

This module orchestrates the full entry pipeline:
1. Load IV/market snapshot data
2. Generate recommendations via build_market_overview
3. Run market scan to generate proposals
4. Filter by position limits
5. IB quote refresh for accurate pricing
6. Submit orders
7. Create journal entries

Designed to run headless via scheduler (Windows Task Scheduler / cron).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def _fmt_ms(seconds: float) -> str:
    """Format seconds as milliseconds string."""
    return f"{seconds * 1000:.0f}ms"

from tomic import config as cfg
from tomic.analysis.market_overview import build_market_overview
from tomic.core.portfolio import services as portfolio_services
from tomic.exports import refresh_spot_price, load_spot_from_metrics, spot_from_chain
from tomic.helpers.dateutils import parse_date
from tomic.journal.service import add_trade
from tomic.logutils import logger
from tomic.services.chain_processing import ChainPreparationConfig
from tomic.services.chain_sources import ChainSourceDecision, ChainSourceError
from tomic.services.market_scan_service import (
    MarketScanError,
    MarketScanRequest,
    MarketScanService,
)
from tomic.services.market_snapshot_service import MarketSnapshotService
from tomic.services.pipeline_factory import create_strategy_pipeline
from tomic.services.portfolio_service import Candidate, CandidateRankingError, PortfolioService
from tomic.services.position_limits import (
    PositionLimitsConfig,
    PositionLimitsResult,
    evaluate_position_limits,
    filter_candidates_by_limits,
)
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.utils import latest_atr


@dataclass
class EntryFlowConfig:
    """Configuration for the automated entry flow."""

    max_open_trades: int = 5
    max_per_symbol: int = 1
    ib_refresh: bool = True
    dry_run: bool = False
    top_n: int | None = None  # None = all accepted candidates

    @classmethod
    def from_config(cls) -> "EntryFlowConfig":
        """Load configuration from application settings."""
        return cls(
            max_open_trades=int(cfg.get("ENTRY_FLOW_MAX_OPEN_TRADES", 5)),
            max_per_symbol=int(cfg.get("ENTRY_FLOW_MAX_PER_SYMBOL", 1)),
            ib_refresh=bool(cfg.get("ENTRY_FLOW_IB_REFRESH", True)),
            dry_run=bool(cfg.get("ENTRY_FLOW_DRY_RUN", False)),
            top_n=cfg.get("ENTRY_FLOW_TOP_N"),
        )


@dataclass
class EntryAttempt:
    """Result of a single entry attempt."""

    symbol: str
    strategy: str
    status: str  # "success", "failed", "skipped", "dry_run"
    reason: str | None = None
    order_ids: tuple[int, ...] = ()
    proposal: StrategyProposal | None = None
    journal_entry: Mapping[str, Any] | None = None


@dataclass
class EntryFlowResult:
    """Aggregated result of the entry flow execution."""

    status: str  # "success", "partial", "no_candidates", "failed"
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    position_state: PositionLimitsResult | None = None
    candidates_found: int = 0
    candidates_after_limits: int = 0
    attempts: tuple[EntryAttempt, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def successful_entries(self) -> int:
        return sum(1 for a in self.attempts if a.status == "success")

    @property
    def failed_entries(self) -> int:
        return sum(1 for a in self.attempts if a.status == "failed")


def _default_symbols() -> list[str]:
    """Load the configured symbol universe."""
    raw = cfg.get("DEFAULT_SYMBOLS", []) or []
    symbols: list[str] = []
    for value in raw:
        if not isinstance(value, (str, bytes)):
            continue
        cleaned = str(value).strip()
        if cleaned:
            symbols.append(cleaned.upper())
    return symbols


def _snapshot_row_mapping(row: object) -> dict[str, Any]:
    """Convert a snapshot row to a dict for build_market_overview."""
    return {
        "symbol": getattr(row, "symbol", None),
        "spot": getattr(row, "spot", None),
        "iv": getattr(row, "iv", None),
        "hv20": getattr(row, "hv20", None),
        "hv30": getattr(row, "hv30", None),
        "hv90": getattr(row, "hv90", None),
        "hv252": getattr(row, "hv252", None),
        "iv_rank": getattr(row, "iv_rank", None),
        "iv_percentile": getattr(row, "iv_percentile", None),
        "term_m1_m2": getattr(row, "term_m1_m2", None),
        "term_m1_m3": getattr(row, "term_m1_m3", None),
        "skew": getattr(row, "skew", None),
        "next_earnings": getattr(row, "next_earnings", None),
        "days_until_earnings": getattr(row, "days_until_earnings", None),
    }


def _build_journal_entry(
    candidate: Candidate,
    proposal: StrategyProposal,
    order_ids: tuple[int, ...],
) -> dict[str, Any]:
    """Build a journal entry for a newly opened trade."""
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")

    # Get expiry from first leg
    expiry = None
    if proposal.legs:
        expiry = proposal.legs[0].get("expiry")

    trade_id = f"{proposal.strategy}_{candidate.symbol}_{expiry or 'UNK'}_{timestamp}"

    legs_data = []
    for leg in proposal.legs:
        legs_data.append({
            "action": leg.get("action") or ("SELL" if (leg.get("position") or 0) < 0 else "BUY"),
            "qty": abs(int(leg.get("qty") or leg.get("position") or 1)),
            "type": leg.get("right") or leg.get("type"),
            "strike": leg.get("strike"),
            "expiry": leg.get("expiry"),
            "conId": leg.get("conId") or leg.get("con_id"),
        })

    return {
        "TradeID": trade_id,
        "DatumIn": today,
        "DatumUit": None,
        "Symbool": candidate.symbol,
        "Type": proposal.strategy,
        "Expiry": expiry,
        "Spot": candidate.spot,
        "Richting": "credit" if (proposal.credit or 0) > 0 else "debit",
        "Status": "Open",
        "Premium": proposal.credit,
        "EntryPrice": proposal.credit,
        "ExitPrice": None,
        "InitMargin": getattr(proposal, "margin", None),
        "ReturnOnMargin": getattr(proposal, "rom", None),
        "IV_Entry": candidate.metrics.get("iv") if candidate.metrics else None,
        "Legs": legs_data,
        "OrderIDs": list(order_ids),
        "Source": "entry_flow_auto",
        "ExitRules": {
            "target_profit_pct": 50,
            "days_before_expiry": 7,
        },
    }


def execute_entry_flow(
    config: EntryFlowConfig | None = None,
    *,
    chain_source_factory: Callable[[str], ChainSourceDecision | None] | None = None,
) -> EntryFlowResult:
    """Execute the automated entry flow.

    This is the main entry point for scheduled entry automation.

    Args:
        config: Entry flow configuration. Uses defaults if not provided.
        chain_source_factory: Factory to resolve option chain sources.
            If not provided, uses Polygon via the export service.

    Returns:
        EntryFlowResult with details of all entry attempts.
    """
    t_flow_start = time.perf_counter()
    started_at = datetime.now()
    errors: list[str] = []
    attempts: list[EntryAttempt] = []

    if config is None:
        config = EntryFlowConfig.from_config()

    logger.info("[execute_entry_flow] START")
    logger.info("=" * 60)
    logger.info("Entry Flow gestart om %s", started_at.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  max_open_trades: %d", config.max_open_trades)
    logger.info("  max_per_symbol: %d", config.max_per_symbol)
    logger.info("  ib_refresh: %s", config.ib_refresh)
    logger.info("  dry_run: %s", config.dry_run)
    logger.info("  top_n: %s", config.top_n or "all")
    logger.info("=" * 60)

    # Step 1: Check position limits
    t_limits_start = time.perf_counter()
    logger.info("[execute_entry_flow] Step 1: checking position limits...")
    limits_config = PositionLimitsConfig(
        max_open_trades=config.max_open_trades,
        max_per_symbol=config.max_per_symbol,
    )
    position_state = evaluate_position_limits(limits_config)
    t_limits_elapsed = time.perf_counter() - t_limits_start

    logger.info(
        "[execute_entry_flow] position_limits: %s (open=%d, slots=%d, symbols=%s)",
        _fmt_ms(t_limits_elapsed),
        position_state.open_count,
        position_state.available_slots,
        sorted(position_state.symbols_with_positions),
    )

    if not position_state.can_open_any:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_entry_flow] DONE (no_slots) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_slots",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
        )

    # Step 2: Load market snapshot
    t_snapshot_start = time.perf_counter()
    logger.info("[execute_entry_flow] Step 2: loading market snapshot...")
    symbols = _default_symbols()
    if not symbols:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.warning("[execute_entry_flow] DONE (no_symbols) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_symbols",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
            errors=("Geen symbolen geconfigureerd",),
        )

    logger.info("[execute_entry_flow] loading snapshot for %d symbols: %s", len(symbols), symbols)
    snapshot_service = MarketSnapshotService(cfg)
    try:
        snapshot = snapshot_service.load_snapshot({"symbols": symbols})
    except Exception as exc:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.exception("[execute_entry_flow] snapshot load FAILED: %s (total: %s)", exc, _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
            errors=(f"Snapshot laden mislukt: {exc}",),
        )
    t_snapshot_elapsed = time.perf_counter() - t_snapshot_start
    logger.info("[execute_entry_flow] snapshot loaded: %s (%d rows)", _fmt_ms(t_snapshot_elapsed), len(snapshot.rows))

    # Step 3: Build recommendations via market overview
    t_overview_start = time.perf_counter()
    logger.info("[execute_entry_flow] Step 3: building market overview...")
    rows = [[mapping[key] for key in (
        "symbol", "spot", "iv", "hv20", "hv30", "hv90", "hv252",
        "iv_rank", "iv_percentile", "term_m1_m2", "term_m1_m3",
        "skew", "next_earnings", "days_until_earnings",
    )] for mapping in (_snapshot_row_mapping(row) for row in snapshot.rows)]

    recommendations, _, meta = build_market_overview(rows)
    t_overview_elapsed = time.perf_counter() - t_overview_start

    if not recommendations:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_entry_flow] DONE (no_candidates from overview) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_candidates",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
        )

    logger.info("[execute_entry_flow] market_overview: %s (%d recommendations)", _fmt_ms(t_overview_elapsed), len(recommendations))
    for rec in recommendations:
        logger.info("  → %s: %s (score=%.2f)", rec.get("symbol"), rec.get("strategy"), rec.get("score", 0))

    # Step 4: Build scan requests
    logger.info("[execute_entry_flow] Step 4: building scan requests...")
    scan_requests: list[MarketScanRequest] = []
    for rec in recommendations:
        symbol = str(rec.get("symbol") or "").upper()
        strategy = str(rec.get("strategy") or "").lower().replace(" ", "_")
        if not symbol or not strategy:
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
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_entry_flow] DONE (no_scan_requests) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_candidates",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
        )

    logger.info("[execute_entry_flow] built %d scan requests", len(scan_requests))

    # Step 5: Setup chain source
    logger.info("[execute_entry_flow] Step 5: setting up chain source (Polygon)...")
    from tomic.cli.app_services import create_controlpanel_services
    from tomic.cli.controlpanel_session import ControlPanelSession
    from tomic.strike_selector import StrikeSelector
    from tomic.strategy_candidates import generate_strategy_candidates

    session = ControlPanelSession()
    services = create_controlpanel_services(
        strike_selector_factory=StrikeSelector,
        strategy_generator=generate_strategy_candidates,
    )

    def _polygon_chain_source(symbol: str) -> ChainSourceDecision | None:
        if chain_source_factory:
            return chain_source_factory(symbol)
        try:
            return services.export.resolve_chain_source(symbol, source="polygon")
        except ChainSourceError as exc:
            logger.debug("Geen chain voor %s: %s", symbol, exc)
            return None

    # Step 6: Run market scan
    t_scan_start = time.perf_counter()
    logger.info("[execute_entry_flow] Step 6: running market scan (ib_refresh=%s)...", config.ib_refresh)
    pipeline = create_strategy_pipeline()
    portfolio_service = PortfolioService()
    prep_config = ChainPreparationConfig.from_app_config()
    interest_rate = float(cfg.get("INTEREST_RATE", 0.05))
    strategy_config = cfg.get("STRATEGY_CONFIG") or {}

    scan_service = MarketScanService(
        pipeline,
        portfolio_service,
        interest_rate=interest_rate,
        strategy_config=strategy_config,
        chain_config=prep_config,
        refresh_spot_price=refresh_spot_price,
        load_spot_from_metrics=load_spot_from_metrics,
        load_latest_close=portfolio_services.load_latest_close,
        spot_from_chain=spot_from_chain,
        atr_loader=latest_atr,
        refresh_snapshot=portfolio_services.refresh_proposal_from_ib if config.ib_refresh else None,
    )

    try:
        candidates = scan_service.run_market_scan(
            scan_requests,
            chain_source=_polygon_chain_source,
            top_n=config.top_n,
            refresh_quotes=config.ib_refresh,
        )
    except (MarketScanError, CandidateRankingError) as exc:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.exception("[execute_entry_flow] market_scan FAILED: %s (total: %s)", exc, _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="failed",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
            errors=(f"Market scan mislukt: {exc}",),
        )

    t_scan_elapsed = time.perf_counter() - t_scan_start
    candidates_found = len(candidates)
    logger.info("[execute_entry_flow] market_scan: %s (%d candidates found)", _fmt_ms(t_scan_elapsed), candidates_found)

    if not candidates:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_entry_flow] DONE (no_candidates from scan) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_candidates",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
            candidates_found=0,
        )

    # Step 7: Filter by position limits
    logger.info("[execute_entry_flow] Step 7: filtering by position limits...")
    candidate_dicts = [
        {"symbol": c.symbol, "strategy": c.strategy, "candidate": c}
        for c in candidates
    ]
    allowed, rejected = filter_candidates_by_limits(
        candidate_dicts,
        limits_config,
    )

    for item, reason in rejected:
        logger.info(
            "[execute_entry_flow] candidate REJECTED: %s/%s - %s",
            item.get("symbol"),
            item.get("strategy"),
            reason,
        )

    allowed_candidates = [item["candidate"] for item in allowed]
    logger.info(
        "[execute_entry_flow] position_limits_filter: %d/%d candidates allowed",
        len(allowed_candidates),
        candidates_found,
    )

    if not allowed_candidates:
        t_flow_elapsed = time.perf_counter() - t_flow_start
        logger.info("[execute_entry_flow] DONE (no_candidates after limits) total: %s", _fmt_ms(t_flow_elapsed))
        return EntryFlowResult(
            status="no_candidates",
            started_at=started_at,
            completed_at=datetime.now(),
            position_state=position_state,
            candidates_found=candidates_found,
            candidates_after_limits=0,
        )

    # Step 8: Submit orders for each candidate
    logger.info("[execute_entry_flow] Step 8: submitting orders for %d candidates...", len(allowed_candidates))
    for idx, candidate in enumerate(allowed_candidates, 1):
        t_order_start = time.perf_counter()
        symbol = candidate.symbol
        strategy = candidate.strategy
        proposal = candidate.proposal

        logger.info("-" * 40)
        logger.info("[execute_entry_flow] order %d/%d: %s / %s", idx, len(allowed_candidates), symbol, strategy)
        logger.info("  score=%.2f, credit=%.2f", candidate.score or 0, proposal.credit or 0)

        if config.dry_run:
            logger.info("  [DRY_RUN] order skipped (dry_run_mode)")
            attempts.append(
                EntryAttempt(
                    symbol=symbol,
                    strategy=strategy,
                    status="dry_run",
                    reason="dry_run_mode",
                    proposal=proposal,
                )
            )
            continue

        # Submit order
        try:
            result = portfolio_services.submit_order(
                proposal,
                symbol=symbol,
            )
        except portfolio_services.OrderSubmissionError as exc:
            t_order_elapsed = time.perf_counter() - t_order_start
            logger.error("[execute_entry_flow] order FAILED for %s: %s (%s)", symbol, exc, _fmt_ms(t_order_elapsed))
            attempts.append(
                EntryAttempt(
                    symbol=symbol,
                    strategy=strategy,
                    status="failed",
                    reason=str(exc),
                    proposal=proposal,
                )
            )
            errors.append(f"Order failed {symbol}: {exc}")
            continue

        if result.fetch_only:
            t_order_elapsed = time.perf_counter() - t_order_start
            logger.info("  [FETCH_ONLY] order skipped (IB_FETCH_ONLY=true) %s", _fmt_ms(t_order_elapsed))
            attempts.append(
                EntryAttempt(
                    symbol=symbol,
                    strategy=strategy,
                    status="skipped",
                    reason="fetch_only_mode",
                    proposal=proposal,
                )
            )
            continue

        order_ids = result.order_ids
        t_order_elapsed = time.perf_counter() - t_order_start
        logger.info("  order SUCCESS: ids=%s (%s)", order_ids, _fmt_ms(t_order_elapsed))

        # Create journal entry
        journal_entry = _build_journal_entry(candidate, proposal, order_ids)
        try:
            add_trade(journal_entry)
            logger.info("  journal entry added: %s", journal_entry.get("TradeID"))
        except Exception as exc:
            logger.error("  journal entry FAILED: %s", exc)
            errors.append(f"Journal failed {symbol}: {exc}")

        attempts.append(
            EntryAttempt(
                symbol=symbol,
                strategy=strategy,
                status="success",
                order_ids=order_ids,
                proposal=proposal,
                journal_entry=journal_entry,
            )
        )

    # Determine final status
    t_flow_elapsed = time.perf_counter() - t_flow_start
    successful = sum(1 for a in attempts if a.status == "success")
    failed = sum(1 for a in attempts if a.status == "failed")
    dry_run_count = sum(1 for a in attempts if a.status == "dry_run")

    if successful > 0 and failed == 0:
        status = "success"
    elif successful > 0 and failed > 0:
        status = "partial"
    elif failed > 0:
        status = "failed"
    else:
        status = "no_entries"

    logger.info("=" * 60)
    logger.info("[execute_entry_flow] DONE (%s) total: %s", status, _fmt_ms(t_flow_elapsed))
    logger.info("  candidates_found: %d", candidates_found)
    logger.info("  after_limits: %d", len(allowed_candidates))
    logger.info("  successful: %d", successful)
    logger.info("  failed: %d", failed)
    if dry_run_count > 0:
        logger.info("  dry_run: %d", dry_run_count)
    if errors:
        logger.info("  errors: %s", errors)
    logger.info("=" * 60)

    return EntryFlowResult(
        status=status,
        started_at=started_at,
        completed_at=datetime.now(),
        position_state=position_state,
        candidates_found=candidates_found,
        candidates_after_limits=len(allowed_candidates),
        attempts=tuple(attempts),
        errors=tuple(errors),
    )


__all__ = [
    "EntryAttempt",
    "EntryFlowConfig",
    "EntryFlowResult",
    "execute_entry_flow",
]
