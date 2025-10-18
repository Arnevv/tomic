from __future__ import annotations

"""Pure helpers to translate domain models into table structures."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

from tomic.helpers.dateutils import parse_date
from tomic.reporting.rejections import reason_label
from tomic.services.pipeline_refresh import Rejection
from tomic.services.portfolio_service import Factsheet
from tomic.services.proposal_details import (
    EarningsVM,
    ProposalCore,
    ProposalLegVM,
    ProposalSummaryVM,
    ProposalVM,
)
from tomic.utils import normalize_right, today

TableData = tuple[list[str], list[list[str]]]

ValueExtractor = Callable[[Any], Any]
Formatter = Callable[..., Any]


@dataclass(frozen=True)
class ColumnSpec:
    """Description of a column in a tabular view."""

    header: str
    path: str | ValueExtractor
    format: Formatter | None = None
    decimals: int | None = None
    pct: bool = False
    nullable: bool = True


@dataclass(frozen=True)
class TableSpec:
    """Specification for building deterministic table data."""

    name: str
    columns: tuple[ColumnSpec, ...]
    default_sort: tuple[str | ValueExtractor, ...] = ()


PLACEHOLDER = "—"
GREEK_LABELS = {
    "delta": "Δ",
    "gamma": "Γ",
    "vega": "V",
    "theta": "Θ",
}


def sanitize(value: Any, placeholder: str = PLACEHOLDER) -> str:
    """Return a safe string representation without NaN/Inf artifacts."""

    if value is None:
        return placeholder
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return placeholder
    if isinstance(value, str):
        return value
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        number = _to_float(value)
        if number is None:
            return None
        return Decimal(str(number))


def fmt_num(value: Any, decimals: int = 2) -> str:
    """Return a decimal formatted number or placeholder."""

    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return PLACEHOLDER
    if not decimal_value.is_finite():
        return PLACEHOLDER
    if decimals is None:
        return format(decimal_value, "f")
    quantize_expr = Decimal(1) if decimals == 0 else Decimal(f"1e-{decimals}")
    rounded = decimal_value.quantize(quantize_expr, rounding=ROUND_HALF_UP)
    return format(rounded, f".{decimals}f")


def fmt_signed(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return PLACEHOLDER
    magnitude = fmt_num(abs(number), decimals)
    if magnitude == PLACEHOLDER:
        return PLACEHOLDER
    if number > 0:
        return f"+{magnitude}"
    if number < 0:
        return f"-{magnitude}"
    return fmt_num(0.0, decimals)


def fmt_delta(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return PLACEHOLDER
    return fmt_signed(number, decimals)


def fmt_pct(value: Any, decimals: int = 1) -> str:
    number = _to_float(value)
    if number is None:
        return PLACEHOLDER
    formatted = fmt_num(number * 100, decimals)
    return PLACEHOLDER if formatted == PLACEHOLDER else f"{formatted}%"


def fmt_opt_strikes(strikes: Iterable[float | None] | None) -> str:
    if not strikes:
        return PLACEHOLDER
    formatted: list[str] = []
    for strike in strikes:
        number = _to_float(strike)
        if number is None:
            continue
        if float(number).is_integer():
            formatted_str = fmt_num(number, 0)
        else:
            formatted_str = fmt_num(number, 2)
        if formatted_str != PLACEHOLDER:
            formatted.append(formatted_str)
    return " / ".join(formatted) if formatted else PLACEHOLDER


def fmt_greek_totals(values: Mapping[str, Any] | None) -> str:
    if not values:
        return PLACEHOLDER
    parts: list[str] = []
    for key in ("delta", "gamma", "vega", "theta"):
        label = GREEK_LABELS.get(key, key.title())
        val = None
        for candidate in (values.get(key), values.get(key.title()), values.get(label)):
            val = _to_float(candidate)
            if val is not None:
                break
        if val is None:
            continue
        parts.append(f"{label} {fmt_signed(val, 2)}")
    return " · ".join(parts) if parts else PLACEHOLDER


def _extract(record: Any, path: str | ValueExtractor) -> Any:
    if callable(path):
        return path(record)
    current = record
    for segment in path.split("."):
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(segment)
        else:
            current = getattr(current, segment, None)
    return current


def _iter_core_legs(record: Any) -> Iterable[Mapping[str, Any]]:
    core = getattr(record, "core", None)
    if isinstance(core, ProposalCore):
        for leg in getattr(core, "legs", ()):
            if isinstance(leg, Mapping):
                yield leg


def _iter_leg_vms(record: Any) -> Iterable[ProposalLegVM]:
    legs = getattr(record, "legs", None)
    if legs:
        for leg in legs:
            if isinstance(leg, ProposalLegVM):
                yield leg


@dataclass(frozen=True)
class SummaryRow:
    metric: str
    value: Any
    details: Any | None = None


@dataclass(frozen=True)
class EarningsRow:
    metric: str
    value: Any
    details: Any | None = None


def _first_leg_iv(record: Any) -> float | None:
    for leg in _iter_leg_vms(record):
        if leg.iv is not None:
            return leg.iv
    for leg in _iter_core_legs(record):
        iv = leg.get("iv")
        val = _to_float(iv)
        if val is not None:
            return val
    return None


def _pricing_value(record: Any, key: str) -> Any:
    summary = getattr(record, "summary", None)
    if summary is not None and hasattr(summary, key):
        value = getattr(summary, key)
        if value not in (None, ""):
            return value
    core = getattr(record, "core", None)
    pricing = getattr(core, "pricing_meta", None)
    if isinstance(pricing, Mapping):
        return pricing.get(key)
    return None


def _greek_value(record: Any, greek: str) -> Any:
    summary = getattr(record, "summary", None)
    if summary is not None and isinstance(getattr(summary, "greeks", None), Mapping):
        value = summary.greeks.get(greek)
        if value not in (None, ""):
            return value
    core = getattr(record, "core", None)
    if isinstance(core, ProposalCore) and isinstance(core.greeks, Mapping):
        return core.greeks.get(greek)
    return None


def _credit_or_mid(record: ProposalVM) -> float | None:
    credit = _pricing_value(record, "credit")
    if credit is not None:
        return _to_float(credit)
    mids: list[float] = []
    for leg in _iter_leg_vms(record):
        mid = _to_float(leg.mid)
        if mid is not None:
            mids.append(mid)
    if mids:
        return sum(mids) / len(mids)
    return None


def _primary_reason(record: Rejection) -> str:
    reasons = getattr(record, "reasons", ())
    if not reasons:
        return ""
    return reason_label(reasons[0])


def _leg_count(record: Any) -> int:
    return sum(1 for _ in _iter_core_legs(record))


def _sort_right(record: Any) -> str:
    for leg in _iter_core_legs(record):
        right = leg.get("type") or leg.get("right")
        if right:
            normalized = normalize_right(str(right))
            if normalized:
                return normalized
    return ""


def _sort_strike(record: Any) -> float:
    strikes: list[float] = []
    for leg in _iter_core_legs(record):
        strike = _to_float(leg.get("strike"))
        if strike is not None:
            strikes.append(strike)
    return min(strikes) if strikes else math.inf


def _collect_expiry_dates(record: Any) -> list[date]:
    expiries: list[date] = []
    core = getattr(record, "core", None)
    values: list[Any] = []
    if core is not None:
        expiry = getattr(core, "expiry", None)
        if expiry:
            values.append(expiry)
    for leg in _iter_core_legs(record):
        values.append(leg.get("expiry"))
    for value in values:
        if value is None:
            continue
        parsed = parse_date(str(value))
        if parsed:
            expiries.append(parsed)
    return expiries


def _min_dte(record: Any) -> int | None:
    expiries = _collect_expiry_dates(record)
    if not expiries:
        return None
    today_value = today()
    deltas = [(expiry - today_value).days for expiry in expiries]
    if not deltas:
        return None
    return min(deltas)


def _apply_format(column: ColumnSpec, value: Any, record: Any) -> Any:
    formatter = column.format
    if formatter is None:
        return value
    try:
        return formatter(value)
    except TypeError:
        return formatter(value, record)


def _render_cell(record: Any, column: ColumnSpec) -> str:
    raw_value = _extract(record, column.path)
    if raw_value in (None, "") and column.nullable:
        return PLACEHOLDER
    value = raw_value
    if column.format is not None:
        value = _apply_format(column, raw_value, record)
    elif column.pct:
        decimals = column.decimals if column.decimals is not None else 1
        value = fmt_pct(raw_value, decimals)
    elif isinstance(raw_value, (int, float)) or _to_float(raw_value) is not None:
        decimals = column.decimals if column.decimals is not None else 2
        value = fmt_num(raw_value, decimals)
    return sanitize(value)


def _normalize_sort_value(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.lower())
    if isinstance(value, (int, float)):
        number = _to_float(value)
        if number is None:
            return (1, math.inf)
        return (0, number)
    if isinstance(value, date):
        return (0, value.isoformat())
    return (0, str(value))


def _sort_key(record: Any, spec: TableSpec) -> tuple[tuple[int, Any], ...]:
    if not spec.default_sort:
        return ((_normalize_sort_value(0),))
    resolved: list[tuple[int, Any]] = []
    for item in spec.default_sort:
        resolved.append(_normalize_sort_value(_extract(record, item)))
    return tuple(resolved)


def sort_records(records: Sequence[Any], spec: TableSpec) -> list[Any]:
    """Return records sorted deterministically according to ``spec``."""

    return sorted(records, key=lambda record: _sort_key(record, spec))


def _build_table(records: Sequence[Any], spec: TableSpec) -> TableData:
    if not records:
        return ([col.header for col in spec.columns], [])
    sorted_records = sort_records(records, spec)
    rows: list[list[str]] = []
    for record in sorted_records:
        row = [_render_cell(record, column) for column in spec.columns]
        rows.append(row)
    headers = [column.header for column in spec.columns]
    return headers, rows


REJECTIONS_SPEC = TableSpec(
    name="rejections",
    columns=(
        ColumnSpec("Symbol", "core.symbol"),
        ColumnSpec("Expiry", "core.expiry"),
        ColumnSpec("LegCount", _leg_count, decimals=0),
        ColumnSpec("Reason", _primary_reason, nullable=False),
        ColumnSpec("Score", lambda r: _pricing_value(r, "score"), decimals=2),
        ColumnSpec("Δ", lambda r: _greek_value(r, "delta"), format=fmt_delta),
        ColumnSpec("IV", _first_leg_iv, format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("EV", lambda r: _pricing_value(r, "ev"), decimals=2),
        ColumnSpec("DTE", _min_dte, decimals=0),
    ),
    default_sort=("core.symbol", "core.expiry", _sort_right, _sort_strike),
)


PROPOSALS_SPEC = TableSpec(
    name="proposals",
    columns=(
        ColumnSpec("Symbol", "core.symbol"),
        ColumnSpec("Strategy", "core.strategy"),
        ColumnSpec("Expiry", "core.expiry"),
        ColumnSpec("Strike(s)", lambda vm: getattr(vm.core, "strikes", ()), format=fmt_opt_strikes),
        ColumnSpec("Δ", lambda r: _greek_value(r, "delta"), format=fmt_delta),
        ColumnSpec("Θ", lambda r: _greek_value(r, "theta"), format=lambda v: fmt_signed(v, 2)),
        ColumnSpec("Vega", lambda r: _greek_value(r, "vega"), format=lambda v: fmt_signed(v, 2)),
        ColumnSpec("IV", _first_leg_iv, format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("EV", lambda r: _pricing_value(r, "ev"), decimals=2),
        ColumnSpec("PoS", lambda r: _pricing_value(r, "pos"), format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("Credit/Mid", _credit_or_mid, decimals=2),
    ),
    default_sort=("core.symbol", "core.expiry", _sort_right, _sort_strike),
)


PORTFOLIO_SPEC = TableSpec(
    name="portfolio",
    columns=(
        ColumnSpec("Symbol", "symbol"),
        ColumnSpec("Qty", lambda f: getattr(f, "quantity", None), decimals=0),
        ColumnSpec("Exposure", lambda f: getattr(f, "exposure", None), decimals=2),
        ColumnSpec(
            "Greeks Σ",
            lambda f: getattr(f, "greeks", None) or getattr(f, "greeks_sum", None),
            format=fmt_greek_totals,
        ),
        ColumnSpec("IV Rank", "iv_rank", format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("HV30", "hv30", format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("ATR", lambda f: getattr(f, "atr", None), decimals=2),
    ),
    default_sort=("symbol",),
)


def rejections_table(
    rejections: Sequence[Rejection], *, spec: TableSpec = REJECTIONS_SPEC
) -> TableData:
    """Return headers and rows for rejection summaries."""

    return _build_table(rejections, spec)


def proposals_table(
    proposals: Sequence[ProposalVM], *, spec: TableSpec = PROPOSALS_SPEC
) -> TableData:
    """Return headers and rows for proposal overviews."""

    return _build_table(proposals, spec)


def portfolio_table(
    factsheets: Sequence[Factsheet | Any], *, spec: TableSpec = PORTFOLIO_SPEC
) -> TableData:
    """Return headers and rows for portfolio snapshots."""

    return _build_table(factsheets, spec)


def _leg_position_label(leg: ProposalLegVM) -> str:
    position = getattr(leg, "position", None)
    if position is None:
        return PLACEHOLDER
    if position < 0:
        return "S"
    if position > 0:
        return "L"
    return "0"


def _leg_option_type(leg: ProposalLegVM) -> str:
    option_type = getattr(leg, "option_type", None)
    if not option_type:
        return ""
    return str(option_type).upper()


def _format_breakevens(values: Iterable[Any] | None) -> str:
    if not values:
        return PLACEHOLDER
    formatted: list[str] = []
    for value in values:
        formatted_value = fmt_num(value, 2)
        if formatted_value != PLACEHOLDER:
            formatted.append(formatted_value)
    return ", ".join(formatted) if formatted else PLACEHOLDER


def _scenario_detail(summary: ProposalSummaryVM) -> str | None:
    label = summary.scenario_label.strip() if summary.scenario_label else ""
    if summary.profit_estimated:
        if label:
            return f"{label} (geschat)"
        return "(geschat)"
    if label:
        return label
    return None


def _summary_status(accepted: bool | None) -> str | None:
    if accepted is True:
        return "✅ geaccepteerd"
    if accepted is False:
        return "❌ afgewezen"
    return None


def _format_summary_value(value: Any, row: SummaryRow) -> str:
    metric = getattr(row, "metric", "").lower()
    if metric in {"score", "ev", "credit", "margin", "max win", "max loss", "risk/reward", "rom", "edge"}:
        return fmt_num(value, 2)
    if metric == "pos":
        return fmt_pct(value, 1)
    if metric == "breakevens":
        return _format_breakevens(value if isinstance(value, Iterable) else None)
    if metric == "bron":
        return sanitize(value)
    if metric == "greeks σ":
        mapping = value if isinstance(value, Mapping) else {}
        return fmt_greek_totals(mapping)
    if metric.startswith("iv"):
        return fmt_pct(value, 1)
    if metric.startswith("hv"):
        return fmt_pct(value, 1)
    return sanitize(value)


def _format_summary_details(value: Any, row: SummaryRow) -> str:
    if value in (None, ""):
        return PLACEHOLDER
    return sanitize(value)


def _format_earnings_value(value: Any, row: EarningsRow) -> str:
    if value in (None, ""):
        return PLACEHOLDER
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, bool):
        return "Ja" if value else "Nee"
    if isinstance(value, (int, float)):
        number = _to_float(value)
        if number is None:
            return PLACEHOLDER
        return fmt_num(number, 0 if float(number).is_integer() else 2)
    return sanitize(value)


def _format_earnings_details(value: Any, row: EarningsRow) -> str:
    if value in (None, ""):
        return PLACEHOLDER
    return sanitize(value)


PROPOSAL_LEGS_SPEC = TableSpec(
    name="proposal_legs",
    columns=(
        ColumnSpec("Expiry", "expiry"),
        ColumnSpec("Strike", "strike", decimals=2),
        ColumnSpec("Type", _leg_option_type, nullable=False),
        ColumnSpec("Pos", _leg_position_label, nullable=False),
        ColumnSpec("Bid", "bid", decimals=2),
        ColumnSpec("Ask", "ask", decimals=2),
        ColumnSpec("Mid", "mid", decimals=2),
        ColumnSpec("IV", "iv", format=lambda v: fmt_pct(v, 1)),
        ColumnSpec("Δ", "delta", format=lambda v: fmt_signed(v, 2)),
        ColumnSpec("Γ", "gamma", format=lambda v: fmt_signed(v, 4)),
        ColumnSpec("Vega", "vega", format=lambda v: fmt_signed(v, 2)),
        ColumnSpec("Θ", "theta", format=lambda v: fmt_signed(v, 2)),
    ),
    default_sort=("expiry", "strike", "option_type"),
)


PROPOSAL_SUMMARY_SPEC = TableSpec(
    name="proposal_summary",
    columns=(
        ColumnSpec("Metric", "metric", nullable=False),
        ColumnSpec("Value", "value", format=_format_summary_value),
        ColumnSpec("Details", "details", format=_format_summary_details),
    ),
)


PROPOSAL_EARNINGS_SPEC = TableSpec(
    name="proposal_earnings",
    columns=(
        ColumnSpec("Metric", "metric", nullable=False),
        ColumnSpec("Value", "value", format=_format_earnings_value),
        ColumnSpec("Details", "details", format=_format_earnings_details),
    ),
)


def proposal_legs_table(vm: ProposalVM, *, spec: TableSpec = PROPOSAL_LEGS_SPEC) -> TableData:
    """Return table data for proposal legs."""

    return _build_table(vm.legs, spec)


def proposal_summary_table(vm: ProposalVM, *, spec: TableSpec = PROPOSAL_SUMMARY_SPEC) -> TableData:
    """Return table data for proposal summary metrics."""

    summary = vm.summary
    scenario_detail = _scenario_detail(summary)
    source = "IB-update" if vm.accepted is not None else "Metrics"
    rows: list[SummaryRow] = [
        SummaryRow("Bron", source, _summary_status(vm.accepted)),
        SummaryRow("Score", summary.score),
        SummaryRow("EV", summary.ev, scenario_detail),
        SummaryRow("Risk/Reward", summary.risk_reward),
        SummaryRow("Credit", summary.credit),
        SummaryRow("Margin", summary.margin),
        SummaryRow("Max win", summary.max_profit),
        SummaryRow("Max loss", summary.max_loss),
        SummaryRow("Breakevens", summary.breakevens),
        SummaryRow("PoS", summary.pos),
        SummaryRow("ROM", summary.rom, scenario_detail),
    ]
    if summary.edge is not None:
        rows.append(SummaryRow("Edge", summary.edge))
    if summary.greeks:
        rows.append(SummaryRow("Greeks Σ", summary.greeks))
    if summary.iv_rank is not None:
        rows.append(SummaryRow("IV Rank", summary.iv_rank))
    if summary.iv_percentile is not None:
        rows.append(SummaryRow("IV Percentile", summary.iv_percentile))
    for hv_label, value in (
        ("HV20", summary.hv20),
        ("HV30", summary.hv30),
        ("HV90", summary.hv90),
        ("HV252", summary.hv252),
    ):
        if value is not None:
            rows.append(SummaryRow(hv_label, value))
    if summary.scenario_error:
        rows.append(SummaryRow("Scenario fout", summary.scenario_error))
    return _build_table(rows, spec)


def proposal_earnings_table(vm: ProposalVM, *, spec: TableSpec = PROPOSAL_EARNINGS_SPEC) -> TableData:
    """Return table data describing proposal earnings context."""

    earnings = vm.earnings if isinstance(vm.earnings, EarningsVM) else None
    if earnings is None:
        return ([column.header for column in spec.columns], [])
    rows: list[EarningsRow] = []
    if earnings.next_earnings:
        rows.append(EarningsRow("Volgende earnings", earnings.next_earnings))
    if earnings.days_until is not None:
        rows.append(EarningsRow("Dagen tot earnings", earnings.days_until))
    if earnings.expiry_gap_days is not None:
        rows.append(EarningsRow("Gap tot expiratie", earnings.expiry_gap_days))
    if earnings.occurs_before_expiry is not None:
        rows.append(EarningsRow("Earnings voor expiratie", earnings.occurs_before_expiry))
    if not rows:
        return ([column.header for column in spec.columns], [])
    return _build_table(rows, spec)


__all__ = [
    "ColumnSpec",
    "TableSpec",
    "TableData",
    "fmt_delta",
    "fmt_num",
    "fmt_opt_strikes",
    "fmt_pct",
    "proposal_earnings_table",
    "proposal_legs_table",
    "proposal_summary_table",
    "portfolio_table",
    "proposals_table",
    "rejections_table",
    "sanitize",
    "sort_records",
    "PORTFOLIO_SPEC",
    "PROPOSAL_EARNINGS_SPEC",
    "PROPOSAL_LEGS_SPEC",
    "PROPOSAL_SUMMARY_SPEC",
    "PROPOSALS_SPEC",
    "REJECTIONS_SPEC",
]
