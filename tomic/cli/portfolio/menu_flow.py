"""Helper functions orchestrating the portfolio control panel flows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from tomic import config as cfg
from tomic.core.portfolio import services as portfolio_services
from tomic.cli.app_services import ControlPanelServices
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.formatting.portfolio_tables import (
    build_evaluated_trades_table,
    build_market_overview_table,
    build_market_scan_table,
    build_proposals_table,
)
from tomic.helpers.price_utils import ClosePriceSnapshot
from tomic.logutils import logger
from tomic.reporting import EvaluationSummary, format_reject_reasons
from tomic.helpers.dateutils import parse_date
from tomic.services.chain_processing import (
    ChainEvaluationConfig,
    ChainPreparationConfig,
    ChainPreparationError,
    ChainEvaluationResult,
    SpotResolution,
    evaluate_chain,
    load_and_prepare_chain,
    resolve_spot_price as resolve_chain_spot_price,
)
from tomic.services.market_scan_service import (
    MarketScanError,
    MarketScanRequest,
    MarketScanService,
    select_chain_source,
)
from tomic.services.portfolio_service import CandidateRankingError
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.utils import latest_atr


PromptFn = Callable[[str], str]
PromptYesNoFn = Callable[[str, bool], bool]
ShowProposalDetailsFn = Callable[[ControlPanelSession, StrategyProposal], None]
BuildRejectionSummaryFn = Callable[..., None]
SaveTradesFn = Callable[[ControlPanelSession, Sequence[dict]], None]
PrintEvaluationOverviewFn = Callable[[str, float | None, EvaluationSummary | None], None]
LoadLatestCloseFn = Callable[[str], ClosePriceSnapshot]
RefreshSpotFn = Callable[[str], float | None]
LoadSpotFromMetricsFn = Callable[[Path, str], float | None]
SpotFromChainFn = Callable[[Iterable[dict]], float | None]


def _print_table(tabulate_fn: Callable[..., str], spec) -> None:
    kwargs = {"headers": spec.headers, "tablefmt": "github"}
    colalign = getattr(spec, "colalign", None)
    if colalign:
        kwargs["colalign"] = colalign
    table = tabulate_fn(spec.rows, **kwargs)
    print(table)


def _print_evaluation_overview(
    session: ControlPanelSession, summary: EvaluationSummary | None
) -> None:
    if summary is None or summary.total <= 0:
        return
    sym = session.symbol.upper() if session.symbol else "—"
    if isinstance(session.spot_price, (int, float)) and session.spot_price > 0:
        header = f"Evaluatieoverzicht: {sym} @ {session.spot_price:.2f}"
    else:
        header = f"Evaluatieoverzicht: {sym}"
    print(header)
    print(f"Totaal combinaties: {summary.total}")
    if summary.expiries:
        print("Expiry breakdown:")
        for breakdown in summary.sorted_expiries():
            print(f"• {breakdown.label}: {breakdown.format_counts()}")
    print(f"Top reason for reject: {format_reject_reasons(summary)}")


def process_chain(
    session: ControlPanelSession,
    services: ControlPanelServices,
    path: Path,
    show_reasons: bool,
    *,
    tabulate_fn: Callable[..., str],
    prompt_fn: PromptFn,
    prompt_yes_no_fn: PromptYesNoFn,
    show_proposal_details: ShowProposalDetailsFn,
    build_rejection_summary_fn: BuildRejectionSummaryFn,
    save_trades_fn: SaveTradesFn,
    refresh_spot_price_fn: RefreshSpotFn,
    load_spot_from_metrics_fn: LoadSpotFromMetricsFn,
    load_latest_close_fn: LoadLatestCloseFn,
    spot_from_chain_fn: SpotFromChainFn,
    print_evaluation_overview_fn: PrintEvaluationOverviewFn | None = None,
) -> bool:
    """Load, evaluate and interact with an option chain CSV."""

    prep_config = ChainPreparationConfig.from_app_config()
    try:
        prepared = load_and_prepare_chain(path, prep_config)
    except ChainPreparationError as exc:
        print(f"⚠️ {exc}")
        return show_reasons

    if prepared.quality < prep_config.min_quality:
        print(
            f"⚠️ CSV kwaliteit {prepared.quality:.1f}% lager dan {prep_config.min_quality}%"
        )
    else:
        print(f"CSV kwaliteit {prepared.quality:.1f}%")

    if not prompt_yes_no_fn("Doorgaan?", False):
        return show_reasons

    if prompt_yes_no_fn(
        "Wil je delta/iv interpoleren om de data te verbeteren?", False
    ):
        try:
            prepared = load_and_prepare_chain(
                path, prep_config, apply_interpolation=True
            )
        except ChainPreparationError as exc:
            print(f"⚠️ {exc}")
            return show_reasons
        print("✅ Interpolatie toegepast op ontbrekende delta/iv.")
        print(f"Nieuwe CSV kwaliteit {prepared.quality:.1f}%")

    symbol = str(session.symbol or "")
    spot_resolution = resolve_chain_spot_price(
        symbol,
        prepared,
        refresh_quote=refresh_spot_price_fn,
        load_metrics_spot=load_spot_from_metrics_fn,
        load_latest_close=load_latest_close_fn,
        chain_spot_fallback=spot_from_chain_fn,
    )
    if isinstance(spot_resolution, SpotResolution):
        spot_price = spot_resolution.price
    else:  # pragma: no cover - backward compatibility guard
        spot_price = spot_resolution  # type: ignore[assignment]

    if not isinstance(spot_price, (int, float)) or spot_price <= 0:
        spot_price = spot_from_chain_fn(prepared.records) or 0.0
    session.spot_price = spot_price

    strategy_name = str(session.strategy or "").lower().replace(" ", "_")
    pipeline = services.get_pipeline()
    atr_val = latest_atr(symbol) or 0.0
    eval_config = ChainEvaluationConfig.from_app_config(
        symbol=symbol,
        strategy=strategy_name,
        spot_price=float(spot_price or 0.0),
        atr=atr_val,
    )

    evaluation = evaluate_chain(prepared, pipeline, eval_config)
    evaluation_summary = session.combo_evaluation_summary
    if isinstance(evaluation_summary, EvaluationSummary) or evaluation_summary is None:
        if print_evaluation_overview_fn is None:
            _print_evaluation_overview(session, evaluation_summary)
        else:
            print_evaluation_overview_fn(
                evaluation.context.symbol,
                evaluation.context.spot_price,
                evaluation_summary,
            )

    build_rejection_summary_fn(
        session,
        evaluation.filter_preview,
        services=services,
        config=cfg,
        show_reasons=show_reasons,
        tabulate_fn=tabulate_fn,
        prompt_fn=prompt_fn,
        prompt_yes_no_fn=prompt_yes_no_fn,
        show_proposal_details=show_proposal_details,
    )

    evaluated = evaluation.evaluated_trades
    session.evaluated_trades = list(evaluated)
    session.spot_price = evaluation.context.spot_price

    if evaluated:
        show_reasons = show_evaluations(
            session,
            evaluation,
            services,
            evaluated,
            atr_val,
            show_reasons,
            tabulate_fn=tabulate_fn,
            prompt_fn=prompt_fn,
            prompt_yes_no_fn=prompt_yes_no_fn,
            show_proposal_details=show_proposal_details,
            build_rejection_summary_fn=build_rejection_summary_fn,
            save_trades_fn=save_trades_fn,
            refresh_spot_price_fn=refresh_spot_price_fn,
            load_latest_close_fn=load_latest_close_fn,
        )
    else:
        print("⚠️ Geen geschikte strikes gevonden.")
        build_rejection_summary_fn(
            session,
            evaluation.summary,
            services=services,
            config=cfg,
            show_reasons=show_reasons,
            tabulate_fn=tabulate_fn,
            prompt_fn=prompt_fn,
            prompt_yes_no_fn=prompt_yes_no_fn,
            show_proposal_details=show_proposal_details,
        )
        print("➤ Controleer of de juiste expiraties beschikbaar zijn in de chain.")
        print("➤ Of pas je selectiecriteria aan in strike_selection_rules.yaml.")

    return show_reasons


def show_evaluations(
    session: ControlPanelSession,
    evaluation: ChainEvaluationResult,
    services: ControlPanelServices,
    evaluated: Sequence[dict],
    atr_val: float,
    show_reasons: bool,
    *,
    tabulate_fn: Callable[..., str],
    prompt_fn: PromptFn,
    prompt_yes_no_fn: PromptYesNoFn,
    show_proposal_details: ShowProposalDetailsFn,
    build_rejection_summary_fn: BuildRejectionSummaryFn,
    save_trades_fn: SaveTradesFn,
    refresh_spot_price_fn: RefreshSpotFn,
    load_latest_close_fn: LoadLatestCloseFn,
) -> bool:
    """Present evaluated trades and optionally drill into proposals."""

    symbol = session.symbol or ""
    close_price, close_date = load_latest_close_fn(symbol)
    if close_price is not None and close_date:
        print(f"Close {close_date}: {close_price}")
    if atr_val:
        print(f"ATR: {atr_val:.2f}")
    else:
        print("ATR: n.v.t.")

    trades_table = build_evaluated_trades_table(evaluated)
    _print_table(tabulate_fn, trades_table)

    if prompt_yes_no_fn("Opslaan naar CSV?", False):
        save_trades_fn(session, evaluated)

    if prompt_yes_no_fn("Doorgaan naar strategie voorstellen?", False):
        show_reasons = True

        latest_spot = refresh_spot_price_fn(str(symbol))
        if isinstance(latest_spot, (int, float)) and latest_spot > 0:
            session.spot_price = float(latest_spot)
            evaluation.context.spot_price = float(latest_spot)

        if evaluation.context.spot_price > 0:
            print(f"Spotprice: {evaluation.context.spot_price:.2f}")
        else:
            print("Spotprice: onbekend")

        proposals = evaluation.proposals
        summary = evaluation.summary

        if proposals:
            rom_w = cfg.get("SCORE_WEIGHT_ROM", 0.5)
            pos_w = cfg.get("SCORE_WEIGHT_POS", 0.3)
            ev_w = cfg.get("SCORE_WEIGHT_EV", 0.2)
            print(
                f"Scoregewichten: ROM {rom_w*100:.0f}% | PoS {pos_w*100:.0f}% | EV {ev_w*100:.0f}%"
            )

            proposal_result = build_proposals_table(proposals)
            _print_table(tabulate_fn, proposal_result.table)

            if proposal_result.missing_scenario:
                print("no scenario defined")
            if proposal_result.warn_missing_edge:
                print("⚠️ Eén of meerdere edges niet beschikbaar")

            if show_reasons:
                build_rejection_summary_fn(
                    session,
                    summary,
                    services=services,
                    config=cfg,
                    show_reasons=show_reasons,
                    tabulate_fn=tabulate_fn,
                    prompt_fn=prompt_fn,
                    prompt_yes_no_fn=prompt_yes_no_fn,
                    show_proposal_details=show_proposal_details,
                )

            while True:
                sel = prompt_fn("Kies voorstel (0 om terug): ")
                if sel in {"", "0"}:
                    break
                try:
                    idx = int(sel) - 1
                    chosen_prop = proposals[idx]
                except (ValueError, IndexError):
                    print("❌ Ongeldige keuze")
                    continue
                show_proposal_details(session, chosen_prop)
                break
        else:
            print("⚠️ Geen voorstellen gevonden")
            build_rejection_summary_fn(
                session,
                summary,
                services=services,
                config=cfg,
                show_reasons=show_reasons,
                tabulate_fn=tabulate_fn,
                prompt_fn=prompt_fn,
                prompt_yes_no_fn=prompt_yes_no_fn,
                show_proposal_details=show_proposal_details,
            )

    return show_reasons


def run_market_scan(
    session: ControlPanelSession,
    services: ControlPanelServices,
    recommendations: Sequence[Mapping[str, object]],
    *,
    tabulate_fn: Callable[..., str],
    prompt_fn: PromptFn,
    prompt_yes_no_fn: PromptYesNoFn,
    show_proposal_details: ShowProposalDetailsFn,
    refresh_spot_price_fn: RefreshSpotFn,
    load_spot_from_metrics_fn: LoadSpotFromMetricsFn,
    load_latest_close_fn: LoadLatestCloseFn,
    spot_from_chain_fn: SpotFromChainFn,
) -> None:
    """Execute a market scan for the provided recommendations."""

    if not recommendations:
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

    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for rec in recommendations:
        symbol = str(rec.get("symbol") or "").upper()
        strategy_name = str(rec.get("strategy") or "")
        if not symbol or not strategy_name:
            continue
        grouped[symbol].append(rec)

    if not grouped:
        print("⚠️ Geen symbolen om te scannen.")
        return

    def _select_existing_chain_dir() -> Path | None:
        while True:
            raw = prompt_fn(
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
        except Exception:  # pragma: no cover - filesystem edge cases
            display_path = existing_chain_dir
        print(f"📂 Gebruik bestaande optionchains uit: {display_path}")
    else:
        print("🔍 Markt scan via Polygon gestart…")

    refresh_quotes = prompt_yes_no_fn(
        "Informatie van TWS ophalen y / n: ",
        False,
    )

    pipeline = services.get_pipeline()
    config_data = cfg.get("STRATEGY_CONFIG") or {}
    interest_rate = float(cfg.get("INTEREST_RATE", 0.05))
    prep_config = ChainPreparationConfig.from_app_config()

    scan_requests: list[MarketScanRequest] = []
    for symbol, symbol_recs in grouped.items():
        for rec in symbol_recs:
            raw_strategy = str(rec.get("strategy") or "")
            strategy = raw_strategy.lower().replace(" ", "_")
            if not strategy:
                continue
            earnings_value = rec.get("next_earnings")
            earnings_date: date | None = None
            if isinstance(earnings_value, date):
                earnings_date = earnings_value
            elif isinstance(earnings_value, str):
                earnings_date = parse_date(earnings_value)
            scan_requests.append(
                MarketScanRequest(
                    symbol=symbol,
                    strategy=strategy,
                    metrics=dict(rec),
                    next_earnings=earnings_date,
                )
            )

    if not scan_requests:
        print("⚠️ Geen voorstellen gevonden tijdens scan.")
        return

    scan_service = MarketScanService(
        pipeline,
        services.portfolio,
        interest_rate=interest_rate,
        strategy_config=config_data,
        chain_config=prep_config,
        refresh_spot_price=refresh_spot_price_fn,
        load_spot_from_metrics=load_spot_from_metrics_fn,
        load_latest_close=load_latest_close_fn,
        spot_from_chain=spot_from_chain_fn,
        atr_loader=latest_atr,
        refresh_snapshot=portfolio_services.refresh_proposal_from_ib,
    )

    def _chain_source(symbol: str) -> Path | None:
        return select_chain_source(
            symbol,
            existing_dir=existing_chain_dir,
            fetch_chain=services.export.fetch_polygon_chain,
        )

    try:
        candidates = scan_service.run_market_scan(
            scan_requests,
            chain_source=_chain_source,
            top_n=top_n,
            refresh_quotes=refresh_quotes,
        )
    except MarketScanError as exc:
        logger.exception("Market scan pipeline failed")
        print(f"❌ Markt scan mislukt: {exc}")
        return
    except CandidateRankingError as exc:
        logger.exception("Candidate ranking failed")
        print(f"❌ Rangschikking van voorstellen mislukt: {exc}")
        return

    if not candidates:
        print("⚠️ Geen voorstellen gevonden tijdens scan.")
        return

    table_spec = build_market_scan_table(candidates)
    _print_table(tabulate_fn, table_spec)

    while True:
        sel = prompt_fn("Selectie scan (0 om terug): ")
        if sel in {"", "0"}:
            break
        try:
            idx = int(sel) - 1
            chosen = candidates[idx]
        except (ValueError, IndexError):
            print("❌ Ongeldige keuze")
            continue
        session.update_from_mapping(
            {
                "symbol": chosen.symbol,
                "strategy": chosen.strategy,
                "spot_price": chosen.spot,
            }
        )
        show_proposal_details(session, chosen.proposal)
        print()
        _print_table(tabulate_fn, table_spec)


def show_market_overview(
    tabulate_fn: Callable[..., str], table_rows: Iterable[Sequence[object]]
) -> None:
    """Render the overview table used in the market info menu."""

    spec = build_market_overview_table(table_rows)
    _print_table(tabulate_fn, spec)

