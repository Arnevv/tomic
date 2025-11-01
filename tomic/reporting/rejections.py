"""Utilities for aggregating and formatting rejection data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Any, Iterable, Mapping, Sequence

from tomic.helpers.dateutils import parse_date
from tomic.helpers.numeric import safe_float
from tomic.logutils import logger
from tomic.reporting._formatting import format_leg_position
from tomic.strategy.reasons import (
    ReasonCategory,
    ReasonDetail,
    ReasonLike,
    normalize_reason,
    category_label,
    category_priority,
)
from tomic.utils import today


@dataclass
class ReasonAggregator:
    """Collect frequency counts for rejection reasons."""

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
            extras = " · ".join(
                f"{name} {count}" for name, count in sorted(self.other.items())
            )
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
            if isinstance(extra_expiry, Sequence) and not isinstance(
                extra_expiry, (str, bytes)
            ):
                expiries.update(extra_expiry)
            elif extra_expiry is not None:
                expiries.add(extra_expiry)
    if not expiries:
        return "Onbekend", None
    labels = [_normalize_expiry_value(value) for value in expiries]
    labels.sort(key=lambda item: (item[1] or date.max, item[0] or ""))
    primary_label, sort_key = labels[0]
    if primary_label is None:
        return "Onbekend", sort_key
    return primary_label, sort_key


def summarize_evaluations(
    evaluations: Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]]
) -> EvaluationSummary | None:
    entries = list(evaluations)
    if not entries:
        return None
    summary = EvaluationSummary(total=len(entries))
    for entry in entries:
        label, sort_key = _resolve_expiry_label(entry)
        breakdown = summary.expiries.get(label)
        if breakdown is None:
            breakdown = ExpiryBreakdown(label=label, sort_key=sort_key)
            summary.expiries[label] = breakdown
        status = str(entry.get("status", "")) if isinstance(entry, Mapping) else ""
        breakdown.add(status)
        if status.strip().lower() == "reject":
            summary.rejects += 1
            reason: ReasonLike | None = None
            if isinstance(entry, Mapping):
                reason = entry.get("reason")
                if reason is None:
                    reason = entry.get("raw_reason")
            summary.reasons.add_reason(reason)
    return summary


def format_reject_reasons(summary: EvaluationSummary) -> str:
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


def reason_label(value: ReasonLike | ReasonDetail | None) -> str:
    try:
        detail = normalize_reason(value)
    except Exception:
        return str(value)
    return detail.message or ReasonAggregator.label_for(detail.category)


def to_float(value: Any) -> float | None:
    return safe_float(value)


def format_money(value: Any) -> str:
    num = to_float(value)
    if num is None:
        return "—"
    return f"{num:.2f}"


def _format_leg_summary(legs: Sequence[Mapping[str, Any]] | None) -> str:
    if not legs:
        return "—"
    parts: list[str] = []
    for leg in legs:
        typ = str(leg.get("type") or "").upper()[:1]
        strike = leg.get("strike")
        pos = format_leg_position(leg.get("position"))
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


def format_dtes(legs: Sequence[Mapping[str, Any]] | None) -> str:
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


def build_rejection_table(
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
            score_val = to_float(metrics.get("score"))
        else:
            score_val = None
        if score_val is None:
            score_val = to_float(entry.get("score"))
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
        to_float((entry.get("metrics") or {}).get("credit")) is not None
        or to_float((entry.get("metrics") or {}).get("net_credit")) is not None
        for entry in rejects
    )
    has_rr = any(
        to_float((entry.get("metrics") or {}).get("max_profit")) is not None
        and to_float((entry.get("metrics") or {}).get("max_loss")) not in {None, 0}
        for entry in rejects
    )
    has_pos = any(
        to_float((entry.get("metrics") or {}).get("pos")) is not None
        for entry in rejects
    )
    has_ev = any(
        to_float((entry.get("metrics") or {}).get("ev")) is not None
        or to_float((entry.get("metrics") or {}).get("ev_pct")) is not None
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
        dtes = format_dtes(legs_seq)
        reason_value = entry.get("reason")
        raw_reason = entry.get("raw_reason")
        label = reason_label(reason_value or raw_reason)
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
            row.append(format_money(credit_val))
        if has_rr:
            max_profit = to_float(metrics.get("max_profit"))
            max_loss = to_float(metrics.get("max_loss"))
            if max_profit is not None and max_loss not in {None, 0}:
                try:
                    ratio = max_profit / abs(max_loss)
                    row.append(f"{ratio:.2f}")
                except Exception:
                    row.append("—")
            else:
                row.append("—")
        if has_pos:
            pos_val = to_float(metrics.get("pos"))
            row.append(f"{pos_val:.1f}%" if pos_val is not None else "—")
        if has_ev:
            ev_val = metrics.get("ev")
            if ev_val in {None, ""}:
                ev_val = metrics.get("ev_pct")
            row.append(format_money(ev_val))
        if has_term:
            row.append(str((entry.get("metrics") or {}).get("term") or "—"))
        if has_flags:
            meta = entry.get("meta") or {}
            if isinstance(meta, Mapping):
                flag_parts = [
                    f"{key}={value}"
                    for key, value in sorted(meta.items())
                    if value not in (None, "")
                ]
                row.append(", ".join(flag_parts) if flag_parts else "—")
            else:
                row.append("—")
        rows.append(row)

    return headers, rows, rejects
