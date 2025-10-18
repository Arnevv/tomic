"""Domain services for portfolio control panel use-cases.

This module contains pure application logic that can be reused by the
command line UI or other adapters. None of the functions perform any
user interaction; instead they return structured results that the UI can
render or act upon.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, TYPE_CHECKING

from tomic import config as cfg
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.criteria import load_criteria
from tomic.exports import (
    export_proposal_csv,
    export_proposal_json,
    proposal_journal_text,
)
from tomic.helpers.price_utils import _load_latest_close
from tomic.logutils import capture_combo_evaluations, logger, summarize_evaluations
from tomic.reporting import EvaluationSummary
from tomic.services.ib_marketdata import SnapshotResult, fetch_quote_snapshot
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tomic.services.pipeline_refresh import RefreshProposal, RefreshSource
from tomic.services.proposal_details import ProposalVM, build_proposal_core, build_proposal_viewmodel
from tomic.services.strategy_pipeline import StrategyProposal

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from tomic.cli.controlpanel_session import ControlPanelSession


POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))


class SessionProtocol(Protocol):
    """Minimal protocol representing the session interactions we rely on."""

    symbol: str | None
    strategy: str | None
    next_earnings: date | None
    days_until_earnings: int | None
    spot_price: float | None

    def clear_combo_results(self) -> None: ...

    def set_combo_results(
        self,
        combos: Sequence[Mapping[str, Any]],
        summary: EvaluationSummary | None,
    ) -> None: ...


@dataclass(frozen=True)
class ProposalPresentation:
    """Structured information describing a strategy proposal."""

    proposal: StrategyProposal
    symbol: str | None
    candidate: RefreshProposal
    viewmodel: ProposalVM
    journal_text: str
    fetch_only_mode: bool
    refresh_result: SnapshotResult | None = None

    @property
    def acceptance_failed(self) -> bool:
        return self.viewmodel.accepted is False

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self.viewmodel.warnings)

    @property
    def reasons(self) -> tuple[Any, ...]:
        return tuple(self.viewmodel.reasons)

    @property
    def has_missing_edge(self) -> bool:
        return bool(getattr(self.viewmodel, "has_missing_edge", False))


@dataclass(frozen=True)
class OrderSubmissionResult:
    """Outcome of preparing (and optionally sending) an IB order."""

    log_path: Path
    order_ids: tuple[int, ...]
    client_id: int
    fetch_only: bool


class OrderSubmissionError(RuntimeError):
    """Raised when preparing or sending an order fails."""


def capture_strategy_generation(
    session: SessionProtocol,
    generator,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute ``generator`` and persist the captured combo evaluation state."""

    session.clear_combo_results()
    with capture_combo_evaluations() as captured:
        try:
            result = generator(*args, **kwargs)
        finally:
            summary = summarize_evaluations(captured)
            session.set_combo_results(captured, summary)
    return result


def refresh_proposal_from_ib(
    proposal: StrategyProposal,
    *,
    symbol: str | None,
    spot_price: float | None,
    timeout: float | None = None,
) -> SnapshotResult:
    """Fetch updated market data for ``proposal`` from IB."""

    criteria_cfg = load_criteria()
    if timeout is None:
        timeout = float(cfg.get("MARKET_DATA_TIMEOUT", 15))
    try:
        return fetch_quote_snapshot(
            proposal,
            criteria=criteria_cfg,
            spot_price=spot_price if isinstance(spot_price, (int, float)) else None,
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - passthrough for UI handling
        logger.exception("IB market data refresh failed: %s", exc)
        raise


def build_proposal_presentation(
    session: SessionProtocol,
    proposal: StrategyProposal,
    *,
    refresh_result: SnapshotResult | None = None,
) -> ProposalPresentation:
    """Return presentation metadata for ``proposal`` based on the session state."""

    symbol = None
    if proposal.legs:
        leg_symbol = proposal.legs[0].get("symbol")
        if isinstance(leg_symbol, str) and leg_symbol.strip():
            symbol = leg_symbol.strip()
    if isinstance(session.symbol, str) and session.symbol.strip():
        symbol = session.symbol.strip()
    if symbol:
        symbol = symbol.upper()

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

    strategy_label = None
    if isinstance(session.strategy, str) and session.strategy.strip():
        strategy_label = session.strategy.strip()
    elif hasattr(proposal, "strategy") and isinstance(proposal.strategy, str):
        strategy_label = proposal.strategy

    journal_text = proposal_journal_text(
        session,
        proposal,
        symbol=symbol,
        strategy=strategy_label,
    )

    fetch_only_mode = bool(cfg.get("IB_FETCH_ONLY", False))

    return ProposalPresentation(
        proposal=proposal,
        symbol=symbol,
        candidate=candidate,
        viewmodel=vm,
        journal_text=journal_text,
        fetch_only_mode=fetch_only_mode,
        refresh_result=refresh_result,
    )


def rejection_messages(vm: ProposalVM) -> tuple[str, ...]:
    """Return normalized rejection messages for presentation layers."""

    messages: list[str] = []
    for detail in getattr(vm, "reasons", ()):  # pragma: no branch - small loop
        msg = getattr(detail, "message", None) or getattr(detail, "code", None)
        if not msg:
            msg = str(detail)
        messages.append(str(msg))
    return tuple(messages)


def prepare_order(
    proposal: StrategyProposal,
    *,
    symbol: str,
    account: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
) -> tuple[Path, tuple[int, ...], int, bool]:
    """Prepare the order log and optionally send instructions to IB."""

    account = account or str(cfg.get("IB_ACCOUNT_ALIAS") or "") or None
    order_type = order_type or str(cfg.get("DEFAULT_ORDER_TYPE", "LMT"))
    tif = tif or str(cfg.get("DEFAULT_TIME_IN_FORCE", "DAY"))

    try:
        instructions = prepare_order_instructions(
            proposal,
            symbol=symbol,
            account=account,
            order_type=order_type,
            tif=tif,
        )
    except Exception as exc:  # pragma: no cover - validation handled by caller
        raise OrderSubmissionError(str(exc)) from exc

    export_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    log_path = OrderSubmissionService.dump_order_log(instructions, directory=export_dir)

    fetch_only = bool(cfg.get("IB_FETCH_ONLY", False))
    if fetch_only:
        return log_path, tuple(), int(cfg.get("IB_CLIENT_ID", 100)), True

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
    except Exception as exc:  # pragma: no cover - network/IB errors
        raise OrderSubmissionError(str(exc)) from exc
    finally:
        if app is not None:
            try:
                app.disconnect()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.debug("Problem while closing IB connection", exc_info=True)

    return log_path, tuple(order_ids), client_id, False


def submit_order(
    proposal: StrategyProposal,
    *,
    symbol: str,
    account: str | None = None,
    order_type: str | None = None,
    tif: str | None = None,
) -> OrderSubmissionResult:
    """Public interface wrapping :func:`prepare_order`."""

    log_path, order_ids, client_id, fetch_only = prepare_order(
        proposal,
        symbol=symbol,
        account=account,
        order_type=order_type,
        tif=tif,
    )
    return OrderSubmissionResult(
        log_path=log_path,
        order_ids=order_ids,
        client_id=client_id,
        fetch_only=fetch_only,
    )


def save_trades(session: SessionProtocol, trades: Sequence[Mapping[str, Any]]) -> Path:
    """Persist evaluated trades as CSV and return the generated path."""

    if not trades:
        raise ValueError("No trades to save")

    symbol = str(session.symbol or "SYMB")
    strat = str(session.strategy or "strategy").replace(" ", "_")
    expiry = str(trades[0].get("expiry", "")) if trades else ""
    base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = base / f"trade_candidates_{symbol}_{strat}_{expiry}_{ts}.csv"
    fieldnames = [k for k in trades[0].keys() if k not in {"rom", "ev"}]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in trades:
            out: dict[str, Any] = {}
            for key in fieldnames:
                value = row.get(key)
                if key in {"pos", "rom", "ev", "edge", "mid", "model", "delta", "margin"}:
                    try:
                        out[key] = f"{float(value):.2f}"
                    except Exception:
                        out[key] = ""
                else:
                    out[key] = value
            writer.writerow(out)
    return path


def export_proposal_to_csv(
    session: SessionProtocol, proposal: StrategyProposal
) -> Path:
    """Persist ``proposal`` to CSV using the configured export location."""

    return export_proposal_csv(session, proposal)


def export_proposal_to_json(
    session: SessionProtocol, proposal: StrategyProposal
) -> Path:
    """Persist ``proposal`` to JSON using the configured export location."""

    return export_proposal_json(session, proposal)


def record_portfolio_timestamp(timestamp: datetime | None = None) -> None:
    """Store ``timestamp`` (defaults to now) as the latest portfolio update."""

    ts = (timestamp or datetime.now()).isoformat()
    META_FILE.write_text(json.dumps({"last_update": ts}))


def read_portfolio_timestamp() -> str | None:
    """Return the previously recorded portfolio timestamp."""

    if not META_FILE.exists():
        return None
    try:
        data = json.loads(META_FILE.read_text())
    except Exception:
        return None
    return data.get("last_update")


def compute_saved_portfolio_greeks() -> Mapping[str, float]:
    """Return Greeks computed from the stored portfolio positions."""

    if not POSITIONS_FILE.exists():
        return {}
    try:
        positions = json.loads(POSITIONS_FILE.read_text())
    except Exception:
        return {}
    portfolio = compute_portfolio_greeks(positions)
    return portfolio


def load_latest_close(symbol: str) -> tuple[float | None, Any]:
    """Expose price history helper used by the UI for dependency injection."""

    return _load_latest_close(symbol)


__all__ = [
    "ACCOUNT_INFO_FILE",
    "META_FILE",
    "POSITIONS_FILE",
    "OrderSubmissionError",
    "OrderSubmissionResult",
    "ProposalPresentation",
    "SessionProtocol",
    "build_proposal_presentation",
    "capture_strategy_generation",
    "compute_saved_portfolio_greeks",
    "export_proposal_to_csv",
    "export_proposal_to_json",
    "load_latest_close",
    "prepare_order",
    "read_portfolio_timestamp",
    "record_portfolio_timestamp",
    "refresh_proposal_from_ib",
    "rejection_messages",
    "save_trades",
    "submit_order",
]
