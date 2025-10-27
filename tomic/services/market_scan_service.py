"""Service layer orchestrating market scan flows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..helpers.config import load_dte_range
from ..helpers.price_utils import ClosePriceSnapshot
from ..loader import load_strike_config
from ..logutils import logger
from ..utils import latest_atr
from .chain_processing import (
    ChainPreparationConfig,
    ChainPreparationError,
    PreparedChain,
    SpotResolution,
    load_and_prepare_chain,
    resolve_spot_price,
)
from .chain_sources import ChainSourceDecision
from .market_snapshot_service import ScanRow
from .portfolio_service import Candidate, PortfolioService
from .strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    StrategyPipeline,
    StrategyProposal,
    run as run_strategy_pipeline,
)


@dataclass(frozen=True)
class MarketScanRequest:
    """Minimal information required to evaluate a scan candidate."""

    symbol: str
    strategy: str
    metrics: Mapping[str, object]
    next_earnings: date | None = None


class MarketScanError(RuntimeError):
    """Raised when the market scan orchestration fails."""


class MarketScanService:
    """Coordinate option chain preparation, pipeline evaluation and ranking."""

    def __init__(
        self,
        pipeline: StrategyPipeline,
        portfolio_service: PortfolioService,
        *,
        interest_rate: float,
        strategy_config: Mapping[str, object] | None = None,
        chain_config: ChainPreparationConfig | None = None,
        refresh_spot_price: Callable[[str], float | None],
        load_spot_from_metrics: Callable[[Path, str], float | None],
        load_latest_close: Callable[[str], ClosePriceSnapshot],
        spot_from_chain: Callable[[Iterable[Mapping[str, object]]], float | None],
        atr_loader: Callable[[str], float | None] | None = None,
        apply_interpolation: bool = False,
        refresh_snapshot: Callable[..., Any] | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._portfolio = portfolio_service
        self._interest_rate = float(interest_rate)
        self._strategy_config = dict(strategy_config or {})
        self._chain_config = chain_config or ChainPreparationConfig()
        self._refresh_spot_price = refresh_spot_price
        self._load_spot_from_metrics = load_spot_from_metrics
        self._load_latest_close = load_latest_close
        self._spot_from_chain = spot_from_chain
        self._atr_loader = atr_loader or latest_atr
        self._apply_interpolation = apply_interpolation
        self._refresh_snapshot = refresh_snapshot

    def run_market_scan(
        self,
        requests: Sequence[MarketScanRequest],
        *,
        chain_source: Callable[[str], ChainSourceDecision | Path | None],
        top_n: int | None = None,
        refresh_quotes: bool = False,
    ) -> list[Candidate]:
        """Evaluate ``requests`` and return ranked :class:`Candidate` entries."""

        if not requests:
            return []

        grouped: dict[str, list[MarketScanRequest]] = {}
        for req in requests:
            symbol = req.symbol.upper()
            if not symbol or not req.strategy:
                continue
            grouped.setdefault(symbol, []).append(req)

        if not grouped:
            return []

        scan_rows: list[ScanRow] = []
        prepared_cache: dict[str, PreparedChain] = {}
        spot_cache: dict[str, SpotResolution] = {}
        atr_cache: dict[str, float] = {}

        for symbol, entries in grouped.items():
            prepared = prepared_cache.get(symbol)
            spot_resolution = spot_cache.get(symbol)
            if prepared is None:
                source_info = chain_source(symbol)
                if source_info is None:
                    logger.info("Skipping %s – no option chain source found", symbol)
                    continue
                if isinstance(source_info, ChainSourceDecision):
                    decision = source_info
                else:
                    chain_path = Path(source_info)
                    decision = ChainSourceDecision(
                        symbol=symbol,
                        source="polygon",
                        path=chain_path,
                        source_provenance=str(chain_path),
                        schema_version=None,
                    )
                try:
                    prepared = load_and_prepare_chain(
                        decision.path,
                        self._chain_config,
                        apply_interpolation=self._apply_interpolation,
                        source=decision.source,
                        source_provenance=decision.source_provenance,
                        schema_version=decision.schema_version,
                    )
                except ChainPreparationError as exc:
                    logger.warning("Failed to prepare chain for %s: %s", symbol, exc)
                    continue

                spot_resolution = resolve_spot_price(
                    symbol,
                    prepared,
                    refresh_quote=self._refresh_spot_price,
                    load_metrics_spot=self._load_spot_from_metrics,
                    load_latest_close=self._load_latest_close,
                    chain_spot_fallback=self._spot_from_chain,
                )
                if not spot_resolution.is_valid:
                    logger.warning("Skipping %s – unable to resolve valid spot price", symbol)
                    continue

                prepared_cache[symbol] = prepared
                spot_cache[symbol] = spot_resolution
                atr_cache[symbol] = float(self._atr_loader(symbol) or 0.0)
            else:
                spot_resolution = spot_cache[symbol]

            spot_price = float(spot_resolution.price or 0.0)
            atr_value = atr_cache.get(symbol, 0.0)

            close_snapshot = spot_resolution.close
            spot_as_of = close_snapshot.date if close_snapshot else None
            spot_timestamp = close_snapshot.fetched_at if close_snapshot else None
            spot_baseline = close_snapshot.baseline if close_snapshot else False
            spot_preview = spot_resolution.used_close_fallback and not spot_resolution.is_live

            for req in entries:
                dte_range = self._resolve_dte_range(req.strategy)
                try:
                    run_result: PipelineRunResult = run_strategy_pipeline(
                        self._pipeline,
                        symbol=symbol,
                        strategy=req.strategy,
                        option_chain=list(prepared.records),
                        spot_price=spot_price,
                        atr=atr_value,
                        config=self._strategy_config,
                        interest_rate=self._interest_rate,
                        dte_range=dte_range,
                        interactive_mode=False,
                        next_earnings=req.next_earnings,
                    )
                except PipelineRunError as exc:
                    raise MarketScanError(str(exc)) from exc

                if not run_result.filtered_chain:
                    logger.info("No contracts after DTE filter for %s/%s", symbol, req.strategy)
                    continue

                for proposal in run_result.proposals:
                    scan_rows.append(
                        ScanRow(
                            symbol=symbol,
                            strategy=req.strategy,
                            proposal=proposal,
                            metrics=req.metrics,
                            spot=spot_price,
                            next_earnings=req.next_earnings,
                            spot_preview=spot_preview,
                            spot_source=spot_resolution.source,
                            spot_as_of=spot_as_of,
                            spot_timestamp=spot_timestamp,
                            spot_baseline=spot_baseline,
                        )
                    )

        if not scan_rows:
            return []

        if refresh_quotes:
            refresher = self._refresh_snapshot
            if refresher is None:
                logger.warning(
                    "Refresh requested but no snapshot refresher configured; skipping"
                )
            else:
                for index, row in enumerate(scan_rows):
                    try:
                        result = refresher(
                            row.proposal,
                            symbol=row.symbol,
                            spot_price=row.spot,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning(
                            "Quote refresh failed for %s/%s: %s",
                            row.symbol,
                            row.strategy,
                            exc,
                            exc_info=True,
                        )
                        continue
                    proposal = getattr(result, "proposal", None)
                    if isinstance(proposal, StrategyProposal):
                        scan_rows[index] = replace(row, proposal=proposal)

        rules = {"top_n": top_n} if top_n is not None else None
        return self._portfolio.rank_candidates(scan_rows, rules)

    def _resolve_dte_range(self, strategy: str) -> tuple[int, int]:
        return load_dte_range(
            strategy,
            self._strategy_config,
            loader=load_strike_config,
        )


__all__ = [
    "MarketScanError",
    "MarketScanRequest",
    "MarketScanService",
]

