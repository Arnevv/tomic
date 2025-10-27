"""Services for preparing and evaluating option chains.

This module contains pure helper functions that handle the heavy lifting of
loading CSV based option chains, normalising the records and evaluating them
through the strategy pipeline. The functions intentionally avoid any user
interaction so they can be reused from the CLI, automated jobs or tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd

from tomic import config as cfg
from tomic.helpers.config import load_dte_range
from tomic.helpers.csv_norm import dataframe_to_records, normalize_chain_dataframe
from tomic.helpers.price_utils import ClosePriceSnapshot
from tomic.helpers.interpolation import interpolate_missing_fields
from tomic.helpers.quality_check import calculate_csv_quality
from tomic.loader import load_strike_config
from tomic.logutils import logger
from tomic.services.strategy_pipeline import (
    PipelineRunError,
    PipelineRunResult,
    RejectionSummary,
    StrategyContext,
    StrategyPipeline,
    StrategyProposal,
    run as run_strategy_pipeline,
)
from tomic.utils import normalize_leg


class ChainPreparationError(RuntimeError):
    """Raised when a chain cannot be loaded or processed."""


@dataclass(slots=True)
class ChainPreparationConfig:
    """Configuration for loading and normalising a CSV option chain."""

    min_quality: float = 70.0
    columns_to_normalize: Sequence[str] = (
        "bid",
        "ask",
        "close",
        "iv",
        "delta",
        "gamma",
        "vega",
        "theta",
        "mid",
    )
    interpolation_suffix: str = "_interpolated"
    date_format: str = "%Y-%m-%d"
    date_columns: Sequence[str] = ("expiry",)
    column_aliases: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_app_config(cls) -> "ChainPreparationConfig":
        """Build configuration using application level settings."""

        min_quality = float(cfg.get("CSV_MIN_QUALITY", 70))
        suffix = str(cfg.get("CHAIN_INTERPOLATION_SUFFIX", "_interpolated"))
        return cls(min_quality=min_quality, interpolation_suffix=suffix)


@dataclass(slots=True)
class PreparedChain:
    """Result of loading and preparing an option chain."""

    path: Path
    source_path: Path
    dataframe: pd.DataFrame
    records: list[dict]
    quality: float
    interpolation_applied: bool = False
    source: str | None = None
    source_provenance: str | None = None
    schema_version: str | None = None


@dataclass(slots=True)
class ChainEvaluationConfig:
    """Configuration for evaluating a prepared option chain."""

    symbol: str
    strategy: str
    strategy_config: Mapping[str, object]
    interest_rate: float
    export_dir: Path
    dte_range: tuple[int, int]
    spot_price: float
    atr: float
    interactive_mode: bool = True
    debug_filename: str = "PEP_debugfilter.csv"

    @classmethod
    def from_app_config(
        cls,
        *,
        symbol: str,
        strategy: str,
        spot_price: float,
        atr: float,
    ) -> "ChainEvaluationConfig":
        """Create configuration using global application settings."""

        config_data: Mapping[str, object] = cfg.get("STRATEGY_CONFIG") or {}
        interest_rate = float(cfg.get("INTEREST_RATE", 0.05))
        export_dir = Path(cfg.get("EXPORT_DIR", "exports"))
        dte_tuple = load_dte_range(
            strategy,
            config_data,
            loader=load_strike_config,
        )

        return cls(
            symbol=symbol,
            strategy=strategy,
            strategy_config=config_data,
            interest_rate=interest_rate,
            export_dir=export_dir,
            dte_range=dte_tuple,
            spot_price=spot_price,
            atr=atr,
        )


@dataclass(slots=True)
class ChainEvaluationResult:
    """Structured result of evaluating a prepared chain."""

    context: StrategyContext
    filtered_chain: list[dict]
    proposals: list[StrategyProposal]
    summary: RejectionSummary
    filter_preview: RejectionSummary
    evaluated_trades: list[dict]
    expiry_counts_before: dict[str, int] = field(default_factory=dict)
    expiry_counts_after: dict[str, int] = field(default_factory=dict)
    skipped_expiries: tuple[str, ...] = ()


def load_and_prepare_chain(
    path: Path,
    config: ChainPreparationConfig,
    *,
    apply_interpolation: bool = False,
    source: str | None = None,
    source_provenance: str | None = None,
    schema_version: str | None = None,
) -> PreparedChain:
    """Load, normalise and optionally interpolate an option chain CSV."""

    if not path.exists():
        raise ChainPreparationError(f"Chain-bestand ontbreekt: {path}")

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - depends on pandas internals
        raise ChainPreparationError(f"Fout bij laden van chain: {exc}") from exc

    df = normalize_chain_dataframe(
        df,
        decimal_columns=config.columns_to_normalize,
        column_aliases=config.column_aliases,
        date_columns=config.date_columns,
        date_format=config.date_format,
    )

    quality = calculate_csv_quality(df)
    source_path = path
    interpolated_path = path
    interpolation_applied = False

    if apply_interpolation:
        logger.info(
            "Interpolating missing delta/iv values using linear (delta) and spline (iv)"
        )
        df = interpolate_missing_fields(df)
        quality = calculate_csv_quality(df)
        interpolated_path = path.with_name(path.stem + config.interpolation_suffix + path.suffix)
        df.to_csv(interpolated_path, index=False)
        interpolation_applied = True
        logger.info("Interpolation completed successfully")
        logger.info(f"Interpolated CSV saved to {interpolated_path}")

    records = [normalize_leg(rec) for rec in dataframe_to_records(df)]

    logger.info(f"Loaded {len(df)} rows from {path}")
    logger.info(f"CSV loaded from {path} with quality {quality:.1f}%")

    return PreparedChain(
        path=interpolated_path,
        source_path=source_path,
        dataframe=df,
        records=records,
        quality=quality,
        interpolation_applied=interpolation_applied,
        source=source,
        source_provenance=source_provenance,
        schema_version=schema_version,
    )


@dataclass(frozen=True)
class SpotResolution:
    """Structured result describing how a spot price was resolved."""

    price: float | None
    source: str
    is_live: bool
    used_close_fallback: bool
    close: ClosePriceSnapshot | None = None

    @property
    def is_valid(self) -> bool:
        return isinstance(self.price, (int, float)) and self.price > 0


def resolve_spot_price(
    symbol: str,
    prepared: PreparedChain,
    *,
    refresh_quote: Callable[[str], float | None],
    load_metrics_spot: Callable[[Path, str], float | None],
    load_latest_close: Callable[[str], ClosePriceSnapshot],
    chain_spot_fallback: Callable[[Iterable[dict]], float | None],
) -> SpotResolution:
    """Resolve the best spot price using a series of fallbacks."""

    close_snapshot: ClosePriceSnapshot | None = None

    def _latest_close() -> float | None:
        nonlocal close_snapshot
        close_snapshot = load_latest_close(symbol)
        if isinstance(close_snapshot, ClosePriceSnapshot):
            return close_snapshot.price
        price, _date = close_snapshot if isinstance(close_snapshot, tuple) else (None, None)
        try:
            return float(price) if isinstance(price, (int, float)) else None
        except Exception:  # pragma: no cover - defensive conversion
            return None

    candidates: list[tuple[str, bool, Callable[[], float | None]]] = [
        ("live", True, lambda: refresh_quote(symbol)),
        (
            "metrics",
            False,
            lambda: load_metrics_spot(prepared.source_path.parent, symbol),
        ),
        ("close", False, _latest_close),
        ("chain", False, lambda: chain_spot_fallback(prepared.records)),
    ]

    for label, is_live, getter in candidates:
        try:
            value = getter()
        except Exception:  # pragma: no cover - defensive fall-back
            continue
        if not isinstance(value, (int, float)) or value <= 0:
            continue

        used_close = label == "close"
        if used_close and close_snapshot is None:
            close_snapshot = load_latest_close(symbol)

        if used_close:
            baseline_txt = " (baseline)" if close_snapshot and close_snapshot.baseline else ""
            logger.info(
                "📉 %s: using close fallback at %.2f%s",
                symbol,
                float(value),
                baseline_txt,
            )
        elif is_live:
            logger.info("⚡ %s: live spot price %.2f", symbol, float(value))
        else:
            logger.info("ℹ️ %s: using cached spot %.2f from %s", symbol, float(value), label)

        return SpotResolution(
            price=float(value),
            source=label,
            is_live=is_live,
            used_close_fallback=used_close,
            close=close_snapshot if isinstance(close_snapshot, ClosePriceSnapshot) else None,
        )

    return SpotResolution(
        price=None,
        source="unresolved",
        is_live=False,
        used_close_fallback=False,
        close=close_snapshot if isinstance(close_snapshot, ClosePriceSnapshot) else None,
    )


def _count_by_expiry(records: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        exp = rec.get("expiry")
        if not isinstance(exp, str) or not exp:
            continue
        counts[exp] = counts.get(exp, 0) + 1
    return counts


def evaluate_chain(
    prepared: PreparedChain,
    pipeline: StrategyPipeline,
    config: ChainEvaluationConfig,
) -> ChainEvaluationResult:
    """Evaluate a prepared option chain using the configured pipeline."""

    expiry_counts_before = _count_by_expiry(prepared.records)
    try:
        run_result: PipelineRunResult = run_strategy_pipeline(
            pipeline,
            symbol=config.symbol,
            strategy=config.strategy,
            option_chain=list(prepared.records),
            spot_price=float(config.spot_price or 0.0),
            atr=config.atr,
            config=config.strategy_config or {},
            interest_rate=config.interest_rate,
            dte_range=config.dte_range,
            interactive_mode=config.interactive_mode,
            debug_path=config.export_dir / config.debug_filename,
        )
    except PipelineRunError as exc:
        raise ChainPreparationError(str(exc)) from exc

    filtered_chain = run_result.filtered_chain
    expiry_counts_after = _count_by_expiry(filtered_chain)
    skipped = tuple(exp for exp in expiry_counts_before if exp not in expiry_counts_after)

    proposals = run_result.proposals
    summary = run_result.summary
    context = run_result.context
    filter_preview = RejectionSummary(
        by_filter=dict(summary.by_filter),
        by_reason=dict(summary.by_reason),
    )
    evaluated = list(pipeline.last_evaluated)

    for exp, cnt in expiry_counts_before.items():
        logger.info(f"- {exp}: {cnt} options in CSV")
    for exp, cnt in expiry_counts_after.items():
        logger.info(f"- {exp}: {cnt} options after DTE filter")
    for exp in skipped:
        logger.info(f"- {exp}: skipped (outside DTE range)")

    return ChainEvaluationResult(
        context=context,
        filtered_chain=filtered_chain,
        proposals=list(proposals),
        summary=summary,
        filter_preview=filter_preview,
        evaluated_trades=evaluated,
        expiry_counts_before=expiry_counts_before,
        expiry_counts_after=expiry_counts_after,
        skipped_expiries=skipped,
    )

