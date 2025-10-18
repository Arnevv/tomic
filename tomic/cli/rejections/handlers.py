"""Interactive helpers for inspecting and refreshing rejected strategies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

from tomic.cli.common import prompt, prompt_yes_no
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.cli.app_services import ControlPanelServices
from tomic.logutils import logger, normalize_reason
from tomic.reporting import (
    ReasonAggregator,
    build_rejection_table as _reporting_build_rejection_table,
    format_dtes,
    reason_label,
)
from tomic.services.pipeline_refresh import (
    ORIGINAL_INDEX_KEY,
    RefreshContext,
    RefreshParams,
    RefreshSource,
    Proposal as RefreshProposal,
    build_proposal_from_entry,
    refresh_pipeline,
)
from tomic.services.proposal_details import (
    ProposalCore,
    ProposalVM,
    build_proposal_viewmodel,
)
from tomic.services.strategy_pipeline import RejectionSummary, StrategyProposal
from tomic.strategy.reasons import ReasonDetail
from tomic.criteria import load_criteria
from tomic.formatting import PROPOSALS_SPEC, proposals_table, sort_records

try:  # pragma: no cover - optional dependency guard
    from tabulate import tabulate as _default_tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

    def _default_tabulate(
        rows: Sequence[Sequence[Any]],
        headers: Sequence[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        table_rows: list[Sequence[Any]] = list(rows)
        if headers:
            table_rows = [headers, *table_rows]
        widths = [max(len(str(cell)) for cell in column) for column in zip(*table_rows)] if table_rows else []

        def _fmt(row: Sequence[Any]) -> str:
            return "| " + " | ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row)) + " |"

        lines: list[str] = []
        if headers:
            lines.append(_fmt(headers))
            separator = "|-" + "-|-".join("-" * widths[idx] for idx in range(len(widths))) + "-|"
            lines.append(separator)
        for row in rows:
            lines.append(_fmt(row))
        return "\n".join(lines)


_Tabulate = Callable[[Sequence[Sequence[Any]], Sequence[str] | None, str], str]
PromptFn = Callable[[str], str]
PromptYesNoFn = Callable[[str, bool], bool]
ShowProposalDetailsFn = Callable[[ControlPanelSession, StrategyProposal], None]


@dataclass(slots=True)
class _ConfigAccessor:
    """Small adapter to read configuration values from different containers."""

    getter: Callable[[str, Any | None], Any]

    def get(self, key: str, default: Any | None = None) -> Any:
        try:
            value = self.getter(key, default)
        except TypeError:
            value = self.getter(key)
        return default if value is None else value


def _coerce_config(config: Any) -> _ConfigAccessor:
    getter = getattr(config, "get", None)
    if not callable(getter):
        return _ConfigAccessor(lambda _key, default=None: default)
    return _ConfigAccessor(getter)


def _ensure_tabulate(tabulate_fn: _Tabulate | None) -> _Tabulate:
    if tabulate_fn is None:
        return _default_tabulate
    return tabulate_fn


def _format_leg_position(raw: Any) -> str:
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return "?"
    return "S" if num < 0 else "L"


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


def _build_rejection_table(entries: Iterable[Mapping[str, Any]]):
    return _reporting_build_rejection_table(entries)


def show_rejection_detail(
    session: ControlPanelSession,
    entry: Mapping[str, Any],
    *,
    tabulate_fn: _Tabulate | None = None,
    prompt_fn: PromptFn = prompt,
    show_proposal_details: ShowProposalDetailsFn | None = None,
) -> None:
    """Pretty-print details for a single rejection entry."""

    tabulate_fn = _ensure_tabulate(tabulate_fn)

    strategy = entry.get("strategy") or "—"
    status = entry.get("status") or "—"
    anchor = entry.get("description") or "—"
    reason_value = entry.get("reason")
    raw_reason = entry.get("raw_reason")
    detail = normalize_reason(reason_value or raw_reason)
    reason_label_text = detail.message or ReasonAggregator.label_for(detail.category)
    original = None
    if isinstance(reason_value, ReasonDetail):
        original = reason_value.data.get("original_message")
    if original is None:
        original = detail.data.get("original_message")
    note = raw_reason or original or reason_label_text

    print(f"Strategie: {strategy}")
    print(f"Status: {status}")
    print(f"Anchor: {anchor}")
    print(f"Reden: {reason_label_text}")
    if note and note != reason_label_text:
        print(f"Detail: {note}")

    metrics = entry.get("metrics") or {}
    if metrics:
        metric_rows = [[key, metrics[key]] for key in sorted(metrics)]
        print("Metrics:")
        print(tabulate_fn(metric_rows, headers=["Metric", "Waarde"], tablefmt="github"))

    meta = entry.get("meta")
    if isinstance(meta, Mapping) and meta:
        meta_rows = [[key, value] for key, value in meta.items()]
        print("Flags:")
        print(tabulate_fn(meta_rows, headers=["Sleutel", "Waarde"], tablefmt="github"))

    legs = entry.get("legs")
    legs_list = (
        list(legs)
        if isinstance(legs, Sequence) and not isinstance(legs, (str, bytes))
        else []
    )
    if not legs_list:
        legs_list = []

    dte_info = format_dtes(legs_list)
    if dte_info:
        print(f"DTEs: {dte_info}")

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
    leg_rows: list[list[str]] = []
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
                str(bid if bid not in {None, ""} else ""),
                str(ask if ask not in {None, ""} else ""),
                str(mid if mid not in {None, ""} else ""),
            ]
        )
    if leg_rows:
        print("Legs:")
        print(tabulate_fn(leg_rows, headers=headers, tablefmt="github"))

    proposal = build_proposal_from_entry(entry)
    if not proposal:
        return

    meta = entry.get("meta") if isinstance(entry, Mapping) else None
    symbol_hint: str | None = None
    if isinstance(meta, Mapping):
        raw_symbol = meta.get("symbol") or meta.get("underlying")
        if isinstance(raw_symbol, str) and raw_symbol.strip():
            symbol_hint = raw_symbol.strip().upper()
    if not symbol_hint:
        symbol_hint = _entry_symbol(entry)

    print("\nActies:")
    print("1. Haal orderinformatie van IB op")
    while True:
        selection = prompt_fn("Kies actie (0 om terug): ")
        if selection in {"", "0"}:
            break
        if selection == "1":
            _display_rejection_proposal(
                session,
                proposal,
                symbol_hint,
                show_proposal_details=show_proposal_details,
            )
        else:
            print("❌ Ongeldige keuze")


def _display_rejection_proposal(
    session: ControlPanelSession,
    proposal: StrategyProposal,
    symbol_hint: str | None,
    *,
    show_proposal_details: ShowProposalDetailsFn | None,
) -> None:
    previous_symbol = session.symbol
    previous_strategy = session.strategy
    try:
        if symbol_hint:
            session.symbol = symbol_hint
        session.strategy = proposal.strategy
        if show_proposal_details:
            show_proposal_details(session, proposal)
    finally:
        session.symbol = previous_symbol
        session.strategy = previous_strategy


def refresh_rejections(
    session: ControlPanelSession,
    services: ControlPanelServices,
    entries: Sequence[Mapping[str, Any]],
    *,
    config: Any,
    show_proposal_details: ShowProposalDetailsFn | None,
    tabulate_fn: _Tabulate | None = None,
    prompt_fn: PromptFn = prompt,
) -> None:
    """Refresh rejected proposals through the strategy pipeline."""

    tabulate_fn = _ensure_tabulate(tabulate_fn)
    config_accessor = _coerce_config(config)

    prepared_entries: list[MutableMapping[str, Any]] = []
    proposal_cache: dict[int, StrategyProposal | None] = {}
    original_map: dict[int, Mapping[str, Any]] = {}
    original_proposals: dict[int, StrategyProposal] = {}

    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        prepared: MutableMapping[str, Any] = dict(entry)
        prepared[ORIGINAL_INDEX_KEY] = idx
        proposal = build_proposal_from_entry(prepared)
        proposal_cache[id(prepared)] = proposal
        if not proposal:
            continue
        prepared_entries.append(prepared)
        original_map[idx] = entry
        original_proposals[idx] = proposal

    if not prepared_entries:
        print("⚠️ Geen geschikte voorstellen om te verversen.")
        return

    criteria_cfg = load_criteria()
    spot_price = session.spot_price if isinstance(session.spot_price, (int, float)) else None
    timeout = float(config_accessor.get("MARKET_DATA_TIMEOUT", 15.0) or 15.0)
    max_attempts = int(config_accessor.get("PIPELINE_REFRESH_ATTEMPTS", 1) or 1)
    if max_attempts < 1:
        max_attempts = 1
    retry_delay = float(config_accessor.get("PIPELINE_REFRESH_RETRY_DELAY", 0.0) or 0.0)
    parallel = bool(config_accessor.get("PIPELINE_REFRESH_PARALLEL", False))

    def _cached_builder(entry: Mapping[str, Any]) -> StrategyProposal | None:
        cached = proposal_cache.get(id(entry))
        if cached is None:
            cached = build_proposal_from_entry(entry)
            proposal_cache[id(entry)] = cached
        return cached

    params = RefreshParams(
        entries=prepared_entries,
        criteria=criteria_cfg,
        spot_price=spot_price,
        timeout=timeout,
        max_attempts=max_attempts,
        retry_delay=retry_delay if retry_delay > 0 else 0.0,
        parallel=parallel,
        proposal_builder=_cached_builder,
    )

    run_id = session.run_id
    trace_id = str(run_id) if isinstance(run_id, str) else None
    context = RefreshContext(trace_id=trace_id)

    total = len(prepared_entries)
    print(f"📡 Ververs orderinformatie via IB voor {total} voorstel(len)...")
    result = refresh_pipeline(context, params=params)

    refreshed_count = result.stats.accepted + result.stats.rejected
    accepted_count = len(result.accepted)
    failures = sum(1 for item in result.rejections if getattr(item, "error", None) is not None)

    fallback_symbol = str(session.symbol or "—")

    for item in result.accepted:
        target = original_map.get(item.source.index)
        if target is None:
            continue
        proposal = item.proposal
        symbol_label = item.source.symbol or _entry_symbol(target) or fallback_symbol
        target["refreshed_proposal"] = proposal
        target["refreshed_reasons"] = item.reasons
        target["refreshed_missing_quotes"] = item.missing_quotes
        target["refreshed_accepted"] = True
        target["refreshed_symbol"] = symbol_label
        print(f"✅ {symbol_label} – {proposal.strategy}: voorstel voldoet na refresh.")

    for item in result.rejections:
        target = original_map.get(item.source.index)
        if target is None:
            continue
        proposal = item.proposal or original_proposals.get(item.source.index)
        symbol_label = item.source.symbol or _entry_symbol(target) or fallback_symbol
        target["refreshed_accepted"] = False
        if proposal:
            target["refreshed_proposal"] = proposal
        target["refreshed_reasons"] = getattr(item, "reasons", [])
        target["refreshed_missing_quotes"] = getattr(item, "missing_quotes", [])
        target["refreshed_symbol"] = symbol_label
        strategy_label = (
            proposal.strategy
            if isinstance(proposal, StrategyProposal)
            else str(target.get("strategy") or "?")
        )
        error = getattr(item, "error", None)
        if error is not None:
            logger.error(
                "Refresh mislukt voor %s (%s): %s",
                strategy_label,
                symbol_label,
                error,
            )
            print(f"❌ {symbol_label} – {strategy_label}: {error}")
        else:
            reason_labels = ", ".join(reason_label(reason) for reason in getattr(item, "reasons", []))
            if not reason_labels:
                reason_labels = "Onbekende reden"
            print(
                "⚠️ "
                + f"{symbol_label} – {strategy_label}: afgewezen ({reason_labels})."
            )

    summary_parts = [f"{refreshed_count}/{total} ververst", f"geaccepteerd: {accepted_count}"]
    if failures:
        summary_parts.append(f"fouten: {failures}")
    print("Samenvatting: " + ", ".join(summary_parts))

    accepted_entries: list[Mapping[str, Any]] = [
        entry
        for entry in entries
        if entry.get("refreshed_accepted")
        and isinstance(entry.get("refreshed_proposal"), StrategyProposal)
    ]
    if not accepted_entries:
        return

    vm_pairs: list[tuple[ProposalVM, Mapping[str, Any]]] = []
    for idx, entry in enumerate(accepted_entries):
        refreshed: StrategyProposal = entry["refreshed_proposal"]  # type: ignore[assignment]
        symbol_label = (
            (entry.get("refreshed_symbol") or _entry_symbol(entry))
            if isinstance(entry, Mapping)
            else None
        )
        source = RefreshSource(index=idx, entry=entry, symbol=symbol_label)
        candidate = RefreshProposal(
            proposal=refreshed,
            source=source,
            reasons=list(entry.get("refreshed_reasons") or []),
            missing_quotes=list(entry.get("refreshed_missing_quotes") or []),
            core=entry.get("refreshed_core") if isinstance(entry.get("refreshed_core"), ProposalCore) else None,
            accepted=True,
        )
        vm = build_proposal_viewmodel(candidate)
        vm_pairs.append((vm, entry))

    viewmodels = [vm for vm, _ in vm_pairs]
    if not viewmodels:
        return

    sorted_vms = sort_records(viewmodels, PROPOSALS_SPEC)
    vm_map = {id(vm): entry for vm, entry in vm_pairs}
    headers, rows = proposals_table(sorted_vms, spec=PROPOSALS_SPEC)
    indexed_rows: list[list[str]] = []
    ordered_entries: list[Mapping[str, Any]] = []
    for index, (vm, row) in enumerate(zip(sorted_vms, rows), start=1):
        indexed_rows.append([str(index), *row])
        mapped_entry = vm_map.get(id(vm))
        if mapped_entry is not None:
            ordered_entries.append(mapped_entry)

    print("Geaccepteerde voorstellen:")
    print(tabulate_fn(indexed_rows, headers=["#", *headers], tablefmt="github"))

    if not ordered_entries:
        return

    while True:
        try:
            selection = prompt_fn("Kies voorstel (0 om terug): ")
        except (EOFError, OSError):  # pragma: no cover - interactive fallback
            logger.debug("Prompt afgebroken tijdens selectie geaccepteerd voorstel")
            break
        if selection in {"", "0"}:
            break
        try:
            index = int(selection)
        except ValueError:
            print("❌ Ongeldige keuze")
            continue
        if index < 1 or index > len(ordered_entries):
            print("❌ Ongeldige keuze")
            continue
        chosen_entry = ordered_entries[index - 1]
        refreshed: StrategyProposal = chosen_entry["refreshed_proposal"]  # type: ignore[assignment]
        symbol_hint = (
            chosen_entry.get("refreshed_symbol")
            or _entry_symbol(chosen_entry)
            or (refreshed.legs[0].get("symbol") if refreshed.legs else None)
        )
        print()
        _display_rejection_proposal(
            session,
            refreshed,
            symbol_hint if isinstance(symbol_hint, str) else None,
            show_proposal_details=show_proposal_details,
        )
        print()


def build_rejection_summary(
    session: ControlPanelSession,
    summary: RejectionSummary | None,
    *,
    services: ControlPanelServices,
    config: Any,
    show_reasons: bool = False,
    tabulate_fn: _Tabulate | None = None,
    prompt_fn: PromptFn = prompt,
    prompt_yes_no_fn: PromptYesNoFn = prompt_yes_no,
    show_proposal_details: ShowProposalDetailsFn | None = None,
) -> None:
    """Display aggregated rejection information and interactive options."""

    tabulate_fn = _ensure_tabulate(tabulate_fn)
    entries = session.combo_evaluations
    eval_entries = list(entries) if isinstance(entries, Sequence) else []
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
        show_reasons
        or prompt_yes_no_fn("Wil je een samenvatting van rejection reasons (y/n)?", False)
    ):
        if summary.by_filter:
            rows_filter = sorted(summary.by_filter.items(), key=lambda x: x[1], reverse=True)
            print("Afwijzingen per filter:")
            print(tabulate_fn(rows_filter, headers=["Filter", "Aantal"], tablefmt="github"))
        if summary.by_reason:
            rows_reason = sorted(summary.by_reason.items(), key=lambda x: x[1], reverse=True)
            print("Redenen:")
            print(tabulate_fn(rows_reason, headers=["Reden", "Aantal"], tablefmt="github"))
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
                        tabulate_fn(
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
                    print(f"• {reason_label(r)}")

    if not rejects:
        return

    if not (
        show_reasons
        or prompt_yes_no_fn("Wil je meer details opvraagbaar per rij (y/n)?", False)
    ):
        return

    if not headers or not rows:
        print("Geen detailgegevens beschikbaar.")
        return

    print(tabulate_fn(rows, headers=headers, tablefmt="github"))

    if len(rejects) > 1:
        print("Voer 'A' in om IB-orderinformatie voor alle regels te verversen.")

    while True:
        selection = prompt_fn("Kies nummer (0 om terug, A voor alles):")
        normalized = selection.strip().lower() if isinstance(selection, str) else ""
        if normalized in {"", "0"}:
            break
        if normalized in {"a", "all"}:
            refresh_rejections(
                session,
                services,
                rejects,
                config=config,
                show_proposal_details=show_proposal_details,
                tabulate_fn=tabulate_fn,
                prompt_fn=prompt_fn,
            )
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
        show_rejection_detail(
            session,
            rejects[idx - 1],
            tabulate_fn=tabulate_fn,
            prompt_fn=prompt_fn,
            show_proposal_details=show_proposal_details,
        )
        print()
