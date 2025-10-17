"""Services for market snapshots and symbol scanning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..journal.utils import load_json
from ..logutils import logger
from ..utils import today
from .strategy_pipeline import StrategyContext, StrategyPipeline, StrategyProposal


ConfigGetter = Callable[[str, Any | None], Any]


@dataclass(frozen=True)
class MarketSnapshotRow:
    """Normalized metrics for a single underlying symbol."""

    symbol: str
    spot: float | None = None
    iv: float | None = None
    hv20: float | None = None
    hv30: float | None = None
    hv90: float | None = None
    hv252: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    term_m1_m2: float | None = None
    term_m1_m3: float | None = None
    skew: float | None = None
    next_earnings: date | None = None
    days_until_earnings: int | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    """Structured snapshot of current market metrics."""

    generated_at: date
    symbols: list[str]
    rows: list[MarketSnapshotRow]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "symbols": list(self.symbols),
            "rows": [self._serialize_row(row) for row in self.rows],
        }

    @staticmethod
    def _serialize_row(row: MarketSnapshotRow) -> dict[str, Any]:
        data = asdict(row)
        earn = data.get("next_earnings")
        if isinstance(earn, date):
            data["next_earnings"] = earn.isoformat()
        return data


@dataclass(frozen=True)
class ScanRequest:
    """Input required to evaluate strategy proposals for a symbol."""

    symbol: str
    strategy: str
    option_chain: Sequence[Mapping[str, Any]]
    spot_price: float
    atr: float
    config: Mapping[str, Any]
    interest_rate: float
    dte_range: tuple[int, int]
    interactive_mode: bool
    next_earnings: date | None
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class ScanRow:
    """Intermediate scan result linking proposals to source metrics."""

    symbol: str
    strategy: str
    proposal: StrategyProposal
    metrics: Mapping[str, Any]
    spot: float | None
    next_earnings: date | None


class MarketSnapshotError(RuntimeError):
    """Raised when snapshot loading or scanning fails."""


def _resolve_config_getter(config: Mapping[str, Any] | ConfigGetter | None) -> ConfigGetter:
    if callable(config):
        return config  # type: ignore[return-value]
    if hasattr(config, "get"):
        return lambda key, default=None: config.get(key, default)  # type: ignore[arg-type]
    if isinstance(config, Mapping):
        return lambda key, default=None: config.get(key, default)
    return lambda _key, default=None: default


def _normalize_percent(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        val = float(value)
        if val > 1:
            val /= 100
        if 0 <= val <= 1:
            return val
    return None


def _parse_latest(data: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not data:
        return None
    try:
        return sorted(data, key=lambda item: item.get("date", ""), reverse=True)[0]
    except Exception:
        return None


def _parse_earnings(
    symbol: str,
    earnings_data: Mapping[str, Iterable[str]] | None,
    *,
    today_fn: Callable[[], date],
) -> date | None:
    if not earnings_data:
        return None
    entries = earnings_data.get(symbol)
    if not isinstance(entries, Iterable):
        return None
    upcoming: list[date] = []
    for raw in entries:
        if not isinstance(raw, str):
            continue
        try:
            earn_date = datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            continue
        if earn_date >= today_fn():
            upcoming.append(earn_date)
    return min(upcoming) if upcoming else None


def _read_metrics(
    symbol: str,
    summary_dir: Path,
    hv_dir: Path,
    spot_dir: Path,
    earnings: Mapping[str, Iterable[str]] | None,
    *,
    loader: Callable[[Path], Any] = load_json,
    today_fn: Callable[[], date] = today,
) -> MarketSnapshotRow | None:
    """Return :class:`MarketSnapshotRow` for ``symbol`` using data files in ``*dir``."""

    try:
        summary_data = loader(summary_dir / f"{symbol}.json")
        hv_data = loader(hv_dir / f"{symbol}.json")
        spot_data = loader(spot_dir / f"{symbol}.json")
    except Exception:
        return None

    if not isinstance(summary_data, Sequence) or not isinstance(hv_data, Sequence) or not isinstance(spot_data, Sequence):
        return None

    summary = _parse_latest(summary_data)
    hv = _parse_latest(hv_data)
    spot = _parse_latest(spot_data)
    if summary is None or hv is None or spot is None:
        return None

    earnings_date = _parse_earnings(symbol, earnings, today_fn=today_fn)
    days_until: int | None = None
    if earnings_date is not None:
        try:
            days_until = (earnings_date - today_fn()).days
        except Exception:
            days_until = None

    return MarketSnapshotRow(
        symbol=symbol,
        spot=spot.get("close"),
        iv=summary.get("atm_iv"),
        hv20=hv.get("hv20"),
        hv30=hv.get("hv30"),
        hv90=hv.get("hv90"),
        hv252=hv.get("hv252"),
        iv_rank=_normalize_percent(summary.get("iv_rank (HV)")),
        iv_percentile=_normalize_percent(summary.get("iv_percentile (HV)")),
        term_m1_m2=summary.get("term_m1_m2"),
        term_m1_m3=summary.get("term_m1_m3"),
        skew=summary.get("skew"),
        next_earnings=earnings_date,
        days_until_earnings=days_until,
    )


class MarketSnapshotService:
    """High level service that aggregates market metrics for the CLI."""

    def __init__(
        self,
        config: Mapping[str, Any] | ConfigGetter | None,
        *,
        loader: Callable[[Path], Any] = load_json,
        today_fn: Callable[[], date] = today,
    ) -> None:
        self._get = _resolve_config_getter(config)
        self._loader = loader
        self._today = today_fn

    def _default_symbols(self) -> list[str]:
        symbols = self._get("DEFAULT_SYMBOLS", []) or []
        if not isinstance(symbols, Iterable):
            return []
        return [str(sym).upper() for sym in symbols if isinstance(sym, str)]

    def load_snapshot(self, filters: Mapping[str, Any] | None = None) -> MarketSnapshot:
        filters = dict(filters or {})
        symbols = filters.get("symbols") or self._default_symbols()
        if isinstance(symbols, str):
            symbols = [symbols]
        symbols = [str(sym).upper() for sym in symbols if isinstance(sym, (str, bytes))]

        summary_dir = Path(self._get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
        hv_dir = Path(self._get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
        spot_dir = Path(self._get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
        earnings_file = self._get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")

        earnings: Mapping[str, Iterable[str]] | None = None
        if earnings_file:
            try:
                earnings_data = self._loader(Path(earnings_file))
            except Exception:
                earnings_data = None
            earnings = earnings_data if isinstance(earnings_data, Mapping) else None

        rows: list[MarketSnapshotRow] = []
        for symbol in symbols:
            row = _read_metrics(
                symbol,
                summary_dir,
                hv_dir,
                spot_dir,
                earnings,
                loader=self._loader,
                today_fn=self._today,
            )
            if row:
                rows.append(row)

        rows.sort(
            key=lambda r: (r.iv_percentile if r.iv_percentile is not None else -1),
            reverse=True,
        )

        return MarketSnapshot(generated_at=self._today(), symbols=list(symbols), rows=rows)

    def scan_symbols(
        self,
        universe: Sequence[ScanRequest],
        rules: Mapping[str, Any] | None = None,
    ) -> list[ScanRow]:
        rules = rules or {}
        pipeline = rules.get("pipeline")
        if pipeline is None or not hasattr(pipeline, "build_proposals"):
            raise MarketSnapshotError("rules must provide a pipeline with build_proposals")

        results: list[ScanRow] = []
        for request in universe:
            if not isinstance(request, ScanRequest):
                logger.warning("Skipping invalid scan request: %r", request)
                continue
            context = StrategyContext(
                symbol=request.symbol,
                strategy=request.strategy,
                option_chain=list(request.option_chain),
                spot_price=float(request.spot_price or 0.0),
                atr=float(request.atr or 0.0),
                config=dict(request.config or {}),
                interest_rate=float(request.interest_rate),
                dte_range=request.dte_range,
                interactive_mode=bool(request.interactive_mode),
                next_earnings=request.next_earnings,
            )
            try:
                proposals, _ = pipeline.build_proposals(context)
            except Exception as exc:  # pragma: no cover - pipeline level failure
                raise MarketSnapshotError(f"pipeline execution failed for {request.symbol}") from exc

            for proposal in proposals:
                results.append(
                    ScanRow(
                        symbol=request.symbol,
                        strategy=request.strategy,
                        proposal=proposal,
                        metrics=request.metrics,
                        spot=request.spot_price,
                        next_earnings=request.next_earnings,
                    )
                )

        return results


__all__ = [
    "MarketSnapshot",
    "MarketSnapshotError",
    "MarketSnapshotRow",
    "MarketSnapshotService",
    "ScanRequest",
    "ScanRow",
    "_read_metrics",
]
