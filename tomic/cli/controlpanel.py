"""Interactive command line interface for TOMIC utilities."""

import argparse
import subprocess
import sys
from datetime import datetime, date
import json
from pathlib import Path
import os
import csv
from collections import defaultdict
import math
import inspect
import re
from dataclasses import dataclass, field, fields
from typing import Any, Iterable, Mapping, Sequence
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
from tomic.cli import services
from tomic.helpers.price_utils import _load_latest_close
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.polygon_client import PolygonClient
from tomic.strike_selector import StrikeSelector, filter_by_expiry
from tomic.loader import load_strike_config
from tomic.utils import get_option_mid_price, latest_atr, normalize_leg, load_price_history
from tomic.metrics import calculate_edge, calculate_ev, calculate_pos, calculate_rom
from tomic.helpers.csv_utils import normalize_european_number_format
from tomic.helpers.interpolation import interpolate_missing_fields
from tomic.helpers.quality_check import calculate_csv_quality
import pandas as pd
from tomic.services.strategy_pipeline import (
    StrategyPipeline,
    StrategyContext,
    StrategyProposal,
    RejectionSummary,
)
from tomic.services.ib_marketdata import fetch_quote_snapshot, SnapshotResult
from tomic.services.order_submission import (
    OrderSubmissionService,
    prepare_order_instructions,
)
from tomic.scripts.backfill_hv import run_backfill_hv
from tomic.cli.iv_backfill_flow import run_iv_backfill_flow
from tomic.services.market_snapshot import (
    MarketSnapshotService,
    _build_factsheet,
)
from tomic.strategy.reasons import (
    ReasonCategory,
    ReasonDetail,
    ReasonLike,
    category_label,
    category_priority,
)
from tomic.strategy_candidates import generate_strategy_candidates
from tomic.core import config as runtime_config
from tomic.criteria import load_criteria

setup_logging(stdout=True)


POSITIONS_FILE = Path(cfg.get("POSITIONS_FILE", "positions.json"))
ACCOUNT_INFO_FILE = Path(cfg.get("ACCOUNT_INFO_FILE", "account_info.json"))
META_FILE = Path(cfg.get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
STRATEGY_DASHBOARD_MODULE = "tomic.cli.strategy_dashboard"

# Runtime session data shared between menu steps
SESSION_STATE: dict[str, object] = {
    "evaluated_trades": [],
    "iv": None,
    "hv20": None,
    "hv30": None,
    "hv90": None,
    "hv252": None,
    "term_m1_m2": None,
    "term_m1_m3": None,
    "criteria": None,
    "combo_evaluations": [],
    "combo_evaluation_summary": None,
}

MARKET_SNAPSHOT_SERVICE = MarketSnapshotService(cfg)


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


@dataclass
class ReasonAggregator:
    by_filter: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)
    by_strategy: dict[str, list[str]] = field(default_factory=dict)
    by_category: dict[ReasonCategory, int] = field(default_factory=dict)

    @classmethod
    def label_for(cls, category: ReasonCategory) -> str:
        return category_label(category)

    def _register_reason(self, detail: ReasonDetail, *, count: int = 1) -> str:
        label = detail.message or self.label_for(detail.category)
        if count > 0:
            self.by_reason[label] = self.by_reason.get(label, 0) + count
            self.by_category[detail.category] = (
                self.by_category.get(detail.category, 0) + count
            )
        return label

    @classmethod
    def _split_reason(cls, text: str) -> list[str]:
        parts = [
            frag.strip()
            for frag in re.split(r"[;,\n\u2022\|]+", text)
            if frag and frag.strip()
        ]
        return parts or [text.strip()]

    def _normalize_reason_list(self, reason: ReasonLike) -> list[ReasonDetail]:
        if isinstance(reason, ReasonCategory):
            return [normalize_reason(reason)]
        if isinstance(reason, str):
            fragments = self._split_reason(reason)
            details = [normalize_reason(fragment) for fragment in fragments]
            if details:
                return details
            return [normalize_reason(reason)]
        return [normalize_reason(reason)]

    def add_reason(
        self,
        reason: ReasonLike,
        *,
        strategy: str | None = None,
        count: int = 1,
    ) -> ReasonDetail:
        details = self._normalize_reason_list(reason)
        details.sort(key=lambda detail: category_priority(detail.category))
        count_value = max(int(count), 0)
        labels = [
            self._register_reason(detail, count=count_value)
            for detail in details
        ]
        detail = details[0]
        label = labels[0]
        if isinstance(reason, ReasonDetail):
            raw_label = reason.message or self.label_for(reason.category)
        elif isinstance(reason, ReasonCategory):
            raw_label = self.label_for(reason)
        else:
            raw_label = str(reason)
        mapped = ", ".join(
            f"{lbl} ({det.category.value})" for det, lbl in zip(details, labels)
        )
        logger.info(f"[reason-selection] raw={raw_label} -> {mapped}")
        if strategy:
            self.by_strategy.setdefault(strategy, []).extend(labels)
        return detail

    def extend_reasons(self, reasons: Iterable[ReasonLike]) -> None:
        for reason in reasons:
            self.add_reason(reason)

    def add_reason_with_count(
        self,
        reason: ReasonLike,
        count: int,
        *,
        strategy: str | None = None,
    ) -> ReasonDetail:
        return self.add_reason(reason, strategy=strategy, count=count)

    def extend_reason_counts(self, counts: Mapping[ReasonLike, int]) -> None:
        for reason, count in counts.items():
            self.add_reason(reason, count=count)

    def add_filter(self, name: str) -> None:
        if not name:
            return
        self.by_filter[name] = self.by_filter.get(name, 0) + 1


@dataclass
class ExpiryBreakdown:
    label: str
    sort_key: date | None = None
    ok: int = 0
    reject: int = 0
    other: dict[str, int] = field(default_factory=dict)

    def add(self, status: str) -> None:
        normalized = (status or "").strip().lower()
        if normalized == "pass":
            self.ok += 1
        elif normalized == "reject":
            self.reject += 1
        else:
            key = (status or "OTHER").strip().upper() or "OTHER"
            self.other[key] = self.other.get(key, 0) + 1

    def format_counts(self) -> str:
        parts = [f"OK {self.ok}", f"Reject {self.reject}"]
        if self.other:
            extras = " · ".join(f"{name} {count}" for name, count in sorted(self.other.items()))
            parts.append(extras)
        return " | ".join(parts)


@dataclass
class EvaluationSummary:
    total: int = 0
    expiries: dict[str, ExpiryBreakdown] = field(default_factory=dict)
    reasons: ReasonAggregator = field(default_factory=ReasonAggregator)
    rejects: int = 0

    @property
    def reject_total(self) -> int:
        return self.rejects

    @property
    def reason_total(self) -> int:
        return sum(self.reasons.by_category.values())

    def sorted_expiries(self) -> list[ExpiryBreakdown]:
        return sorted(
            self.expiries.values(),
            key=lambda item: ((item.sort_key or date.max), item.label),
        )


def _normalize_expiry_value(value: Any) -> tuple[str | None, date | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat(), value
    text = str(value).strip()
    if not text:
        return None, None
    parsed = parse_date(text)
    if parsed:
        return parsed.isoformat(), parsed
    return text, None


def _resolve_expiry_label(entry: Mapping[str, Any]) -> tuple[str, date | None]:
    expiries: set[Any] = set()
    legs = entry.get("legs") if isinstance(entry, Mapping) else None
    if isinstance(legs, Sequence):
        for leg in legs:
            if isinstance(leg, Mapping):
                expiries.add(leg.get("expiry"))
    if not expiries:
        meta = entry.get("meta") if isinstance(entry, Mapping) else None
        if isinstance(meta, Mapping):
            extra_expiry = meta.get("expiry")
            if isinstance(extra_expiry, Sequence) and not isinstance(extra_expiry, (str, bytes)):
                expiries.update(extra_expiry)
            elif extra_expiry is not None:
                expiries.add(extra_expiry)
    normalized = [
        _normalize_expiry_value(expiry)
        for expiry in expiries
        if expiry not in {None, ""}
    ]
    normalized = [(label, key) for label, key in normalized if label]
    if not normalized:
        return "—", None
    merged: dict[str, date | None] = {}
    for label, sort_key in normalized:
        if label not in merged:
            merged[label] = sort_key
        else:
            current = merged[label]
            if current is None and sort_key is not None:
                merged[label] = sort_key
            elif current is not None and sort_key is not None:
                merged[label] = min(current, sort_key)
    ordered = sorted(merged.items(), key=lambda item: ((item[1] or date.max), item[0]))
    labels = [label for label, _ in ordered]
    sort_key = ordered[0][1]
    return " / ".join(labels), sort_key


def summarize_evaluations(evaluations: Sequence[Mapping[str, Any]]) -> EvaluationSummary | None:
    if not evaluations:
        return None
    summary = EvaluationSummary(total=len(evaluations))
    for entry in evaluations:
        label, sort_key = _resolve_expiry_label(entry)
        breakdown = summary.expiries.get(label)
        if breakdown is None:
            breakdown = ExpiryBreakdown(label=label, sort_key=sort_key)
            summary.expiries[label] = breakdown
        status = str(entry.get("status", "")) if isinstance(entry, Mapping) else ""
        breakdown.add(status)
        if status.strip().lower() == "reject":
            summary.rejects += 1
            reason = None
            if isinstance(entry, Mapping):
                reason = entry.get("reason")
                if reason is None:
                    reason = entry.get("raw_reason")
            summary.reasons.add_reason(reason)
    return summary


def _format_reject_reasons(summary: EvaluationSummary) -> str:
    total_rejects = summary.reject_total or summary.reason_total
    if not total_rejects:
        return "n.v.t."
    ordered = sorted(
        summary.reasons.by_category.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    parts = []
    for category, count in ordered:
        label = ReasonAggregator.label_for(category)
        percentage = round((count / total_rejects) * 100)
        parts.append(f"{label} ({percentage}%)")
    return " · ".join(parts)


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
    print(f"Top reason for reject: {_format_reject_reasons(summary)}")


def _generate_with_capture(*args: Any, **kwargs: Any):
    SESSION_STATE["combo_evaluations"] = []
    SESSION_STATE["combo_evaluation_summary"] = None
    with capture_combo_evaluations() as captured:
        try:
            result = generate_strategy_candidates(*args, **kwargs)
        finally:
            summary = summarize_evaluations(captured)
            SESSION_STATE["combo_evaluations"] = list(captured)
            SESSION_STATE["combo_evaluation_summary"] = summary
    return result


def _reason_label(value: ReasonLike | ReasonDetail | None) -> str:
    try:
        detail = normalize_reason(value)
    except Exception:
        return str(value)
    return detail.message or ReasonAggregator.label_for(detail.category)


def _format_leg_position(raw: Any) -> str:
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return "?"
    return "S" if num < 0 else "L"


def _format_leg_summary(legs: Sequence[Mapping[str, Any]] | None) -> str:
    if not legs:
        return "—"
    parts: list[str] = []
    for leg in legs:
        typ = str(leg.get("type") or "").upper()[:1]
        strike = leg.get("strike")
        pos = _format_leg_position(leg.get("position"))
        label = f"{pos}{typ}" if typ else pos
        if strike is not None:
            try:
                strike_val = float(strike)
                label = f"{label} {strike_val:g}"
            except (TypeError, ValueError):
                label = f"{label} {strike}"
        parts.append(label.strip())
    return ", ".join(parts) if parts else "—"


def _format_expiry_dte(expiry: Any) -> str:
    if not expiry:
        return ""
    expiry_str = str(expiry)
    try:
        exp_date = parse_date(expiry_str)
    except Exception:
        exp_date = None
    if isinstance(exp_date, date):
        dte = (exp_date - today()).days
        return f"{expiry_str} ({dte}d)"
    return expiry_str


def _format_dtes(legs: Sequence[Mapping[str, Any]] | None) -> str:
    if not legs:
        return ""
    expiries: list[str] = []
    seen: set[str] = set()
    for leg in legs:
        formatted = _format_expiry_dte(leg.get("expiry"))
        if formatted and formatted not in seen:
            expiries.append(formatted)
            seen.add(formatted)
    return ", ".join(expiries)


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_money(value: Any) -> str:
    num = _to_float(value)
    if num is None:
        return "—"
    return f"{num:.2f}"


def _build_rejection_table(
    entries: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[str], list[list[str]], list[Mapping[str, Any]]]:
    rejects: list[Mapping[str, Any]] = []
    if entries:
        for entry in entries:
            status = str(entry.get("status", "")).lower()
            if status == "pass":
                continue
            rejects.append(entry)

    if not rejects:
        return [], [], []

    def _score_value(entry: Mapping[str, Any]) -> float | None:
        metrics = entry.get("metrics") or {}
        if isinstance(metrics, Mapping):
            score_val = _to_float(metrics.get("score"))
        else:
            score_val = None
        if score_val is None:
            score_val = _to_float(entry.get("score"))
        return score_val

    scored_rejects: list[tuple[int, Mapping[str, Any], float | None]] = [
        (idx, entry, _score_value(entry)) for idx, entry in enumerate(rejects)
    ]

    def _sort_key(item: tuple[int, Mapping[str, Any], float | None]) -> tuple[int, float]:
        original_idx, _entry, score_val = item
        if score_val is None:
            return (1, float(original_idx))
        return (0, -score_val)

    scored_rejects.sort(key=_sort_key)
    rejects = [entry for _, entry, _ in scored_rejects]
    scores = [score for _, _, score in scored_rejects]

    has_credit = any(
        _to_float((entry.get("metrics") or {}).get("credit")) is not None
        or _to_float((entry.get("metrics") or {}).get("net_credit")) is not None
        for entry in rejects
    )
    has_rr = any(
        _to_float((entry.get("metrics") or {}).get("max_profit")) is not None
        and _to_float((entry.get("metrics") or {}).get("max_loss")) not in {None, 0}
        for entry in rejects
    )
    has_pos = any(
        _to_float((entry.get("metrics") or {}).get("pos")) is not None for entry in rejects
    )
    has_ev = any(
        _to_float((entry.get("metrics") or {}).get("ev")) is not None
        or _to_float((entry.get("metrics") or {}).get("ev_pct")) is not None
        for entry in rejects
    )
    has_term = any(
        (entry.get("metrics") or {}).get("term") is not None for entry in rejects
    )
    has_flags = any((entry.get("meta") or {}) for entry in rejects)

    headers = ["#", "Strat", "Status", "Anchor", "Legs", "DTEs", "Note"]
    has_score = any(score is not None for score in scores)
    if has_score:
        headers.append("Score")
    if has_credit:
        headers.append("Net$")
    if has_rr:
        headers.append("R/R")
    if has_pos:
        headers.append("PoS")
    if has_ev:
        headers.append("EV€")
    if has_term:
        headers.append("Term")
    if has_flags:
        headers.append("Flags")

    rows: list[list[str]] = []
    for idx, (entry, score_val) in enumerate(zip(rejects, scores), start=1):
        strategy = str(entry.get("strategy") or "—")
        status = str(entry.get("status") or "—")
        anchor = str(entry.get("description") or "—")
        legs_raw = entry.get("legs")
        legs_seq = (
            list(legs_raw)
            if isinstance(legs_raw, Sequence) and not isinstance(legs_raw, (str, bytes))
            else []
        )
        dtes = _format_dtes(legs_seq)
        reason_value = entry.get("reason")
        raw_reason = entry.get("raw_reason")
        label = _reason_label(reason_value or raw_reason)
        note = str(label)

        row = [
            str(idx),
            strategy,
            status,
            anchor,
            _format_leg_summary(legs_seq),
            dtes,
            note,
        ]

        if has_score:
            row.append(f"{score_val:.2f}" if score_val is not None else "—")
        metrics = entry.get("metrics") or {}
        if has_credit:
            credit_val = metrics.get("credit")
            if credit_val in {None, ""}:
                credit_val = metrics.get("net_credit")
            row.append(_format_money(credit_val))
        if has_rr:
            max_profit = _to_float(metrics.get("max_profit"))
            max_loss = _to_float(metrics.get("max_loss"))
            if max_profit is not None and max_loss not in {None, 0}:
                try:
                    ratio = max_profit / abs(max_loss)
                    row.append(f"{ratio:.2f}")
                except Exception:
                    row.append("—")
            else:
                row.append("—")
        if has_pos:
            pos_val = _to_float(metrics.get("pos"))
            row.append(f"{pos_val:.1f}%" if pos_val is not None else "—")
        if has_ev:
            ev_val = _to_float(metrics.get("ev"))
            if ev_val is None:
                ev_pct = _to_float(metrics.get("ev_pct"))
                row.append(f"{ev_pct:.2f}%" if ev_pct is not None else "—")
            else:
                row.append(f"{ev_val:.2f}")
        if has_term:
            row.append(str(metrics.get("term") or "—"))
        if has_flags:
            meta = entry.get("meta") or {}
            if isinstance(meta, Mapping):
                parts = [f"{k}={v}" for k, v in meta.items()]
                row.append("; ".join(parts) if parts else "—")
            else:
                row.append(str(meta))

        rows.append(row)

    return headers, rows, rejects


def _show_rejection_detail(entry: Mapping[str, Any]) -> None:
    strategy = entry.get("strategy") or "—"
    status = entry.get("status") or "—"
    anchor = entry.get("description") or "—"
    reason_value = entry.get("reason")
    raw_reason = entry.get("raw_reason")
    detail = normalize_reason(reason_value or raw_reason)
    reason_label = detail.message or ReasonAggregator.label_for(detail.category)
    original = None
    if isinstance(reason_value, ReasonDetail):
        original = reason_value.data.get("original_message")
    if original is None:
        original = detail.data.get("original_message")
    note = raw_reason or original or reason_label

    print(f"Strategie: {strategy}")
    print(f"Status: {status}")
    print(f"Anchor: {anchor}")
    print(f"Reden: {reason_label}")
    if note and note != reason_label:
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
        dte_info = _format_dtes(legs_list)
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
                    _format_money(bid) if bid not in {None, ""} else "",
                    _format_money(ask) if ask not in {None, ""} else "",
                    _format_money(mid) if mid not in {None, ""} else "",
                ]
            )
        print("Legs:")
        print(tabulate(leg_rows, headers=headers, tablefmt="github"))

    proposal = _proposal_from_rejection(entry)
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
            _display_rejection_proposal(proposal, symbol_hint)
        else:
            print("❌ Ongeldige keuze")


def _proposal_from_rejection(entry: Mapping[str, Any]) -> StrategyProposal | None:
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

    proposal_kwargs: dict[str, Any] = {}
    allowed_fields = {field.name for field in fields(StrategyProposal) if field.init}
    allowed_fields.discard("strategy")
    allowed_fields.discard("legs")
    for key, value in metrics.items():
        if key in allowed_fields:
            proposal_kwargs[key] = value

    return StrategyProposal(strategy=strategy, legs=normalized_legs, **proposal_kwargs)


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


def _refresh_reject_entries(entries: Sequence[Mapping[str, Any]]) -> None:
    proposals: list[tuple[Mapping[str, Any], StrategyProposal, str | None]] = []
    for entry in entries:
        proposal = _proposal_from_rejection(entry)
        if not proposal:
            continue
        proposals.append((entry, proposal, _entry_symbol(entry)))

    if not proposals:
        print("⚠️ Geen geschikte voorstellen om te verversen.")
        return

    criteria_cfg = load_criteria()
    spot_price = SESSION_STATE.get("spot_price")
    try:
        timeout = float(cfg.get("MARKET_DATA_TIMEOUT", 15))
    except Exception:
        timeout = 15.0

    total = len(proposals)
    refreshed = 0
    accepted = 0
    failures = 0

    print(f"📡 Ververs orderinformatie via IB voor {total} voorstel(len)...")

    for entry, proposal, symbol in proposals:
        label_symbol = symbol or str(SESSION_STATE.get("symbol") or "—")
        try:
            result = fetch_quote_snapshot(
                proposal,
                criteria=criteria_cfg,
                spot_price=spot_price if isinstance(spot_price, (int, float)) else None,
                timeout=timeout,
            )
        except Exception as exc:  # pragma: no cover - IB afhankelijk
            failures += 1
            logger.exception("IB marktdata refresh mislukt: %s", exc)
            print(f"❌ {label_symbol} – {proposal.strategy}: {exc}")
            continue

        refreshed += 1
        if result.accepted:
            accepted += 1
            print(f"✅ {label_symbol} – {proposal.strategy}: voorstel voldoet na refresh.")
        else:
            reason_labels = ", ".join(_reason_label(reason) for reason in result.reasons)
            if not reason_labels:
                reason_labels = "Onbekende reden"
            print(
                "⚠️ "
                + f"{label_symbol} – {proposal.strategy}: afgewezen ({reason_labels})."
            )

        entry["refreshed_proposal"] = result.proposal
        entry["refreshed_reasons"] = result.reasons
        entry["refreshed_missing_quotes"] = result.missing_quotes
        entry["refreshed_accepted"] = result.accepted

    summary_parts = [f"{refreshed}/{total} ververst"]
    summary_parts.append(f"geaccepteerd: {accepted}")
    if failures:
        summary_parts.append(f"fouten: {failures}")
    print("Samenvatting: " + ", ".join(summary_parts))


def _display_rejection_proposal(proposal: StrategyProposal, symbol_hint: str | None) -> None:
    previous_symbol = SESSION_STATE.get("symbol")
    previous_strategy = SESSION_STATE.get("strategy")
    try:
        if symbol_hint:
            SESSION_STATE["symbol"] = symbol_hint
        SESSION_STATE["strategy"] = proposal.strategy
        _show_proposal_details(proposal)
    finally:
        if previous_symbol is None:
            SESSION_STATE.pop("symbol", None)
        else:
            SESSION_STATE["symbol"] = previous_symbol
        if previous_strategy is None:
            SESSION_STATE.pop("strategy", None)
        else:
            SESSION_STATE["strategy"] = previous_strategy


def _show_proposal_details(proposal: StrategyProposal) -> None:
    criteria_cfg = load_criteria()
    symbol = (
        str(SESSION_STATE.get("symbol") or proposal.legs[0].get("symbol", ""))
        if proposal.legs
        else str(SESSION_STATE.get("symbol") or "")
    )
    spot_price = SESSION_STATE.get("spot_price")
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

    rows: list[list[str]] = []
    warns: list[str] = []
    missing_quotes: list[str] = refresh_result.missing_quotes if refresh_result else []
    for leg in proposal.legs:
        if leg.get("edge") is None:
            logger.debug(
                f"[EDGE missing] {leg.get('position')} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')}"
            )
        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = leg.get("mid")
        if bid is None or ask is None:
            warns.append(f"⚠️ Bid/ask ontbreekt voor strike {leg.get('strike')}")
        if mid is not None:
            try:
                mid_f = float(mid)
                if bid is not None and math.isclose(mid_f, float(bid), abs_tol=1e-6):
                    warns.append(
                        f"⚠️ Midprijs gelijk aan bid voor strike {leg.get('strike')}"
                    )
                if ask is not None and math.isclose(mid_f, float(ask), abs_tol=1e-6):
                    warns.append(
                        f"⚠️ Midprijs gelijk aan ask voor strike {leg.get('strike')}"
                    )
            except Exception:
                pass

        missing_metrics = leg.get("missing_metrics") or []
        if missing_metrics:
            msg = (
                f"⚠️ Ontbrekende metrics voor strike {leg.get('strike')}: {', '.join(missing_metrics)}"
            )
            if leg.get("metrics_ignored"):
                msg += " (toegestaan)"
            warns.append(msg)

        rows.append(
            [
                leg.get("expiry"),
                leg.get("strike"),
                leg.get("type"),
                "S" if leg.get("position", 0) < 0 else "L",
                f"{bid:.2f}" if bid is not None else "—",
                f"{ask:.2f}" if ask is not None else "—",
                f"{mid:.2f}" if mid is not None else "—",
                (f"{leg.get('iv', 0):.2f}" if leg.get("iv") is not None else ""),
                (f"{leg.get('delta', 0):+.2f}" if leg.get("delta") is not None else ""),
                (f"{leg.get('gamma', 0):+.4f}" if leg.get("gamma") is not None else ""),
                (f"{leg.get('vega', 0):+.2f}" if leg.get("vega") is not None else ""),
                (f"{leg.get('theta', 0):+.2f}" if leg.get("theta") is not None else ""),
            ]
        )
    missing_edge = any(leg.get("edge") is None for leg in proposal.legs)

    print(
        tabulate(
            rows,
            headers=[
                "Expiry",
                "Strike",
                "Type",
                "Pos",
                "Bid",
                "Ask",
                "Mid",
                "IV",
                "Delta",
                "Gamma",
                "Vega",
                "Theta",
            ],
            tablefmt="github",
        )
    )
    if missing_quotes:
        warns.append("⚠️ Geen verse quotes voor: " + ", ".join(missing_quotes))
    if missing_edge:
        warns.append("⚠️ Eén of meerdere edges niet beschikbaar")
    if getattr(proposal, "credit_capped", False):
        warns.append(
            "⚠️ Credit afgetopt op theoretisch maximum vanwege ontbrekende bid/ask"
        )
    for warning in warns:
        print(warning)

    rr_value: float | None = None
    try:
        profit_val = float(proposal.max_profit) if proposal.max_profit is not None else None
    except Exception:
        profit_val = None
    try:
        loss_val = float(proposal.max_loss) if proposal.max_loss is not None else None
    except Exception:
        loss_val = None
    if profit_val is not None and loss_val not in (None, 0):
        risk = abs(loss_val)
        if risk > 0:
            rr_value = profit_val / risk

    score_str = f"{proposal.score:.2f}" if proposal.score is not None else "—"
    ev_str = f"{proposal.ev:.2f}" if proposal.ev is not None else "—"
    rr_str = f"{rr_value:.2f}" if rr_value is not None else "—"
    prefix = "IB-update → " if refresh_result else "Metrics → "
    print(f"{prefix}Score: {score_str} | EV: {ev_str} | R/R: {rr_str}")

    acceptance_failed = bool(refresh_result and not refresh_result.accepted)
    if acceptance_failed:
        print("❌ Acceptatiecriteria niet gehaald na IB-refresh.")
        for detail in refresh_result.reasons:
            msg = getattr(detail, "message", None) or getattr(detail, "code", None)
            if msg:
                print(f"  - {msg}")

    if missing_edge and not cfg.get("ALLOW_INCOMPLETE_METRICS", False):
        if not prompt_yes_no(
            "⚠️ Deze strategie bevat onvolledige edge-informatie. Toch accepteren?",
            False,
        ):
            return
    if proposal.credit is not None:
        print(f"Credit: {proposal.credit:.2f}")
    else:
        print("Credit: —")
    if proposal.margin is not None:
        print(f"Margin: {proposal.margin:.2f}")
    else:
        print("Margin: —")
    max_win = f"{proposal.max_profit:.2f}" if proposal.max_profit is not None else "—"
    print(f"Max win: {max_win}")
    max_loss = f"{proposal.max_loss:.2f}" if proposal.max_loss is not None else "—"
    print(f"Max loss: {max_loss}")
    if proposal.breakevens:
        be = ", ".join(f"{b:.2f}" for b in proposal.breakevens)
        print(f"Breakevens: {be}")
    pos_str = f"{proposal.pos:.2f}" if proposal.pos is not None else "—"
    print(f"PoS: {pos_str}")

    label = None
    if getattr(proposal, "scenario_info", None):
        label = proposal.scenario_info.get("scenario_label")
        if proposal.scenario_info.get("error") == "no scenario defined":
            print("no scenario defined")

    suffix = ""
    if proposal.profit_estimated:
        suffix = f" {label} (geschat)" if label else " (geschat)"

    rom_str = f"{proposal.rom:.2f}" if proposal.rom is not None else "—"
    print(f"ROM: {rom_str}{suffix}")
    ev_display = f"{proposal.ev:.2f}" if proposal.ev is not None else "—"
    print(f"EV: {ev_display}{suffix}")
    if prompt_yes_no("Voorstel opslaan naar CSV?", False):
        _export_proposal_csv(proposal)
    if prompt_yes_no("Voorstel opslaan naar JSON?", False):
        _export_proposal_json(proposal)

    can_send_order = not acceptance_failed and not fetch_only_mode
    if can_send_order and prompt_yes_no("Order naar IB sturen?", False):
        _submit_ib_order(proposal, symbol=symbol)
    elif fetch_only_mode:
        print("ℹ️ fetch_only modus actief – orders worden niet verstuurd.")

    journal = _proposal_journal_text(proposal)
    print("\nJournal entry voorstel:\n" + journal)


def _submit_ib_order(proposal: StrategyProposal, *, symbol: str | None = None) -> None:
    ticker = symbol or str(SESSION_STATE.get("symbol") or "")
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


def _save_trades(trades: list[dict[str, object]]) -> None:
    symbol = str(SESSION_STATE.get("symbol", "SYMB"))
    strat = str(SESSION_STATE.get("strategy", "strategy")).replace(" ", "_")
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


def _export_proposal_csv(proposal: StrategyProposal) -> None:
    symbol = str(SESSION_STATE.get("symbol", "SYMB"))
    strat = str(SESSION_STATE.get("strategy", "strategy")).replace(" ", "_")
    base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = base / f"strategy_proposal_{symbol}_{strat}_{ts}.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
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
        )
        for leg in proposal.legs:
            writer.writerow(
                [
                    leg.get("expiry"),
                    leg.get("strike"),
                    leg.get("type"),
                    leg.get("position"),
                    leg.get("bid"),
                    leg.get("ask"),
                    leg.get("mid"),
                    leg.get("delta"),
                    leg.get("theta"),
                    leg.get("vega"),
                    leg.get("edge"),
                    leg.get("manual_override"),
                    ",".join(leg.get("missing_metrics") or []),
                    leg.get("metrics_ignored"),
                ]
            )
        writer.writerow([])
        summary_rows = [
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
            (
                "scenario_info",
                json.dumps(proposal.scenario_info) if proposal.scenario_info is not None else None,
            ),
            ("breakevens", json.dumps(proposal.breakevens or [])),
            ("atr", proposal.atr),
            ("iv_rank", proposal.iv_rank),
            ("iv_percentile", proposal.iv_percentile),
            ("hv20", proposal.hv20),
            ("hv30", proposal.hv30),
            ("hv90", proposal.hv90),
            ("dte", json.dumps(proposal.dte) if proposal.dte is not None else None),
            (
                "breakeven_distances",
                json.dumps(proposal.breakeven_distances or {"dollar": [], "percent": []}),
            ),
            (
                "wing_width",
                json.dumps(proposal.wing_width) if proposal.wing_width is not None else None,
            ),
            ("wing_symmetry", proposal.wing_symmetry),
        ]
        for key, value in summary_rows:
            writer.writerow([key, value])
    print(f"✅ Voorstel opgeslagen in: {path.resolve()}")


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


def _export_proposal_json(proposal: StrategyProposal) -> None:
    symbol = str(SESSION_STATE.get("symbol", "SYMB"))
    strategy_name = str(SESSION_STATE.get("strategy", "strategy"))
    strat_file = strategy_name.replace(" ", "_")
    base = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    path = base / f"strategy_proposal_{symbol}_{strat_file}_{ts}.json"

    accept = _load_acceptance_criteria(strat_file)
    portfolio_ctx, portfolio_available = _load_portfolio_context()
    spot_price = SESSION_STATE.get("spot_price")

    earnings_dict = load_json(
        cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
    )
    next_earn = None
    if isinstance(earnings_dict, dict):
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
        "strategy": strat_file,
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
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Voorstel opgeslagen in: {path.resolve()}")


def _proposal_journal_text(proposal: StrategyProposal) -> str:
    margin_str = f"{proposal.margin:.2f}" if proposal.margin is not None else "—"
    pos_str = f"{proposal.pos:.2f}" if proposal.pos is not None else "—"
    rom_str = f"{proposal.rom:.2f}" if proposal.rom is not None else "—"
    ev_str = f"{proposal.ev:.2f}" if proposal.ev is not None else "—"
    lines = [
        f"Symbol: {SESSION_STATE.get('symbol')}",
        f"Strategy: {SESSION_STATE.get('strategy')}",
        f"Credit: {proposal.credit:.2f}",
        f"Margin: {margin_str}",
        f"ROM: {rom_str}",
        f"PoS: {pos_str}",
        f"EV: {ev_str}",
    ]
    for leg in proposal.legs:
        side = "Short" if leg.get("position", 0) < 0 else "Long"
        mid = leg.get("mid")
        mid_str = f"{mid:.2f}" if mid is not None else ""
        lines.append(
            f"{side} {leg.get('type')} {leg.get('strike')} {leg.get('expiry')} @ {mid_str}"
        )
    return "\n".join(lines)


def _print_reason_summary(summary: RejectionSummary | None) -> None:
    """Display aggregated rejection information."""

    entries = SESSION_STATE.get("combo_evaluations")
    if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
        eval_entries = list(entries)
    else:
        eval_entries = []
    headers, rows, rejects = _build_rejection_table(eval_entries)

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
                    print(f"• {_reason_label(r)}")

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
            _refresh_reject_entries(rejects)
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
        _show_rejection_detail(rejects[idx - 1])
        print()


SHOW_REASONS = False


PIPELINE: StrategyPipeline | None = None


def _get_strategy_pipeline() -> StrategyPipeline:
    global PIPELINE
    if PIPELINE is None:
        PIPELINE = StrategyPipeline(
            cfg,
            None,
            strike_selector_factory=_strike_selector_factory,
            strategy_generator=_generate_with_capture,
        )
    return PIPELINE


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


def run_dataexporter() -> None:
    """Menu for export and CSV validation utilities."""

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
            path = services.fetch_polygon_chain(symbol)
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
            changed = services.git_commit(
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
            changed = services.git_commit(
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


def run_portfolio_menu() -> None:
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

        factsheet = _build_factsheet(chosen)
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

        snapshot = MARKET_SNAPSHOT_SERVICE.load_snapshot({"symbols": symbols})

        def _as_overview_row(data: dict[str, object]) -> list[object]:
            return [
                data.get("symbol"),
                data.get("spot"),
                data.get("iv"),
                data.get("hv20"),
                data.get("hv30"),
                data.get("hv90"),
                data.get("hv252"),
                data.get("iv_rank"),
                data.get("iv_percentile"),
                data.get("term_m1_m2"),
                data.get("term_m1_m3"),
                data.get("skew"),
                data.get("next_earnings"),
                data.get("days_until_earnings"),
            ]

        rows = [_as_overview_row(row) for row in snapshot.get("rows", [])]

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

            pipeline = _get_strategy_pipeline()
            config_data = cfg.get("STRATEGY_CONFIG") or {}
            results: list[dict[str, Any]] = []

            def _find_existing_chain(directory: Path, symbol: str) -> Path | None:
                upper = symbol.upper()
                patterns = [
                    f"{upper}_*-optionchainpolygon.csv",
                    f"option_chain_{upper}_*.csv",
                    f"{upper}_*-optionchain.csv",
                ]
                matches: list[Path] = []
                for pattern in patterns:
                    try:
                        matches.extend(directory.rglob(pattern))
                    except Exception as exc:
                        print(f"⚠️ Kon niet zoeken in {directory}: {exc}")
                        return None
                if not matches:
                    return None
                return max(matches, key=lambda p: p.stat().st_mtime)

            for symbol, symbol_recs in grouped.items():
                if existing_chain_dir:
                    chain_path = _find_existing_chain(existing_chain_dir, symbol)
                    if not chain_path:
                        print(
                            f"ℹ️ Geen bestaande optionchain gevonden voor {symbol} in {existing_chain_dir}"
                        )
                        continue
                else:
                    chain_path = services.fetch_polygon_chain(symbol)
                    if not chain_path:
                        print(f"⚠️ Geen polygon chain gevonden voor {symbol}")
                        continue
                if existing_chain_dir:
                    print(f"📄 Gebruik bestaande chain voor {symbol}: {chain_path.name}")
                try:
                    df = pd.read_csv(chain_path)
                except Exception as exc:
                    print(f"⚠️ Kon chain voor {symbol} niet laden: {exc}")
                    continue
                df.columns = [c.lower() for c in df.columns]
                df = normalize_european_number_format(
                    df,
                    [
                        "bid",
                        "ask",
                        "close",
                        "iv",
                        "delta",
                        "gamma",
                        "vega",
                        "theta",
                        "mid",
                    ],
                )
                if "expiry" not in df.columns and "expiration" in df.columns:
                    df = df.rename(columns={"expiration": "expiry"})
                elif "expiry" in df.columns and "expiration" in df.columns:
                    df = df.drop(columns=["expiration"])
                if "expiry" in df.columns:
                    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime(
                        "%Y-%m-%d"
                    )
                chain_records = [
                    normalize_leg(rec) for rec in df.to_dict(orient="records")
                ]
                if not chain_records:
                    print(f"⚠️ Geen optiedata beschikbaar voor {symbol}")
                    continue

                spot_price = refresh_spot_price(symbol)
                if spot_price is None or spot_price <= 0:
                    spot_price = _load_spot_from_metrics(chain_path.parent, symbol)
                if spot_price is None or spot_price <= 0:
                    spot_price, _ = _load_latest_close(symbol)
                if spot_price is None or spot_price <= 0:
                    spot_price = _spot_from_chain(chain_records)
                if spot_price is None or spot_price <= 0:
                    print(f"⚠️ Geen geldige spotprijs voor {symbol}")
                    continue

                atr_val = latest_atr(symbol) or 0.0

                for rec in symbol_recs:
                    raw_strategy = str(rec.get("strategy") or "")
                    strategy = raw_strategy.lower().replace(" ", "_")
                    if not strategy:
                        continue
                    rules = load_strike_config(strategy, config_data) if config_data else {}
                    dte_range = rules.get("dte_range") or [0, 365]
                    try:
                        dte_tuple = (int(dte_range[0]), int(dte_range[1]))
                    except Exception:
                        dte_tuple = (0, 365)
                    filtered = filter_by_expiry(list(chain_records), dte_tuple)
                    if not filtered:
                        continue
                    earnings_value = rec.get("next_earnings")
                    earnings_date = None
                    if isinstance(earnings_value, date):
                        earnings_date = earnings_value
                    elif isinstance(earnings_value, str):
                        earnings_date = parse_date(earnings_value)
                    context = StrategyContext(
                        symbol=symbol,
                        strategy=strategy,
                        option_chain=filtered,
                        spot_price=float(spot_price),
                        atr=float(atr_val),
                        config=config_data or {},
                        interest_rate=float(cfg.get("INTEREST_RATE", 0.05)),
                        dte_range=dte_tuple,
                        interactive_mode=False,
                        next_earnings=earnings_date,
                    )
                    proposals, _ = pipeline.build_proposals(context)
                    for proposal in proposals:
                        if proposal.score is None:
                            continue
                        results.append(
                            {
                                "symbol": symbol,
                                "strategy": raw_strategy,
                                "proposal": proposal,
                                "metrics": rec,
                                "spot": spot_price,
                            }
                        )

            if not results:
                print("⚠️ Geen voorstellen gevonden tijdens scan.")
                return

            def _avg_bid_ask_pct(proposal: StrategyProposal) -> float | None:
                spreads: list[float] = []
                for leg in proposal.legs:
                    bid = _to_float(leg.get("bid"))
                    ask = _to_float(leg.get("ask"))
                    if bid is None or ask is None:
                        continue
                    mid = (bid + ask) / 2
                    if math.isclose(mid, 0.0):
                        base = ask
                    else:
                        base = mid
                    if base in {None, 0} or math.isclose(base, 0.0):
                        continue
                    spreads.append(((ask - bid) / base) * 100)
                if not spreads:
                    return None
                return sum(spreads) / len(spreads)

            def _risk_reward(proposal: StrategyProposal) -> float | None:
                profit = _to_float(proposal.max_profit)
                loss = _to_float(proposal.max_loss)
                if profit is None or loss in {None, 0}:
                    return None
                risk = abs(loss)
                if risk <= 0:
                    return None
                return profit / risk

            def _mid_sources(proposal: StrategyProposal) -> str:
                fallback = getattr(proposal, "fallback", None)
                if isinstance(fallback, str) and fallback.strip():
                    return fallback
                sources: set[str] = set()
                for leg in proposal.legs:
                    src = str(leg.get("mid_fallback") or leg.get("mid_source") or "").strip()
                    if src:
                        sources.add(src)
                if not sources:
                    return "quotes"
                return ",".join(sorted(sources))

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

            results.sort(key=lambda item: item["proposal"].score or 0.0, reverse=True)
            top_results = results[:top_n]

            rows_out: list[list[str]] = []
            for idx, item in enumerate(top_results, 1):
                prop = item["proposal"]
                metrics = item["metrics"]
                iv_rank_raw = metrics.get("iv_rank")
                try:
                    iv_rank_pct = float(iv_rank_raw) * 100 if iv_rank_raw is not None else None
                except Exception:
                    iv_rank_pct = None
                skew_raw = metrics.get("skew")
                try:
                    skew_fmt = f"{float(skew_raw):.2f}" if skew_raw is not None else "—"
                except Exception:
                    skew_fmt = "—"
                earnings_raw = metrics.get("next_earnings")
                earnings = (
                    str(earnings_raw)
                    if earnings_raw not in {None, ""}
                    else "—"
                )
                rows_out.append(
                    [
                        idx,
                        item["symbol"],
                        item["strategy"],
                        _fmt_money(prop.score),
                        _fmt_money(prop.ev),
                        _fmt_ratio(_risk_reward(prop)),
                        _format_dtes(prop.legs),
                        _fmt_pct(iv_rank_pct),
                        skew_fmt,
                        _fmt_pct(_avg_bid_ask_pct(prop)),
                        _mid_sources(prop),
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
                    chosen = top_results[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                SESSION_STATE.update(
                    {
                        "symbol": chosen["symbol"],
                        "strategy": chosen["strategy"],
                        "spot_price": chosen.get("spot"),
                    }
                )
                _show_proposal_details(chosen["proposal"])
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
                SESSION_STATE.update(chosen)
                print(
                    f"\n🎯 Gekozen strategie: {SESSION_STATE.get('symbol')} – {SESSION_STATE.get('strategy')}\n"
                )
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
        for row in snapshot.get("rows", []):
            formatted_rows.append(
                [
                    row.get("symbol"),
                    row.get("spot"),
                    fmt4(row.get("iv")),
                    fmt4(row.get("hv20")),
                    fmt4(row.get("hv30")),
                    fmt4(row.get("hv90")),
                    fmt4(row.get("hv252")),
                    fmt2(row.get("iv_rank")),
                    fmt2(row.get("iv_percentile")),
                    row.get("term_m1_m2"),
                    row.get("term_m1_m3"),
                    row.get("skew"),
                    row.get("next_earnings"),
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
        if not path.exists():
            print("⚠️ Chain-bestand ontbreekt")
            return

        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"⚠️ Fout bij laden van chain: {exc}")
            return
        df.columns = [c.lower() for c in df.columns]
        df = normalize_european_number_format(
            df,
            [
                "bid",
                "ask",
                "close",
                "iv",
                "delta",
                "gamma",
                "vega",
                "theta",
                "mid",
            ],
        )
        if "expiry" not in df.columns and "expiration" in df.columns:
            df = df.rename(columns={"expiration": "expiry"})
        elif "expiry" in df.columns and "expiration" in df.columns:
            df = df.drop(columns=["expiration"])

        if "expiry" in df.columns:
            df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
        logger.info(f"Loaded {len(df)} rows from {path}")

        quality = calculate_csv_quality(df)
        min_q = cfg.get("CSV_MIN_QUALITY", 70)
        if quality < min_q:
            print(f"⚠️ CSV kwaliteit {quality:.1f}% lager dan {min_q}%")
        else:
            print(f"CSV kwaliteit {quality:.1f}%")
        logger.info(f"CSV loaded from {path} with quality {quality:.1f}%")
        if not prompt_yes_no("Doorgaan?", False):
            return
        do_interpolate = prompt_yes_no(
            "Wil je delta/iv interpoleren om de data te verbeteren?", False
        )
        if do_interpolate:
            logger.info(
                "Interpolating missing delta/iv values using linear (delta) and spline (iv)"
            )
            df = interpolate_missing_fields(df)
            print("✅ Interpolatie toegepast op ontbrekende delta/iv.")
            logger.info("Interpolation completed successfully")
            quality = calculate_csv_quality(df)
            print(f"Nieuwe CSV kwaliteit {quality:.1f}%")
            new_path = path.with_name(path.stem + "_interpolated.csv")
            df.to_csv(new_path, index=False)
            logger.info(f"Interpolated CSV saved to {new_path}")
            path = new_path
        data = [normalize_leg(rec) for rec in df.to_dict(orient="records")]
        symbol = str(SESSION_STATE.get("symbol", ""))
        spot_price = refresh_spot_price(symbol)
        if spot_price is None or spot_price <= 0:
            spot_price = _load_spot_from_metrics(path.parent, symbol)
        if spot_price is None or spot_price <= 0:
            spot_price, _ = _load_latest_close(symbol)
        if spot_price is None or spot_price <= 0:
            spot_price = _spot_from_chain(data)
        SESSION_STATE["spot_price"] = spot_price
        exp_counts: dict[str, int] = {}
        for row in data:
            exp = row.get("expiry")
            if exp:
                exp_counts[exp] = exp_counts.get(exp, 0) + 1
        for exp, cnt in exp_counts.items():
            logger.info(f"- {exp}: {cnt} options in CSV")

        strat = str(SESSION_STATE.get("strategy", "")).lower().replace(" ", "_")
        config_data = cfg.get("STRATEGY_CONFIG") or {}
        rules = load_strike_config(strat, config_data) if config_data else {}
        dte_range = rules.get("dte_range") or [0, 365]
        try:
            dte_tuple = (int(dte_range[0]), int(dte_range[1]))
        except Exception:
            dte_tuple = (0, 365)

        filtered = filter_by_expiry(data, dte_tuple)

        after_counts: dict[str, int] = {}
        for row in filtered:
            exp = row.get("expiry")
            if exp:
                after_counts[exp] = after_counts.get(exp, 0) + 1
        kept_expiries = set(after_counts)
        for exp, cnt in after_counts.items():
            logger.info(f"- {exp}: {cnt} options after DTE filter")
        for exp in exp_counts:
            if exp not in kept_expiries:
                logger.info(f"- {exp}: skipped (outside DTE range)")

        pipeline = _get_strategy_pipeline()
        atr_val = latest_atr(symbol) or 0.0
        spot_for_pipeline = SESSION_STATE.get("spot_price")
        if spot_for_pipeline is None or spot_for_pipeline <= 0:
            spot_for_pipeline = _spot_from_chain(data)
        context = StrategyContext(
            symbol=symbol,
            strategy=strat,
            option_chain=filtered,
            spot_price=float(spot_for_pipeline or 0.0),
            atr=atr_val,
            config=config_data or {},
            interest_rate=float(cfg.get("INTEREST_RATE", 0.05)),
            dte_range=dte_tuple,
            interactive_mode=True,
            debug_path=Path(cfg.get("EXPORT_DIR", "exports")) / "PEP_debugfilter.csv",
        )
        proposals, summary = pipeline.build_proposals(context)
        evaluation_summary = SESSION_STATE.get("combo_evaluation_summary")
        if isinstance(evaluation_summary, EvaluationSummary) or evaluation_summary is None:
            _print_evaluation_overview(context.symbol, context.spot_price, evaluation_summary)
        filter_preview = RejectionSummary(
            by_filter=dict(summary.by_filter), by_reason=dict(summary.by_reason)
        )
        _print_reason_summary(filter_preview)

        evaluated = pipeline.last_evaluated
        SESSION_STATE["evaluated_trades"] = evaluated
        SESSION_STATE["spot_price"] = context.spot_price

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
                _save_trades(evaluated)
            if prompt_yes_no("Doorgaan naar strategie voorstellen?", False):
                global SHOW_REASONS
                SHOW_REASONS = True

                latest_spot = refresh_spot_price(symbol)
                if isinstance(latest_spot, (int, float)) and latest_spot > 0:
                    SESSION_STATE["spot_price"] = float(latest_spot)
                    context.spot_price = float(latest_spot)

                if context.spot_price > 0:
                    print(f"Spotprice: {context.spot_price:.2f}")
                else:
                    print("Spotprice: onbekend")

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
                        _print_reason_summary(summary)
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
                        _show_proposal_details(chosen_prop)
                        break
                else:
                    print("⚠️ Geen voorstellen gevonden")
                    _print_reason_summary(summary)
        else:
            print("⚠️ Geen geschikte strikes gevonden.")
            _print_reason_summary(summary)
            print("➤ Controleer of de juiste expiraties beschikbaar zijn in de chain.")
            print("➤ Of pas je selectiecriteria aan in strike_selection_rules.yaml.")

    def choose_chain_source() -> None:
        symbol = SESSION_STATE.get("symbol")
        if not symbol:
            print("⚠️ Geen strategie geselecteerd")
            return

        def use_ib() -> None:
            path = services.export_chain(str(symbol))
            if not path:
                print("⚠️ Geen chain gevonden")
                return
            _process_chain(path)

        def use_polygon() -> None:
            path = services.fetch_polygon_chain(str(symbol))
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

    menu = Menu("TOMIC CONTROL PANEL", exit_text="Stoppen")
    menu.add("Analyse & Strategie", run_portfolio_menu)
    menu.add("Data & Marktdata", run_dataexporter)
    menu.add("Trades & Journal", run_trade_management)
    menu.add("Risicotools & Synthetica", run_risk_tools)
    menu.add("Configuratie", run_settings_menu)
    menu.run()
    print("Tot ziens.")


if __name__ == "__main__":
    main(sys.argv[1:])
