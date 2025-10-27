"""Utilities for importing MarketChameleon earnings data.

This module centralises all logic required to ingest a CSV export from
MarketChameleon and merge it into the local ``earnings_dates.json`` file.
The public functions are intentionally granular so the importer can be used
from both the interactive control panel as well as automated scripts/tests.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tomic.helpers.dateutils import insert_chrono, is_iso_date, to_iso_date
from tomic.logutils import logger


def _normalise_column_name(name: str) -> str:
    return name.strip().casefold()


def _read_csv_with_pandas(path: Path) -> list[dict[str, Any]] | None:
    try:  # pragma: no cover - optional dependency branch exercised in prod
        import pandas as pd  # type: ignore
    except Exception:
        return None

    read_csv = getattr(pd, "read_csv", None)
    if read_csv is None:
        return None

    try:
        frame = read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - delegated to tests via csv module
        logger.error(f"CSV inlezen mislukt via pandas: {exc}")
        return None

    records = frame.to_dict(orient="records")
    if not isinstance(records, list):
        return None
    return [{k: str(v) for k, v in record.items()} for record in records]


def _parse_csv_rows(path: Path) -> list[dict[str, Any]]:
    records = _read_csv_with_pandas(path)
    if records is not None:
        return records

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: ("" if v is None else str(v)) for k, v in row.items()} for row in reader]


def parse_earnings_csv(
    path: str,
    symbol_col: str = "Symbol",
    next_col_candidates: list[str] | tuple[str, ...] = (
        "Next Earnings",
        "Next Earnings ",
    ),
    tz: str | None = None,
) -> dict[str, str]:
    """Return a mapping of symbols to ISO dates parsed from ``path``.

    Column names are matched case-insensitively and surrounding whitespace is
    ignored to accommodate the inconsistencies seen in the MarketChameleon
    export (e.g. ``"Next Earnings "`` with a trailing space).
    """

    csv_path = Path(path).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    rows = _parse_csv_rows(csv_path)
    if not rows:
        logger.warning(f"Geen records gevonden in CSV {csv_path}")
        return {}

    first_row = rows[0]
    columns = {_normalise_column_name(col): col for col in first_row.keys() if col}

    if _normalise_column_name(symbol_col) not in columns:
        raise KeyError(f"Kolom '{symbol_col}' ontbreekt in CSV {csv_path}")

    next_column_name: str | None = None
    for candidate in next_col_candidates:
        candidate_norm = _normalise_column_name(candidate)
        if candidate_norm in columns:
            next_column_name = columns[candidate_norm]
            break

    if not next_column_name:
        raise KeyError(
            "Geen geldige kolom gevonden voor volgende earnings datum."
        )

    symbol_column_name = columns[_normalise_column_name(symbol_col)]

    result: dict[str, str] = {}
    parse_errors = 0
    for row in rows:
        symbol_raw = str(row.get(symbol_column_name, "")).strip()
        if not symbol_raw:
            continue
        next_raw = str(row.get(next_column_name, "")).strip()
        if not next_raw:
            continue

        iso_date = _normalise_date_value(next_raw, tz=tz)
        if not iso_date:
            parse_errors += 1
            logger.warning(
                f"Kon datum '{next_raw}' voor symbool {symbol_raw} niet parsen"
            )
            continue
        result[symbol_raw.upper()] = iso_date

    if parse_errors:
        logger.warning(f"{parse_errors} rijen overgeslagen door parse-fouten")

    logger.info(
        f"CSV {csv_path} verwerkt → {len(result)} symbolen met geldige earnings"
    )
    return result


def _normalise_date_value(raw: str, tz: str | None = None) -> str | None:
    raw = raw.strip()
    if not raw:
        return None

    iso = to_iso_date(raw)
    if iso:
        return iso

    # Fallback to pandas for odd formats if available.
    try:  # pragma: no cover - exercised when pandas is available
        import pandas as pd  # type: ignore

        to_dt = getattr(pd, "to_datetime", None)
        if to_dt is not None:
            ts = to_dt(raw, dayfirst=False, errors="coerce")
            if ts is not None and not getattr(ts, "isnat", False):
                if hasattr(ts, "tz_convert") and tz:
                    try:
                        ts = ts.tz_convert(tz)
                    except Exception:
                        ts = ts.tz_localize(tz) if hasattr(ts, "tz_localize") else ts
                if hasattr(ts, "to_pydatetime"):
                    dt = ts.to_pydatetime()
                else:
                    dt = ts
                if isinstance(dt, datetime):
                    return dt.date().isoformat()
                if isinstance(dt, date):
                    return dt.isoformat()
    except Exception:
        pass

    for fmt in ("%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def load_json(path: str | Path) -> dict[str, list[str]]:
    """Return validated earnings JSON from ``path``.

    Missing files result in an empty dictionary.  The JSON must contain a
    mapping of strings to lists of strings; all other structures raise a
    ``ValueError`` to surface potential data corruption early.
    """

    json_path = Path(path).expanduser()
    if not json_path.exists():
        logger.info(f"JSON bestand ontbreekt, nieuw bestand wordt aangemaakt: {json_path}")
        return {}

    try:
        with json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ongeldige JSON structuur in {json_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"JSON bestand {json_path} moet een object bevatten")

    validated: dict[str, list[str]] = {}
    for symbol, values in data.items():
        if not isinstance(symbol, str):
            raise ValueError("JSON sleutel moet string zijn")
        if not isinstance(values, list):
            raise ValueError(f"JSON waarde voor {symbol} moet lijst zijn")
        cleaned: list[str] = []
        for raw in values:
            if isinstance(raw, str):
                cleaned.append(raw)
            else:
                raise ValueError(f"Alle datums voor {symbol} moeten strings zijn")
        validated[symbol] = cleaned
    return validated


def save_json(data: dict[str, list[str]], path: str | Path, backup: bool = True) -> None:
    """Persist ``data`` to ``path`` while optionally creating a timestamped backup."""

    json_path = Path(path).expanduser()
    json_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if backup and json_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = json_path.with_suffix(json_path.suffix + f".{timestamp}.bak")
        shutil.copy2(json_path, backup_path)

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)

    save_json.last_backup_path = backup_path
    if backup_path:
        logger.info(f"Backup aangemaakt: {backup_path}")
    logger.success(f"earnings JSON opgeslagen: {json_path}")


save_json.last_backup_path: Path | None = None


def closest_future_index(dates: list[str], today: date) -> int | None:
    """Return the index of the first date that is >= ``today``."""

    for idx, raw in enumerate(dates):
        if not is_iso_date(raw):
            continue
        dt = datetime.strptime(raw, "%Y-%m-%d").date()
        if dt >= today:
            return idx
    return None


def enforce_month_uniqueness(
    dates: list[str],
    *,
    keep_month: str,
    keep_date: str,
) -> tuple[list[str], int]:
    """Remove all entries sharing ``keep_month`` and insert ``keep_date`` once."""

    filtered = [d for d in dates if len(d) >= 7 and d[:7] != keep_month]
    removed = len(dates) - len(filtered)
    filtered = insert_chrono(filtered, keep_date)
    return filtered, removed


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def update_next_earnings(
    json_data: dict[str, list[str]],
    csv_map: dict[str, str],
    today: date,
    *,
    dry_run: bool = True,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Merge ``csv_map`` into ``json_data``.

    Returns a tuple ``(updated_json, changes)`` where ``changes`` contains one
    dictionary per affected symbol with keys ``symbol``, ``old_future``,
    ``new_future``, ``action`` and ``removed_same_month``.
    """

    updated: dict[str, list[str]] = {
        symbol: list(values) for symbol, values in json_data.items()
    }
    changes: list[dict[str, Any]] = []

    for symbol, csv_value in csv_map.items():
        iso_csv = to_iso_date(csv_value)
        if not iso_csv:
            logger.warning(f"CSV datum ongeldig voor {symbol}: {csv_value}")
            continue

        existing = updated.get(symbol, [])
        normalized = []
        invalid_entries = 0
        for item in existing:
            iso_item = to_iso_date(item)
            if iso_item:
                normalized.append(iso_item)
            else:
                invalid_entries += 1
        if invalid_entries:
            logger.warning(
                f"{invalid_entries} ongeldige datums verwijderd voor symbool {symbol}"
            )

        if normalized != sorted(normalized):
            normalized.sort()

        before_state = list(normalized)
        idx = closest_future_index(normalized, today)
        old_future = normalized[idx] if idx is not None and idx < len(normalized) else None

        action = "inserted_as_next"
        if idx is None:
            normalized = insert_chrono(normalized, iso_csv)
        else:
            normalized[idx] = iso_csv
            action = "replaced_closest_future"

        normalized, removed = enforce_month_uniqueness(
            normalized, keep_month=iso_csv[:7], keep_date=iso_csv
        )
        normalized = _dedupe_preserve_order(normalized)

        if normalized == before_state:
            continue

        updated[symbol] = normalized
        change = {
            "symbol": symbol,
            "old_future": old_future,
            "new_future": iso_csv,
            "action": action if symbol in json_data else "created_symbol",
            "removed_same_month": removed,
        }
        changes.append(change)

    if not dry_run:
        json_data.clear()
        json_data.update({k: list(v) for k, v in updated.items()})

    return updated, changes


__all__ = [
    "parse_earnings_csv",
    "load_json",
    "save_json",
    "closest_future_index",
    "enforce_month_uniqueness",
    "update_next_earnings",
]

