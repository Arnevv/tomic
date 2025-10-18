from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from tomic import config as cfg
from tomic.api.earnings_importer import (
    load_json as load_earnings_json,
    parse_earnings_csv,
    save_json as save_earnings_json,
    update_next_earnings,
)
from tomic.core import config as runtime_config


@dataclass(slots=True)
class MarketChameleonImportPlan:
    """Container describing a pending MarketChameleon import."""

    csv_path: Path
    json_path: Path
    csv_map: dict[str, Any]
    json_data: dict[str, Any]
    today: date


def resolve_csv_columns(runtime_config_module=runtime_config) -> tuple[str, list[str]]:
    """Return configured CSV symbol and earnings date columns."""

    runtime_config_module.load()
    symbol_col = runtime_config_module.get("earnings_import.symbol_col", "Symbol")
    raw_candidates = runtime_config_module.get(
        "earnings_import.next_col_candidates",
        ["Next Earnings", "Next Earnings "],
    )
    if isinstance(raw_candidates, str):
        next_cols = [raw_candidates]
    elif isinstance(raw_candidates, Sequence):
        next_cols = [str(col) for col in raw_candidates]
    else:
        next_cols = ["Next Earnings", "Next Earnings "]
    return str(symbol_col or "Symbol"), next_cols


def parse_market_chameleon_csv(
    csv_path: Path,
    runtime_config_module=runtime_config,
) -> dict[str, Any]:
    """Parse MarketChameleon CSV according to runtime configuration."""

    symbol_col, next_cols = resolve_csv_columns(runtime_config_module)
    return parse_earnings_csv(
        str(csv_path),
        symbol_col=symbol_col,
        next_col_candidates=next_cols,
    )


def resolve_earnings_json_path(
    runtime_config_module=runtime_config,
    cfg_module=cfg,
) -> Path:
    """Return the target JSON path for earnings data."""

    runtime_config_module.load()
    json_path_cfg = runtime_config_module.get("data.earnings_json_path")
    path = Path(
        json_path_cfg
        or cfg_module.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
    ).expanduser()
    return path


def determine_today(runtime_config_module=runtime_config) -> date:
    """Return today taking configured overrides into account."""

    runtime_config_module.load()
    override = runtime_config_module.get("earnings_import.today_override")
    if isinstance(override, date):
        return override
    if isinstance(override, str) and override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def build_import_plan(
    csv_path: Path,
    *,
    runtime_config_module=runtime_config,
    cfg_module=cfg,
) -> MarketChameleonImportPlan:
    """Return a plan describing how the earnings JSON would be updated."""

    csv_map = parse_market_chameleon_csv(csv_path, runtime_config_module)
    json_path = resolve_earnings_json_path(runtime_config_module, cfg_module)
    json_data = load_earnings_json(json_path)
    today_value = determine_today(runtime_config_module)
    return MarketChameleonImportPlan(
        csv_path=csv_path,
        json_path=json_path,
        csv_map=csv_map,
        json_data=json_data,
        today=today_value,
    )


def preview_changes(plan: MarketChameleonImportPlan) -> list[dict[str, Any]]:
    """Return the list of changes that would be applied for ``plan``."""

    _, changes = update_next_earnings(
        plan.json_data,
        plan.csv_map,
        plan.today,
        dry_run=True,
    )
    return list(changes)


def summarise_changes(changes: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return aggregate statistics for ``changes``."""

    replaced = 0
    inserted = 0
    removed_same_month = 0
    total = 0
    for change in changes:
        total += 1
        action = change.get("action")
        if action == "replaced_closest_future":
            replaced += 1
        if action in {"inserted_as_next", "created_symbol"}:
            inserted += 1
        removed_same_month += int(change.get("removed_same_month", 0) or 0)
    return {
        "total": total,
        "replaced": replaced,
        "inserted": inserted,
        "removed_same_month": removed_same_month,
    }


def apply_import(plan: MarketChameleonImportPlan) -> tuple[dict[str, Any], Path | None]:
    """Apply ``plan`` to disk and return the updated data and backup path."""

    updated_data, _ = update_next_earnings(
        plan.json_data,
        plan.csv_map,
        plan.today,
        dry_run=False,
    )
    save_earnings_json(updated_data, plan.json_path)
    backup_path = getattr(save_earnings_json, "last_backup_path", None)
    return updated_data, backup_path


__all__ = [
    "MarketChameleonImportPlan",
    "resolve_csv_columns",
    "parse_market_chameleon_csv",
    "resolve_earnings_json_path",
    "determine_today",
    "build_import_plan",
    "preview_changes",
    "summarise_changes",
    "apply_import",
]
