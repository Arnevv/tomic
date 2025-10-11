"""Utilities to build a structured market snapshot for the CLI layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..journal.utils import load_json
from ..utils import today


ConfigGetter = Callable[[str, Any | None], Any]


@dataclass
class MarketRow:
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


@dataclass
class Factsheet:
    """Structured representation of key metrics for a recommendation."""

    symbol: str
    strategy: str | None = None
    spot: float | None = None
    iv: float | None = None
    hv20: float | None = None
    hv30: float | None = None
    hv90: float | None = None
    hv252: float | None = None
    term_m1_m2: float | None = None
    term_m1_m3: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    skew: float | None = None
    criteria: str | None = None
    next_earnings: date | None = None
    days_until_earnings: int | None = None


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
) -> MarketRow | None:
    """Return :class:`MarketRow` for ``symbol`` using data files in ``*dir``."""

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

    return MarketRow(
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
        next_earnings=_parse_earnings(symbol, earnings, today_fn=today_fn),
    )


def _format_snapshot(rows: Sequence[MarketRow]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for row in rows:
        data = asdict(row)
        earn = data.get("next_earnings")
        if isinstance(earn, date):
            data["next_earnings"] = earn.isoformat()
        formatted.append(data)
    return formatted


def _build_factsheet(
    record: Mapping[str, Any],
    *,
    today_fn: Callable[[], date] = today,
) -> Factsheet:
    symbol = str(record.get("symbol", ""))
    strategy = record.get("strategy")
    raw_next = record.get("next_earnings")
    earnings_date: date | None = None
    if isinstance(raw_next, date):
        earnings_date = raw_next
    elif isinstance(raw_next, str) and raw_next:
        try:
            earnings_date = datetime.strptime(raw_next, "%Y-%m-%d").date()
        except Exception:
            earnings_date = None

    days_until: int | None = None
    if earnings_date is not None:
        try:
            days_until = (earnings_date - today_fn()).days
        except Exception:
            days_until = None

    return Factsheet(
        symbol=symbol,
        strategy=strategy if isinstance(strategy, str) else None,
        spot=record.get("spot"),
        iv=record.get("iv"),
        hv20=record.get("hv20"),
        hv30=record.get("hv30"),
        hv90=record.get("hv90"),
        hv252=record.get("hv252"),
        term_m1_m2=record.get("term_m1_m2"),
        term_m1_m3=record.get("term_m1_m3"),
        iv_rank=_normalize_percent(record.get("iv_rank")),
        iv_percentile=_normalize_percent(record.get("iv_percentile")),
        skew=record.get("skew"),
        criteria=record.get("criteria") if isinstance(record.get("criteria"), str) else None,
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

    def load_snapshot(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
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

        rows: list[MarketRow] = []
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

        return {
            "generated_at": self._today().isoformat(),
            "symbols": symbols,
            "rows": _format_snapshot(rows),
        }


__all__ = [
    "Factsheet",
    "MarketRow",
    "MarketSnapshotService",
    "_build_factsheet",
    "_format_snapshot",
    "_read_metrics",
]
