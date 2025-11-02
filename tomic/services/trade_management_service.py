"""Domain service for trade management status aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import MutableMapping
from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable, List, Mapping, Sequence

from tomic.analysis.exit_rules import extract_exit_rules, generate_exit_alerts
from tomic.analysis.strategy import group_strategies
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.utils import get_leg_right


QuoteFetcher = Callable[[Mapping[str, Any], Sequence[MutableMapping[str, Any]]], Sequence[Mapping[str, Any]] | None]


def _filter_exit_alerts(alerts: Iterable[str]) -> List[str]:
    relevant = ["exitniveau", "PnL", "DTE ≤ exitdrempel", "dagen in trade"]
    return [a for a in alerts if any(key in a for key in relevant)]


@dataclass(frozen=True)
class StrategyManagementSummary:
    """Reduced representation of the management status for a strategy."""

    symbol: str | None
    expiry: str | None
    strategy: str | None
    spot: object
    unrealized_pnl: object
    days_to_expiry: object
    exit_trigger: str
    status: str


def _load_positions_and_journal(
    positions_file: str | None,
    journal_file: str | None,
    loader: Callable[[str], Any],
) -> tuple[str, str, list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    positions_path = positions_file or cfg_get("POSITIONS_FILE", "positions.json")
    journal_path = journal_file or cfg_get("JOURNAL_FILE", "journal.json")

    raw_positions = loader(positions_path)
    positions = list(raw_positions) if isinstance(raw_positions, list) else []

    raw_journal = loader(journal_path)
    journal = list(raw_journal) if isinstance(raw_journal, list) else []

    return positions_path, journal_path, positions, journal


def build_management_summary(
    positions_file: str | None = None,
    journal_file: str | None = None,
    *,
    grouper=group_strategies,
    exit_rule_loader=extract_exit_rules,
    alert_generator=generate_exit_alerts,
    loader=load_json,
) -> Sequence[StrategyManagementSummary]:
    """Return strategy management statuses for the requested journal context.

    Deze functie blijft ongewijzigd ten behoeve van de bestaande CLI-output.
    """

    positions_path, journal_path, positions, journal = _load_positions_and_journal(
        positions_file,
        journal_file,
        loader,
    )

    strategies = grouper(positions, journal)
    exit_rules_data = exit_rule_loader(journal_path)
    exit_rules: Mapping[tuple[Any, Any], Mapping[str, Any]]
    if isinstance(exit_rules_data, Mapping):
        exit_rules = exit_rules_data  # type: ignore[assignment]
    else:
        exit_rules = {}

    summaries: list[StrategyManagementSummary] = []
    for strat in strategies:
        key = (strat.get("symbol"), strat.get("expiry"))
        rule = exit_rules.get(key)
        alert_generator(strat, rule)

        alerts = _filter_exit_alerts(strat.get("alerts", []))
        status = "⚠️ Beheer nodig" if alerts else "✅ Houden"
        exit_trigger = " | ".join(alerts) if alerts else "geen trigger"

        summaries.append(
            StrategyManagementSummary(
                symbol=strat.get("symbol"),
                expiry=strat.get("expiry"),
                strategy=strat.get("type"),
                spot=strat.get("spot"),
                unrealized_pnl=strat.get("unrealizedPnL"),
                days_to_expiry=strat.get("days_to_expiry"),
                exit_trigger=exit_trigger,
                status=status,
            )
        )

    return summaries


@dataclass(frozen=True)
class StrategyExitIntent:
    """Representation of raw legs and exit governance for a strategy."""

    strategy: Mapping[str, Any]
    legs: Sequence[Mapping[str, Any]]
    exit_rules: Mapping[str, Any] | None


def _expiry_variants(value: Any) -> set[str]:
    variants: set[str] = set()
    if value in (None, ""):
        return variants
    text = str(value)
    variants.add(text)
    if "-" in text:
        variants.add(text.replace("-", ""))
    return variants


def _normalize_expiry(leg: Mapping[str, Any]) -> str | None:
    for key in ["expiry", "lastTradeDate", "lastTradeDateOrContractMonth", "expiration"]:
        value = leg.get(key)
        if value:
            for variant in _expiry_variants(value):
                return variant
    return None


def _normalize_right(leg: Mapping[str, Any]) -> str | None:
    right = leg.get("right")
    if isinstance(right, str) and right:
        lower = right.lower()
        if lower in {"c", "call"}:
            return "call"
        if lower in {"p", "put"}:
            return "put"
    derived = get_leg_right(leg)
    return derived if derived else None


def _collect_raw_leg_groups(
    positions: Sequence[Mapping[str, Any]],
    journal: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[Any, list[Mapping[str, Any]]], dict[tuple[str, str], list[Mapping[str, Any]]]]:
    conid_to_trade: dict[Any, Any] = {}
    if journal:
        for trade in journal:
            tid = trade.get("TradeID") or id(trade)
            for leg in trade.get("Legs", []) or []:
                cid = leg.get("conId")
                if cid is not None:
                    conid_to_trade[cid] = tid

    by_trade: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    by_symbol_expiry: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)

    for pos in positions:
        cid = pos.get("conId") or pos.get("con_id")
        tid = conid_to_trade.get(cid)
        if tid is not None:
            by_trade[tid].append(pos)
            continue

        symbol = pos.get("symbol") or pos.get("underlying") or pos.get("localSymbol")
        if not symbol:
            continue

        expiry_candidates: set[str] = set()
        for key in ["lastTradeDate", "expiry", "expiration", "lastTradeDateOrContractMonth"]:
            expiry_candidates.update(_expiry_variants(pos.get(key)))
        if not expiry_candidates:
            continue
        for exp in expiry_candidates:
            by_symbol_expiry[(symbol, exp)].append(pos)

    return by_trade, by_symbol_expiry


def _resolve_raw_legs(
    strategy: Mapping[str, Any],
    raw_by_trade: Mapping[Any, list[Mapping[str, Any]]],
    raw_by_symbol_expiry: Mapping[tuple[str, str], list[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    trade_id = strategy.get("trade_id")
    if trade_id in raw_by_trade:
        return raw_by_trade.get(trade_id, [])

    symbol = strategy.get("symbol")
    expiry = strategy.get("expiry")
    candidates: list[tuple[str, str]] = []
    if symbol and expiry:
        for variant in _expiry_variants(expiry):
            candidates.append((symbol, variant))

    symbol_alt = strategy.get("underlying") or strategy.get("symbol")
    if symbol_alt and symbol_alt != symbol and expiry:
        for variant in _expiry_variants(expiry):
            candidates.append((symbol_alt, variant))

    for candidate in candidates:
        if candidate in raw_by_symbol_expiry:
            return raw_by_symbol_expiry[candidate]

    return []


_LEG_METADATA_FIELDS = [
    "symbol",
    "underlying",
    "expiry",
    "lastTradeDate",
    "lastTradeDateOrContractMonth",
    "expiration",
    "strike",
    "right",
    "multiplier",
    "tradingClass",
    "trading_class",
    "primaryExchange",
    "primary_exchange",
    "exchange",
    "currency",
    "conId",
    "con_id",
    "localSymbol",
]

_LEG_QUOTE_FIELDS = [
    "bid",
    "ask",
    "last",
    "mid",
    "close",
    "bidSize",
    "askSize",
    "minTick",
    "min_tick",
]


def _copy_missing_fields(target: MutableMapping[str, Any], source: Mapping[str, Any]) -> None:
    for key in _LEG_METADATA_FIELDS:
        if key == "right":
            existing = _normalize_right(target)
            if existing:
                continue
            source_right = _normalize_right(source)
            if source_right:
                target["right"] = source_right
            continue
        if target.get(key) in (None, "") and source.get(key) not in (None, ""):
            target[key] = source[key]
    for key in _LEG_QUOTE_FIELDS:
        if key in {"minTick", "min_tick"}:
            continue
        if target.get(key) in (None, "") and source.get(key) not in (None, ""):
            target[key] = source.get(key)
    _ensure_min_tick_field(target, source)


def _ensure_min_tick_field(
    target: MutableMapping[str, Any], source: Mapping[str, Any] | None = None
) -> None:
    if target.get("minTick") not in (None, ""):
        return
    if target.get("min_tick") not in (None, ""):
        target["minTick"] = target["min_tick"]
        return
    if source is not None:
        for key in ("minTick", "min_tick"):
            value = source.get(key) if isinstance(source, Mapping) else None
            if value not in (None, ""):
                target["minTick"] = value
                target.setdefault("min_tick", value)
                break


def _has_valid_quotes(leg: Mapping[str, Any]) -> bool:
    def _valid(val: Any) -> bool:
        return isinstance(val, (int, float)) and val >= 0

    return _valid(leg.get("bid")) and _valid(leg.get("ask"))


def _has_min_tick(leg: Mapping[str, Any]) -> bool:
    value = leg.get("minTick")
    if not isinstance(value, (int, float)) or value <= 0:
        value = leg.get("min_tick")
    return isinstance(value, (int, float)) and value > 0


def _match_raw_leg(
    leg: Mapping[str, Any],
    con_lookup: Mapping[Any, Mapping[str, Any]],
    key_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    cid = leg.get("conId") or leg.get("con_id")
    if cid is not None and cid in con_lookup:
        return con_lookup[cid]
    strike = leg.get("strike")
    right = _normalize_right(leg)
    expiry = _normalize_expiry(leg)
    if strike in (None, "") or not right or not expiry:
        return None
    key = (str(strike), right, expiry)
    return key_lookup.get(key)


def _intent_symbol(intent: StrategyExitIntent) -> str | None:
    strategy = intent.strategy if isinstance(intent.strategy, Mapping) else None
    symbol = None
    if strategy:
        symbol = strategy.get("symbol") or strategy.get("underlying")
    if not symbol and intent.legs:
        first = intent.legs[0]
        symbol = first.get("symbol") if isinstance(first, Mapping) else None
    if not symbol:
        return None
    text = str(symbol).strip()
    return text.upper() if text else None


def exit_intent_keys(intent: StrategyExitIntent) -> set[tuple[str, str | None]]:
    """Return normalized symbol/expiry combinations for ``intent``."""

    keys: set[tuple[str, str | None]] = set()
    symbol = _intent_symbol(intent)
    if not symbol:
        return keys

    strategy = intent.strategy if isinstance(intent.strategy, Mapping) else None
    expiry_value = strategy.get("expiry") if strategy else None
    variants = _expiry_variants(expiry_value) if expiry_value else set()
    keys.add((symbol, None))
    for variant in variants:
        keys.add((symbol, variant))
    return keys


def _prepare_payload_leg(
    leg: MutableMapping[str, Any],
    strategy: Mapping[str, Any],
    raw_leg: Mapping[str, Any] | None,
) -> None:
    if raw_leg:
        _copy_missing_fields(leg, raw_leg)
    leg.setdefault("symbol", strategy.get("symbol"))
    if strategy.get("expiry"):
        leg.setdefault("expiry", strategy.get("expiry"))
    if leg.get("con_id") and not leg.get("conId"):
        leg["conId"] = leg["con_id"]
    if leg.get("conId") and not leg.get("con_id"):
        leg["con_id"] = leg["conId"]
    if not leg.get("right"):
        right = _normalize_right(leg)
        if right:
            leg["right"] = right
    _ensure_min_tick_field(leg)


def _update_raw_leg_quotes(
    raw_leg: MutableMapping[str, Any] | None, updated: Mapping[str, Any]
) -> None:
    if raw_leg is None:
        return
    for key in ["bid", "ask", "last", "mid"]:
        if updated.get(key) not in (None, ""):
            raw_leg[key] = updated[key]
    if updated.get("minTick") not in (None, ""):
        raw_leg["minTick"] = updated["minTick"]
        raw_leg.setdefault("min_tick", updated["minTick"])
    elif updated.get("min_tick") not in (None, ""):
        raw_leg["min_tick"] = updated["min_tick"]
        raw_leg.setdefault("minTick", updated["min_tick"])


def _resolve_quote_fetcher(custom_fetcher: QuoteFetcher | None) -> QuoteFetcher | None:
    if custom_fetcher is not None:
        return custom_fetcher
    try:  # pragma: no cover - optional dependency during tests
        from tomic.services.ib_marketdata import fetch_quote_snapshot
        from tomic.strategy.models import StrategyProposal
    except Exception:  # pragma: no cover - IB stack not available
        return None

    def _default(strategy: Mapping[str, Any], legs: Sequence[MutableMapping[str, Any]]):
        if not legs:
            return legs
        proposal = StrategyProposal(
            strategy=strategy.get("type"),
            legs=[dict(leg) for leg in legs],
        )
        try:
            result = fetch_quote_snapshot(
                proposal,
                trigger="exit-intents",
                log_delta=False,
            )
        except Exception:  # pragma: no cover - network failure
            logger.warning("Fallback market data retrieval failed", exc_info=True)
            return legs
        return result.proposal.legs

    return _default


def _enrich_strategy_leg_quotes(
    strategy: MutableMapping[str, Any],
    raw_legs: Sequence[MutableMapping[str, Any]],
    *,
    quote_fetcher: QuoteFetcher | None = None,
    refresh_attempts: int = 0,
    refresh_wait: float = 0.0,
) -> None:
    legs = strategy.get("legs")
    if not isinstance(legs, list):
        return

    con_lookup = {}
    key_lookup = {}
    for raw in raw_legs:
        cid = raw.get("conId") or raw.get("con_id")
        if cid is not None:
            con_lookup[cid] = raw
        strike = raw.get("strike")
        right = _normalize_right(raw)
        expiry = _normalize_expiry(raw)
        if strike not in (None, "") and right and expiry:
            key_lookup[(str(strike), right, expiry)] = raw

    matched_raw: list[MutableMapping[str, Any] | None] = []
    needs_refresh = False

    for leg in legs:
        raw_match = _match_raw_leg(leg, con_lookup, key_lookup)
        matched_raw.append(raw_match if isinstance(raw_match, MutableMapping) else None)
        if isinstance(raw_match, Mapping):
            _copy_missing_fields(leg, raw_match)
        else:
            leg.setdefault("symbol", strategy.get("symbol"))
            if strategy.get("expiry"):
                leg.setdefault("expiry", strategy.get("expiry"))
        _ensure_min_tick_field(leg)
        if not _has_valid_quotes(leg) or not _has_min_tick(leg):
            needs_refresh = True

    attempts_remaining = max(int(refresh_attempts), 0)
    if not needs_refresh and attempts_remaining <= 0:
        return

    fetcher = _resolve_quote_fetcher(quote_fetcher)
    if fetcher is None:
        return

    attempts = max(attempts_remaining, 1) if (needs_refresh or attempts_remaining > 0) else 0
    if attempts <= 0:
        return

    wait_time = max(float(refresh_wait), 0.0)

    for attempt in range(attempts):
        payload: list[MutableMapping[str, Any]] = [dict(leg) for leg in legs]
        for idx, payload_leg in enumerate(payload):
            raw_leg = matched_raw[idx] if idx < len(matched_raw) else None
            _prepare_payload_leg(payload_leg, strategy, raw_leg)

        refreshed = fetcher(strategy, payload)
        if isinstance(refreshed, Sequence):
            for idx, updated in enumerate(refreshed):
                if idx >= len(legs):
                    break
                if not isinstance(updated, Mapping):
                    continue
                _copy_missing_fields(legs[idx], updated)
                for quote_key in ["bid", "ask", "last", "mid", "bidSize", "askSize"]:
                    if updated.get(quote_key) not in (None, ""):
                        legs[idx][quote_key] = updated[quote_key]
                _ensure_min_tick_field(legs[idx], updated)
                raw_leg = matched_raw[idx]
                if isinstance(raw_leg, MutableMapping):
                    _update_raw_leg_quotes(raw_leg, legs[idx])

        if all(_has_valid_quotes(leg) and _has_min_tick(leg) for leg in legs):
            break

        if attempt < attempts - 1 and wait_time > 0:
            time.sleep(wait_time)


def build_exit_intents(
    positions_file: str | None = None,
    journal_file: str | None = None,
    *,
    grouper=group_strategies,
    exit_rule_loader=extract_exit_rules,
    loader=load_json,
    quote_fetcher: QuoteFetcher | None = None,
    freshen_attempts: int = 0,
    freshen_wait_s: float = 0.0,
) -> Sequence[StrategyExitIntent]:
    """Return exit governance payload per strategy with raw legs and quotes."""

    positions_path, journal_path, positions, journal = _load_positions_and_journal(
        positions_file,
        journal_file,
        loader,
    )

    strategies = grouper(positions, journal)
    exit_rules_data = exit_rule_loader(journal_path)
    exit_rules: Mapping[tuple[Any, Any], Mapping[str, Any]]
    if isinstance(exit_rules_data, Mapping):
        exit_rules = exit_rules_data  # type: ignore[assignment]
    else:
        exit_rules = {}

    raw_by_trade, raw_by_symbol_expiry = _collect_raw_leg_groups(positions, journal)

    intents: list[StrategyExitIntent] = []
    for strategy in strategies:
        raw_legs_source = _resolve_raw_legs(strategy, raw_by_trade, raw_by_symbol_expiry)

        raw_leg_copies: list[MutableMapping[str, Any]] = [dict(leg) for leg in raw_legs_source]
        _enrich_strategy_leg_quotes(
            strategy,
            raw_leg_copies,
            quote_fetcher=quote_fetcher,
            refresh_attempts=freshen_attempts,
            refresh_wait=freshen_wait_s,
        )

        rule_key = (strategy.get("symbol"), strategy.get("expiry"))
        rule = exit_rules.get(rule_key)
        intents.append(
            StrategyExitIntent(
                strategy=strategy,
                legs=raw_leg_copies,
                exit_rules=rule,
            )
        )

    return intents


def build_exit_alert_index(
    summaries: Sequence[StrategyManagementSummary],
) -> set[tuple[str, str | None]]:
    """Return normalized symbol/expiry keys for summaries with exit alerts."""

    keys: set[tuple[str, str | None]] = set()
    for summary in summaries:
        trigger_text = summary.exit_trigger or ""
        if trigger_text.strip().lower() in {"", "geen trigger"}:
            continue
        symbol = summary.symbol
        if not symbol:
            continue
        symbol_key = str(symbol).upper()
        variants = _expiry_variants(summary.expiry) if summary.expiry else set()
        if not variants:
            keys.add((symbol_key, None))
        else:
            for variant in variants:
                keys.add((symbol_key, variant))
    return keys


__all__ = [
    "StrategyManagementSummary",
    "StrategyExitIntent",
    "build_management_summary",
    "build_exit_intents",
    "build_exit_alert_index",
    "exit_intent_keys",
]

