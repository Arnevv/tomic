"""Helpers translating mid usage summaries into tradeability decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ..mid_resolver import MidUsageSummary
from .reasons import (
    ReasonCategory,
    ReasonDetail,
    make_reason,
    reason_from_mid_source,
)


@dataclass(frozen=True)
class ReasonEvaluation:
    """Result produced by :class:`ReasonEngine`."""

    summary: MidUsageSummary
    status: str
    needs_refresh: bool
    fallback_summary: Mapping[str, int]
    tags: tuple[str, ...]
    reasons: tuple[ReasonDetail, ...]
    preview_sources: tuple[str, ...]
    fallback_limit_exceeded: bool = False


class ReasonEngine:
    """Convert mid usage statistics into canonical status and reasons."""

    def __init__(self, *, auto_refresh_on_preview: bool = True) -> None:
        self._auto_refresh_on_preview = bool(auto_refresh_on_preview)

    def evaluate(
        self,
        summary: MidUsageSummary,
        *,
        existing_reasons: Sequence[ReasonDetail] | None = None,
        needs_refresh: bool = False,
    ) -> ReasonEvaluation:
        reasons_map: dict[str, ReasonDetail] = {}
        ordered: list[ReasonDetail] = []
        for detail in existing_reasons or ():
            if isinstance(detail, ReasonDetail):
                code = detail.code or f"reason_{len(reasons_map)}"
                if code not in reasons_map:
                    reasons_map[code] = detail
                    ordered.append(detail)

        def _add_reason(detail: ReasonDetail | None) -> None:
            if detail is None:
                return
            code = detail.code or f"reason_{len(reasons_map)}"
            if code in reasons_map:
                return
            reasons_map[code] = detail
            ordered.append(detail)

        fallback_summary = dict(summary.fallback_summary)
        preview_sources = summary.preview_sources

        for source in preview_sources:
            detail = reason_from_mid_source(source)
            _add_reason(detail)

        status = "tradable"
        fallback_limit_exceeded = (
            summary.fallback_allowed is not None
            and summary.fallback_allowed >= 0
            and summary.fallback_count > summary.fallback_allowed
        )

        if summary.preview_leg_count > 0:
            status = "advisory"
        if fallback_limit_exceeded:
            status = "rejected"
            _add_reason(
                make_reason(
                    ReasonCategory.POLICY_VIOLATION,
                    "MID_FALLBACK_LIMIT",
                    "te veel fallback-legs",
                    data={
                        "fallback_leg_count": summary.fallback_count,
                        "fallback_allowed": summary.fallback_allowed,
                    },
                )
            )
        if summary.spread_too_wide_count > 0:
            status = "rejected"
            _add_reason(
                make_reason(
                    ReasonCategory.WIDE_SPREAD,
                    "MID_SPREAD_WIDE",
                    "spread te wijd",
                    data={"legs": summary.spread_too_wide_count},
                )
            )
        if summary.one_sided_count > 0:
            status = "rejected"
            _add_reason(
                make_reason(
                    ReasonCategory.LOW_LIQUIDITY,
                    "MID_ONE_SIDED",
                    "one sided quotes",
                    data={"legs": summary.one_sided_count},
                )
            )
        if summary.missing_mid_count > 0:
            status = "rejected"
            _add_reason(
                make_reason(
                    ReasonCategory.MISSING_DATA,
                    "MID_MISSING",
                    "mid ontbreekt",
                    data={"legs": summary.missing_mid_count},
                )
            )

        effective_refresh = bool(
            needs_refresh
            or (self._auto_refresh_on_preview and summary.preview_leg_count > 0)
        )

        tags: list[str] = [status]
        if effective_refresh:
            tags.append("needs_refresh")
        if summary.spread_too_wide_count > 0:
            tags.append(f"spread_wide:{summary.spread_too_wide_count}")
        if summary.one_sided_count > 0:
            tags.append(f"one_sided:{summary.one_sided_count}")
        if summary.missing_mid_count > 0:
            tags.append(f"mid_missing:{summary.missing_mid_count}")
        if fallback_limit_exceeded:
            tags.append(
                f"fallback_limit:{summary.fallback_count}/{summary.fallback_allowed}"
            )
        for source, count in sorted(fallback_summary.items()):
            if count > 0:
                tags.append(f"{source}:{count}")

        return ReasonEvaluation(
            summary=summary,
            status=status,
            needs_refresh=effective_refresh,
            fallback_summary=fallback_summary,
            tags=tuple(tags),
            reasons=tuple(ordered),
            preview_sources=preview_sources,
            fallback_limit_exceeded=fallback_limit_exceeded,
        )


__all__ = ["ReasonEngine", "ReasonEvaluation"]
