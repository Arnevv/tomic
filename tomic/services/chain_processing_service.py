from __future__ import annotations

"""Pure services for loading and evaluating option chains."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

import pandas as pd

from ..helpers.csv_utils import normalize_european_number_format
from ..helpers.interpolation import interpolate_missing_fields
from ..helpers.quality_check import calculate_csv_quality
from ..loader import load_strike_config
from ..logutils import logger
from ..strike_selector import filter_by_expiry
from ..utils import normalize_leg
from .strategy_pipeline import (
    RejectionSummary,
    StrategyContext,
    StrategyPipeline,
    StrategyProposal,
)


NumericColumns = (
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


class ChainProcessingError(RuntimeError):
    """Raised when a chain cannot be loaded or processed."""


@dataclass
class ChainProcessingConfig:
    """Configuration required for chain preparation and evaluation."""

    csv_min_quality: float = 70.0
    interest_rate: float = 0.05
    export_dir: Path = Path("exports")
    strategy_config: Mapping[str, Any] = field(default_factory=dict)
    default_dte_range: tuple[int, int] = (0, 365)
    score_weight_rom: float = 0.5
    score_weight_pos: float = 0.3
    score_weight_ev: float = 0.2

    @classmethod
    def from_settings(cls, settings: Any) -> "ChainProcessingConfig":
        """Create configuration from the shared ``cfg`` object."""

        get = getattr(settings, "get", None)
        if not callable(get):
            return cls()

        export_dir = Path(get("EXPORT_DIR", "exports"))
        strategy_config = get("STRATEGY_CONFIG") or {}
        return cls(
            csv_min_quality=float(get("CSV_MIN_QUALITY", 70)),
            interest_rate=float(get("INTEREST_RATE", 0.05)),
            export_dir=export_dir,
            strategy_config=strategy_config,
            default_dte_range=(0, 365),
            score_weight_rom=float(get("SCORE_WEIGHT_ROM", 0.5)),
            score_weight_pos=float(get("SCORE_WEIGHT_POS", 0.3)),
            score_weight_ev=float(get("SCORE_WEIGHT_EV", 0.2)),
        )


@dataclass
class PreparedChain:
    """Normalized data returned by :func:`load_and_prepare_chain`."""

    path: Path
    dataframe: pd.DataFrame
    normalized_legs: list[MutableMapping[str, Any]]
    quality: float
    interpolation_applied: bool = False

    def expiry_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.normalized_legs:
            exp = row.get("expiry")
            if exp:
                counts[exp] = counts.get(exp, 0) + 1
        return counts


@dataclass(frozen=True)
class SpotPriceResolver:
    """Callables used to resolve a spot price for a symbol."""

    refresh: Callable[[str], float | None] | None = None
    from_metrics: Callable[[Path, str], float | None] | None = None
    latest_close: Callable[[str], float | None] | None = None
    from_chain: Callable[[Sequence[Mapping[str, Any]]], float | None] | None = None

    def resolve(
        self,
        symbol: str,
        chain_directory: Path,
        chain: Sequence[Mapping[str, Any]],
        initial: float | None,
    ) -> float | None:
        """Resolve spot price using configured callables."""

        spot = _valid_price(initial)
        if spot is not None:
            return spot

        if self.refresh is not None:
            spot = _valid_price(self.refresh(symbol))
            if spot is not None:
                return spot

        if self.from_metrics is not None:
            spot = _valid_price(self.from_metrics(chain_directory, symbol))
            if spot is not None:
                return spot

        if self.latest_close is not None:
            spot = _valid_price(self.latest_close(symbol))
            if spot is not None:
                return spot

        if self.from_chain is not None:
            spot = _valid_price(self.from_chain(chain))
            if spot is not None:
                return spot

        return None


@dataclass(frozen=True)
class ChainEvaluationConfig:
    """Parameters required to evaluate a prepared chain."""

    symbol: str
    strategy: str
    atr: float
    interest_rate: float
    export_dir: Path
    strategy_config: Mapping[str, Any]
    default_dte_range: tuple[int, int]
    interactive_mode: bool = True
    initial_spot: float | None = None
    chain_directory: Path | None = None
    criteria: Any | None = None


@dataclass
class ChainEvaluation:
    """Evaluation result returned by :func:`evaluate_chain`."""

    context: StrategyContext
    proposals: list[StrategyProposal]
    summary: RejectionSummary
    filtered_chain: list[MutableMapping[str, Any]]
    dte_range: tuple[int, int]
    expiry_counts_before: dict[str, int]
    expiry_counts_after: dict[str, int]
    spot_price: float | None
    evaluated_trades: list[dict[str, Any]]


def load_and_prepare_chain(
    path: Path,
    symbol: str,
    config: ChainProcessingConfig,
    *,
    apply_interpolation: bool = False,
) -> PreparedChain:
    """Load an option chain CSV and normalize it for further processing."""

    if not path.exists():
        raise ChainProcessingError(f"Chain-bestand ontbreekt: {path}")

    try:
        df = pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - pandas error formatting
        raise ChainProcessingError(f"Fout bij laden van chain: {exc}") from exc

    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    df = normalize_european_number_format(df, NumericColumns)

    if "expiry" not in df.columns and "expiration" in df.columns:
        df = df.rename(columns={"expiration": "expiry"})
    elif "expiry" in df.columns and "expiration" in df.columns:
        df = df.drop(columns=["expiration"])

    if "expiry" in df.columns:
        df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime("%Y-%m-%d")

    if apply_interpolation:
        logger.info(
            "Interpolating missing delta/iv values using linear (delta) and spline (iv)"
        )
        df = interpolate_missing_fields(df)

    quality = calculate_csv_quality(df)
    normalized = [normalize_leg(rec) for rec in df.to_dict(orient="records")]

    return PreparedChain(
        path=path,
        dataframe=df,
        normalized_legs=normalized,
        quality=float(quality),
        interpolation_applied=apply_interpolation,
    )


def evaluate_chain(
    prepared: PreparedChain,
    config: ChainEvaluationConfig,
    pipeline: StrategyPipeline,
    *,
    spot_resolver: SpotPriceResolver | None = None,
) -> ChainEvaluation:
    """Evaluate a prepared chain using ``pipeline`` and return structured data."""

    chain_directory = config.chain_directory or prepared.path.parent
    expiry_counts_before = prepared.expiry_counts()

    rules = {}
    if config.strategy_config:
        try:
            rules = load_strike_config(config.strategy, config.strategy_config)
        except Exception as exc:  # pragma: no cover - defensive log
            logger.warning("Failed to load strike config for %s: %s", config.strategy, exc)

    dte_range = _extract_dte_range(rules.get("dte_range"), config.default_dte_range)
    filtered_chain = list(filter_by_expiry(prepared.normalized_legs, dte_range))

    expiry_counts_after: dict[str, int] = {}
    for row in filtered_chain:
        exp = row.get("expiry")
        if exp:
            expiry_counts_after[exp] = expiry_counts_after.get(exp, 0) + 1

    if spot_resolver is not None:
        spot_price = spot_resolver.resolve(
            config.symbol,
            chain_directory,
            filtered_chain or prepared.normalized_legs,
            config.initial_spot,
        )
    else:
        spot_price = _valid_price(config.initial_spot)

    context = StrategyContext(
        symbol=config.symbol,
        strategy=config.strategy,
        option_chain=filtered_chain,
        spot_price=float(spot_price or 0.0),
        atr=float(config.atr or 0.0),
        config=config.strategy_config,
        interest_rate=float(config.interest_rate),
        dte_range=dte_range,
        interactive_mode=config.interactive_mode,
        criteria=config.criteria,
        debug_path=config.export_dir / "PEP_debugfilter.csv",
    )

    proposals, summary = pipeline.build_proposals(context)
    evaluated_trades = list(pipeline.last_evaluated)

    return ChainEvaluation(
        context=context,
        proposals=list(proposals),
        summary=summary,
        filtered_chain=filtered_chain,
        dte_range=dte_range,
        expiry_counts_before=expiry_counts_before,
        expiry_counts_after=expiry_counts_after,
        spot_price=spot_price,
        evaluated_trades=evaluated_trades,
    )


def spot_from_chain(chain: Sequence[Mapping[str, Any]]) -> float | None:
    """Return the first positive spot-like value from ``chain``."""

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


def _valid_price(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        price = float(value)
    except Exception:
        return None
    return price if price > 0 else None


def _extract_dte_range(raw: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        start, end = raw
        return int(start), int(end)
    except Exception:
        return fallback

