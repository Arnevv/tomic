from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from tomic import config as cfg
from tomic.core import config as runtime_config
from tomic.export import (
    RunMetadata,
    build_export_path,
    export_proposals_csv,
    export_proposals_json,
    render_journal_entries,
)
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.journal.utils import load_json, save_json
from tomic.integrations.polygon.client import PolygonClient
from tomic.services.strategy_pipeline import StrategyProposal
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.analysis.greeks import compute_portfolio_greeks
from tomic.loader import load_strike_config
from tomic.utils import today


def build_run_metadata(
    session: ControlPanelSession,
    *,
    symbol: str | None = None,
    strategy: str | None = None,
    runtime_config_module=runtime_config,
) -> RunMetadata:
    """Return consistent metadata for the current CLI session."""

    if not session.run_id:
        session.run_id = uuid.uuid4().hex[:12]
    run_id = str(session.run_id)

    config_hash = session.config_hash
    if not isinstance(config_hash, str) or not config_hash:
        try:
            cfg_model = runtime_config_module.load()
            cfg_dump = cfg_model.model_dump(by_alias=True)
            config_hash = hashlib.sha256(
                json.dumps(cfg_dump, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:12]
        except Exception:
            config_hash = "unknown"
        session.config_hash = config_hash

    schema_version = cfg.get("EXPORT_SCHEMA_VERSION")
    schema_version_str = str(schema_version) if schema_version else None

    return RunMetadata(
        timestamp=datetime.now(),
        run_id=run_id,
        config_hash=config_hash,
        symbol=symbol,
        strategy=strategy,
        schema_version=schema_version_str,
    )


def load_acceptance_criteria(strategy: str) -> dict[str, Any]:
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


def load_portfolio_context(
    positions_file: Path,
    account_info_file: Path,
) -> tuple[dict[str, Any], bool]:
    """Return portfolio context and availability flag."""

    ctx = {
        "net_delta": None,
        "net_theta": None,
        "net_vega": None,
        "margin_used": None,
        "positions_open": None,
    }
    if not positions_file.exists() or not account_info_file.exists():
        return ctx, False
    try:
        positions = json.loads(positions_file.read_text())
        account = json.loads(account_info_file.read_text())
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


def export_proposal_csv(
    session: ControlPanelSession,
    proposal: StrategyProposal,
    *,
    export_dir: Path | None = None,
    runtime_config_module=runtime_config,
) -> Path:
    """Serialise ``proposal`` to CSV and return the resulting path."""

    symbol = str(session.symbol or "").strip() or None
    strategy_name = str(session.strategy or proposal.strategy or "").strip() or None

    run_meta = build_run_metadata(
        session,
        symbol=symbol,
        strategy=strategy_name,
        runtime_config_module=runtime_config_module,
    )
    footer_rows: list[tuple[str, object]] = [
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
        ("scenario_info", proposal.scenario_info),
        ("breakevens", proposal.breakevens or []),
        ("atr", proposal.atr),
        ("iv_rank", proposal.iv_rank),
        ("iv_percentile", proposal.iv_percentile),
        ("hv20", proposal.hv20),
        ("hv30", proposal.hv30),
        ("hv90", proposal.hv90),
        ("dte", proposal.dte),
        (
            "breakeven_distances",
            proposal.breakeven_distances or {"dollar": [], "percent": []},
        ),
        ("wing_width", proposal.wing_width),
        ("wing_symmetry", proposal.wing_symmetry),
    ]
    run_meta = run_meta.with_extra(footer_rows=footer_rows)

    export_dir = export_dir or Path(cfg.get("EXPORT_DIR", "exports"))
    strategy_tag = [strategy_name.replace(" ", "_")] if strategy_name else None
    export_path = build_export_path(
        "proposal",
        run_meta,
        extension="csv",
        directory=export_dir,
        tags=strategy_tag,
    )

    columns = [
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

    records: list[dict[str, object]] = []
    for leg in proposal.legs:
        row = dict(leg)
        metrics = leg.get("missing_metrics") or []
        if isinstance(metrics, (list, tuple)):
            row["missing_metrics"] = ",".join(str(m) for m in metrics)
        records.append(row)

    result_path = export_proposals_csv(
        records,
        columns=columns,
        path=export_path,
        run_meta=run_meta,
    )
    return result_path


def export_proposal_json(
    session: ControlPanelSession,
    proposal: StrategyProposal,
    *,
    export_dir: Path | None = None,
    earnings_path: Path | None = None,
    positions_file: Path | None = None,
    account_info_file: Path | None = None,
    runtime_config_module=runtime_config,
) -> Path:
    """Serialise ``proposal`` to JSON and return the resulting path."""

    symbol = str(session.symbol or "").strip() or None
    strategy_name = str(session.strategy or proposal.strategy or "").strip() or None
    strategy_file = strategy_name.replace(" ", "_") if strategy_name else None

    run_meta = build_run_metadata(
        session,
        symbol=symbol,
        strategy=strategy_name,
        runtime_config_module=runtime_config_module,
    )

    accept = load_acceptance_criteria(strategy_file or proposal.strategy)
    positions_path = positions_file or Path(cfg.get("POSITIONS_FILE", "positions.json"))
    account_path = account_info_file or Path(
        cfg.get("ACCOUNT_INFO_FILE", "account_info.json")
    )
    portfolio_ctx, portfolio_available = load_portfolio_context(positions_path, account_path)
    spot_price = session.spot_price

    earnings_file = earnings_path or Path(
        cfg.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
    )
    earnings_dict = load_json(earnings_file)
    next_earn = None
    if isinstance(earnings_dict, dict) and symbol:
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
        "strategy": strategy_file or proposal.strategy,
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

    export_dir = export_dir or Path(cfg.get("EXPORT_DIR", "exports"))
    strategy_tag = [strategy_file] if strategy_file else None
    export_path = build_export_path(
        "proposal",
        run_meta,
        extension="json",
        directory=export_dir,
        tags=strategy_tag,
    )
    return export_proposals_json(data, path=export_path, run_meta=run_meta)


def proposal_journal_text(
    session: ControlPanelSession,
    proposal: StrategyProposal,
    *,
    symbol: str | None = None,
    strategy: str | None = None,
) -> str:
    """Return the formatted journal text for ``proposal``."""

    ticker = symbol or session.symbol or ""
    strategy_name = strategy or session.strategy or proposal.strategy
    journal_lines = render_journal_entries(
        {"proposal": proposal, "symbol": ticker, "strategy": strategy_name}
    )
    return "\n".join(journal_lines)


def load_spot_from_metrics(directory: Path, symbol: str) -> float | None:
    """Return spot price from a metrics CSV in ``directory`` if available."""
    pattern = f"other_data_{symbol.upper()}_*.csv"
    files = list(directory.glob(pattern))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        with latest.open(newline="") as handle:
            row = next(csv.DictReader(handle))
            spot = row.get("SpotPrice") or row.get("spotprice")
            return float(spot) if spot is not None else None
    except Exception:
        return None


def spot_from_chain(chain: list[dict[str, Any]]) -> float | None:
    """Return first positive spot-like value from option ``chain``."""

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


def refresh_spot_price(
    symbol: str,
    *,
    price_history_dir: Path | None = None,
    price_meta_file: Path | None = None,
    polygon_client_factory=PolygonClient,
) -> float | None:
    """Fetch and cache the current spot price for ``symbol``."""

    sym = symbol.upper()
    history_dir = price_history_dir or Path(
        cfg.get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")
    )
    history_dir.mkdir(parents=True, exist_ok=True)
    spot_file = history_dir / f"{sym}_spot.json"
    meta_path = price_meta_file or Path(cfg.get("PRICE_META_FILE", "price_meta.json"))
    if price_meta_file is not None:
        if price_meta_file.exists():
            meta_data = load_json(price_meta_file)
            meta = meta_data if isinstance(meta_data, dict) else {}
        else:
            meta = {}
    else:
        meta = load_price_meta()
    now = datetime.now()
    meta_entry = meta.get(sym)
    ts_str = None
    if isinstance(meta_entry, Mapping):
        ts_str = (
            meta_entry.get("fetched_at")
            or meta_entry.get("timestamp")
            or meta_entry.get("last_fetch")
        )
    elif isinstance(meta_entry, str):
        ts_str = meta_entry
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

    client = polygon_client_factory()
    try:
        client.connect()
        price = client.fetch_spot_price(sym)
    except Exception:
        price = None
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    if price is None:
        return None

    save_json({"price": float(price), "timestamp": now.isoformat()}, spot_file)
    if not isinstance(meta_entry, Mapping):
        meta_entry = {}
    meta_entry = dict(meta_entry)
    meta_entry["fetched_at"] = now.isoformat()
    meta_entry.setdefault("source", "polygon")
    meta[sym] = meta_entry
    if price_meta_file is not None:
        save_json(meta, price_meta_file)
    else:
        save_price_meta(meta)
    return float(price)


__all__ = [
    "build_run_metadata",
    "load_acceptance_criteria",
    "load_portfolio_context",
    "export_proposal_csv",
    "export_proposal_json",
    "proposal_journal_text",
    "load_spot_from_metrics",
    "spot_from_chain",
    "refresh_spot_price",
]
