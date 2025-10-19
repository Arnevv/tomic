from __future__ import annotations

"""Service for refreshing strategy pipeline rejections."""

import math
import time
from concurrent.futures import Executor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Mapping, Sequence

from ..logutils import logger
from .ib_marketdata import SnapshotResult, fetch_quote_snapshot
from .proposal_details import ProposalCore, build_proposal_core
from .strategy_pipeline import StrategyProposal
from ._config import cfg_value

ProposalBuilder = Callable[[Mapping[str, Any]], StrategyProposal | None]
SnapshotFetcher = Callable[..., SnapshotResult]
SortKeyCallable = Callable[[StrategyProposal | None, Mapping[str, Any]], tuple[Any, ...]]


ORIGINAL_INDEX_KEY = "__pipeline_refresh_index__"


@dataclass(frozen=True)
class RefreshContext:
    """Execution context for a pipeline refresh run."""

    trace_id: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class RefreshParams:
    """Configuration for :func:`refresh_pipeline`."""

    entries: Sequence[Mapping[str, Any]]
    criteria: Mapping[str, Any] | None = None
    spot_price: float | None = None
    interest_rate: float | None = None
    timeout: float | None = None
    max_attempts: int | None = None
    retry_delay: float | None = None
    parallel: bool | None = None
    max_workers: int | None = None
    executor: Executor | None = None
    fetch_snapshot: SnapshotFetcher | None = None
    proposal_builder: ProposalBuilder | None = None
    sort_key: SortKeyCallable | None = None
    throttle_inflight: int | None = None
    throttle_interval: float | None = None


@dataclass(frozen=True)
class RefreshSource:
    """Information about the source entry of a refresh result."""

    index: int
    entry: Mapping[str, Any]
    symbol: str | None = None


@dataclass(frozen=True)
class Proposal:
    """Accepted proposal after refreshing via the pipeline."""

    proposal: StrategyProposal
    source: RefreshSource
    reasons: list[Any] = field(default_factory=list)
    missing_quotes: list[str] = field(default_factory=list)
    core: ProposalCore | None = None
    accepted: bool | None = True


@dataclass(frozen=True)
class Rejection:
    """Rejected proposal (or failure) after pipeline refresh."""

    source: RefreshSource
    proposal: StrategyProposal | None = None
    reasons: list[Any] = field(default_factory=list)
    missing_quotes: list[str] = field(default_factory=list)
    error: Exception | None = None
    attempts: int = 0
    core: ProposalCore | None = None
    accepted: bool | None = False


@dataclass(frozen=True)
class PipelineStats:
    """Aggregated statistics for a refresh run."""

    total: int
    accepted: int
    rejected: int
    failed: int
    duration: float
    attempts: int
    retries: int


@dataclass(frozen=True)
class RefreshResult:
    """Outcome of :func:`refresh_pipeline`."""

    accepted: list[Proposal]
    rejections: list[Rejection]
    stats: PipelineStats


class PipelineError(Exception):
    """Base error for refresh pipeline issues."""


class PipelineTimeout(PipelineError):
    """Raised when the refresh operation times out."""


class IncompleteData(PipelineError):
    """Raised when the input entry is missing data to build a proposal."""


class UpstreamError(PipelineError):
    """Raised for unexpected upstream failures during refresh."""


@dataclass
class _ProcessingOutcome:
    index: int
    entry: Mapping[str, Any]
    proposal: StrategyProposal | None
    snapshot: SnapshotResult | None
    attempts: int
    error: PipelineError | None


class RefreshThrottle:
    """Coordinator enforcing shared throttling across refresh attempts."""

    def __init__(self, max_inflight: int | None, min_interval: float) -> None:
        self.max_inflight = max_inflight if max_inflight and max_inflight > 0 else None
        self.min_interval = max(0.0, float(min_interval))
        self._semaphore = (
            BoundedSemaphore(self.max_inflight)
            if isinstance(self.max_inflight, int)
            else None
        )
        self._lock = Lock()
        self._last_timestamp = 0.0

    def __enter__(self) -> "RefreshThrottle":
        if self._semaphore is not None:
            self._semaphore.acquire()
        self._throttle()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._semaphore is not None:
            self._semaphore.release()

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_timestamp)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last_timestamp = now

    def describe(self) -> str:
        inflight = self.max_inflight if self.max_inflight is not None else "∞"
        return f"inflight={inflight} interval={self.min_interval:.2f}s"


@dataclass(frozen=True)
class RefreshRuntimeSettings:
    timeout: float
    max_attempts: int
    retry_delay: float
    parallel: bool
    max_workers: int | None
    throttle: RefreshThrottle


def refresh_pipeline(
    ctx: RefreshContext | None,
    *,
    params: RefreshParams,
) -> RefreshResult:
    """Refresh proposals for rejected entries using IB market data.

    Parameters
    ----------
    ctx:
        Context metadata for logging (trace identifier, label).
    params:
        Configuration describing the entries to refresh and runtime settings.
    """

    context = ctx or RefreshContext()
    entries = tuple(params.entries or [])
    if not entries:
        stats = PipelineStats(
            total=0,
            accepted=0,
            rejected=0,
            failed=0,
            duration=0.0,
            attempts=0,
            retries=0,
        )
        return RefreshResult(accepted=[], rejections=[], stats=stats)

    builder = params.proposal_builder or build_proposal_from_entry
    fetcher = params.fetch_snapshot or fetch_quote_snapshot
    runtime = _resolve_runtime_settings(params)
    use_parallel = (runtime.parallel or params.executor is not None) and len(entries) > 1

    logger.info(
        "refresh_pipeline start total=%d trace_id=%s attempts=%d retry=%.2fs parallel=%s throttle=%s",
        len(entries),
        context.trace_id,
        runtime.max_attempts,
        runtime.retry_delay,
        use_parallel,
        runtime.throttle.describe(),
    )

    start = time.monotonic()
    outcomes: list[_ProcessingOutcome] = []

    if use_parallel:
        executor = params.executor
        owns_executor = False
        if executor is None:
            max_workers = runtime.max_workers or min(32, len(entries))
            executor = ThreadPoolExecutor(max_workers=max_workers)
            owns_executor = True
        try:
            futures = [
                executor.submit(
                    _process_entry,
                    index,
                    entry,
                    builder,
                    fetcher,
                    runtime.timeout,
                    runtime.max_attempts,
                    runtime.retry_delay,
                    runtime.throttle,
                    params,
                )
                for index, entry in enumerate(entries)
            ]
            for future in as_completed(futures):
                outcomes.append(future.result())
        finally:
            if owns_executor and executor is not None:
                executor.shutdown(wait=True)
    else:
        for index, entry in enumerate(entries):
            outcomes.append(
                _process_entry(
                    index,
                    entry,
                    builder,
                    fetcher,
                    runtime.timeout,
                    runtime.max_attempts,
                    runtime.retry_delay,
                    runtime.throttle,
                    params,
                )
            )

    accepted_items: list[Proposal] = []
    rejected_items: list[Rejection] = []
    attempts_total = 0
    attempts_with_work = 0

    sorter = params.sort_key or _default_sort_key

    for outcome in outcomes:
        attempts_total += outcome.attempts
        if outcome.attempts:
            attempts_with_work += 1
        entry_index = _entry_index(outcome.index, outcome.entry)
        symbol = _infer_symbol(outcome.proposal, outcome.entry)
        source = RefreshSource(index=entry_index, entry=outcome.entry, symbol=symbol)

        if outcome.snapshot is not None and outcome.error is None:
            snapshot = outcome.snapshot
            reasons = list(snapshot.reasons)
            missing = list(snapshot.missing_quotes)
            if snapshot.accepted:
                accepted_items.append(
                    Proposal(
                        proposal=snapshot.proposal,
                        source=source,
                        reasons=reasons,
                        missing_quotes=missing,
                        core=build_proposal_core(
                            snapshot.proposal,
                            symbol=symbol,
                            entry=outcome.entry,
                        ),
                    )
                )
            else:
                rejected_items.append(
                    Rejection(
                        source=source,
                        proposal=snapshot.proposal,
                        reasons=reasons,
                        missing_quotes=missing,
                        attempts=outcome.attempts,
                        core=build_proposal_core(
                            snapshot.proposal,
                            symbol=symbol,
                            entry=outcome.entry,
                        ),
                    )
                )
        else:
            rejection_core = None
            if isinstance(outcome.proposal, StrategyProposal):
                rejection_core = build_proposal_core(
                    outcome.proposal,
                    symbol=symbol,
                    entry=outcome.entry,
                )
            rejected_items.append(
                Rejection(
                    source=source,
                    proposal=outcome.proposal,
                    error=outcome.error,
                    attempts=outcome.attempts,
                    core=rejection_core,
                )
            )

    accepted_items.sort(key=lambda item: sorter(item.proposal, item.source.entry))
    rejected_items.sort(key=lambda item: sorter(item.proposal, item.source.entry))

    duration = time.monotonic() - start
    failed_count = sum(1 for item in rejected_items if item.error is not None)
    retries = max(0, attempts_total - attempts_with_work)
    stats = PipelineStats(
        total=len(entries),
        accepted=len(accepted_items),
        rejected=len(rejected_items),
        failed=failed_count,
        duration=duration,
        attempts=attempts_total,
        retries=retries,
    )

    logger.info(
        "refresh_pipeline done accepted=%d rejected=%d failed=%d duration=%.3fs trace_id=%s",
        stats.accepted,
        stats.rejected,
        stats.failed,
        stats.duration,
        context.trace_id,
    )

    return RefreshResult(accepted=accepted_items, rejections=rejected_items, stats=stats)


def build_proposal_from_entry(entry: Mapping[str, Any]) -> StrategyProposal | None:
    """Reconstruct :class:`StrategyProposal` from a rejection entry."""

    metrics = entry.get("metrics") if isinstance(entry, Mapping) else None
    legs = entry.get("legs") if isinstance(entry, Mapping) else None
    strategy = entry.get("strategy") if isinstance(entry, Mapping) else None

    if not isinstance(strategy, str) or not strategy:
        return None
    if not isinstance(metrics, Mapping):
        return None
    if not isinstance(legs, Sequence):
        return None

    normalized_legs: list[dict[str, Any]] = []
    for leg in legs:
        if isinstance(leg, Mapping):
            normalized_legs.append(dict(leg))
    if not normalized_legs:
        return None

    symbol_hint = _extract_entry_symbol(entry)
    if symbol_hint:
        for leg in normalized_legs:
            if not any(
                leg.get(key)
                for key in ("symbol", "underlying", "ticker", "root", "root_symbol")
            ):
                leg["symbol"] = symbol_hint

    allowed_fields = {field.name for field in fields(StrategyProposal) if field.init}
    allowed_fields.discard("strategy")
    allowed_fields.discard("legs")

    proposal_kwargs: dict[str, Any] = {}
    for key, value in metrics.items():
        if key in allowed_fields:
            proposal_kwargs[key] = value

    return StrategyProposal(strategy=strategy, legs=normalized_legs, **proposal_kwargs)


def _coerce_int(value: Any) -> int | None:
    try:
        if value in {None, ""}:
            return None
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _resolve_runtime_settings(params: RefreshParams) -> RefreshRuntimeSettings:
    timeout_cfg = cfg_value("MARKET_DATA_TIMEOUT", 15.0)
    timeout = float(params.timeout if params.timeout is not None else timeout_cfg)

    attempts_cfg = cfg_value("PIPELINE_REFRESH_ATTEMPTS", 1)
    attempts_val = params.max_attempts if params.max_attempts not in {None, 0} else attempts_cfg
    try:
        max_attempts = max(1, int(attempts_val))
    except Exception:
        max_attempts = 1

    retry_cfg = cfg_value("PIPELINE_REFRESH_RETRY_DELAY", 0.0)
    retry_val = params.retry_delay if params.retry_delay is not None else retry_cfg
    try:
        retry_delay = max(0.0, float(retry_val))
    except Exception:
        retry_delay = 0.0

    parallel_cfg = bool(cfg_value("PIPELINE_REFRESH_PARALLEL", False))
    parallel = bool(params.parallel) if params.parallel is not None else parallel_cfg

    if params.max_workers is not None:
        max_workers = _coerce_int(params.max_workers)
    else:
        max_workers = _coerce_int(cfg_value("PIPELINE_REFRESH_MAX_WORKERS", None))

    inflight = params.throttle_inflight
    if inflight is None:
        inflight = _coerce_int(cfg_value("PIPELINE_REFRESH_MAX_INFLIGHT", None))

    interval_raw = params.throttle_interval
    if interval_raw is None:
        interval_raw = cfg_value("PIPELINE_REFRESH_MIN_INTERVAL", 0.0)
    try:
        interval = max(0.0, float(interval_raw))
    except Exception:
        interval = 0.0

    throttle = RefreshThrottle(inflight, interval)
    return RefreshRuntimeSettings(
        timeout=timeout,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
        parallel=parallel,
        max_workers=max_workers,
        throttle=throttle,
    )


def _process_entry(
    index: int,
    entry: Mapping[str, Any],
    builder: ProposalBuilder,
    fetcher: SnapshotFetcher,
    timeout: float,
    max_attempts: int,
    retry_delay: float,
    throttle: RefreshThrottle,
    params: RefreshParams,
) -> _ProcessingOutcome:
    try:
        proposal = builder(entry)
    except Exception as exc:  # pragma: no cover - defensive
        error = _map_exception(exc)
        return _ProcessingOutcome(index, entry, None, None, 0, error)

    if proposal is None:
        return _ProcessingOutcome(
            index,
            entry,
            None,
            None,
            0,
            IncompleteData("entry lacks proposal data"),
        )

    attempts = 0
    last_error: PipelineError | None = None

    while attempts < max_attempts:
        attempts += 1
        try:
            with throttle:
                snapshot = fetcher(
                    proposal,
                    criteria=params.criteria,
                    spot_price=params.spot_price,
                    interest_rate=params.interest_rate,
                    timeout=timeout,
                )
            return _ProcessingOutcome(index, entry, snapshot.proposal, snapshot, attempts, None)
        except Exception as exc:  # pragma: no cover - network dependent
            last_error = _map_exception(exc)
            if attempts < max_attempts and retry_delay:
                time.sleep(retry_delay)

    return _ProcessingOutcome(index, entry, proposal, None, attempts, last_error)


def _map_exception(exc: Exception) -> PipelineError:
    if isinstance(exc, PipelineError):
        return exc
    if isinstance(exc, TimeoutError):
        return PipelineTimeout(str(exc))
    if getattr(exc, "timeout", False):
        return PipelineTimeout(str(exc))
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return IncompleteData(str(exc))
    return UpstreamError(str(exc))


def _entry_index(default_index: int, entry: Mapping[str, Any]) -> int:
    raw = entry.get(ORIGINAL_INDEX_KEY)
    try:
        return int(raw)
    except Exception:
        return default_index


def _infer_symbol(
    proposal: StrategyProposal | None,
    entry: Mapping[str, Any],
) -> str | None:
    if proposal and proposal.legs:
        for leg in proposal.legs:
            if not isinstance(leg, Mapping):
                continue
            for key in ("symbol", "underlying", "ticker", "root", "root_symbol"):
                value = leg.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().upper()
    return _extract_entry_symbol(entry)


def _extract_entry_symbol(entry: Mapping[str, Any]) -> str | None:
    symbol = entry.get("symbol") if isinstance(entry, Mapping) else None
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip().upper()
    meta = entry.get("meta") if isinstance(entry, Mapping) else None
    if isinstance(meta, Mapping):
        raw_symbol = meta.get("symbol") or meta.get("underlying")
        if isinstance(raw_symbol, str) and raw_symbol.strip():
            return raw_symbol.strip().upper()
    return None


def _default_sort_key(
    proposal: StrategyProposal | None,
    entry: Mapping[str, Any],
) -> tuple[Any, ...]:
    symbol = _infer_symbol(proposal, entry) or ""
    expiry = _first_leg_value(proposal, entry, "expiry") or ""
    strike = _first_leg_value(proposal, entry, "strike")
    try:
        strike_val = float(strike) if strike is not None else math.inf
    except Exception:
        strike_val = math.inf
    strategy = ""
    if proposal and proposal.strategy:
        strategy = proposal.strategy
    else:
        raw_strategy = entry.get("strategy") if isinstance(entry, Mapping) else None
        if isinstance(raw_strategy, str):
            strategy = raw_strategy
    return (symbol, str(expiry), strike_val, strategy)


def _first_leg_value(
    proposal: StrategyProposal | None,
    entry: Mapping[str, Any],
    key: str,
) -> Any:
    if proposal and proposal.legs:
        leg = proposal.legs[0]
        if isinstance(leg, Mapping):
            value = leg.get(key)
            if value is not None:
                return value
    legs = entry.get("legs") if isinstance(entry, Mapping) else None
    if isinstance(legs, Sequence) and legs:
        first = legs[0]
        if isinstance(first, Mapping):
            return first.get(key)
    return None


__all__ = [
    "PipelineError",
    "PipelineStats",
    "PipelineTimeout",
    "Proposal",
    "RefreshContext",
    "RefreshParams",
    "RefreshResult",
    "RefreshSource",
    "Rejection",
    "build_proposal_from_entry",
    "refresh_pipeline",
    "IncompleteData",
    "UpstreamError",
    "ORIGINAL_INDEX_KEY",
]

