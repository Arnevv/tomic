"""Interactive flow for IV backfill imports."""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from tomic import config as cfg
from tomic.cli.common import prompt, prompt_yes_no
from tomic.helpers.csv_utils import parse_euro_float
from tomic.helpers.json_utils import dump_json
from tomic.journal.utils import load_json
from tomic.logutils import logger


try:  # pragma: no cover - fallback when tabulate is unavailable
    from tabulate import tabulate
except Exception:  # pragma: no cover - minimal fallback

    def tabulate(  # type: ignore[misc]
        rows: Sequence[Sequence[Any]],
        headers: Sequence[str] | None = None,
        tablefmt: str | None = None,
    ) -> str:
        def _stringify(value: Any) -> str:
            return "" if value is None else str(value)

        table_rows = list(rows)
        if headers:
            table_rows = [headers] + table_rows

        if not table_rows:
            return ""

        widths = [
            max(len(_stringify(row[idx])) for row in table_rows)
            for idx in range(len(table_rows[0]))
        ]

        def fmt(row: Sequence[Any]) -> str:
            return "| " + " | ".join(
                _stringify(col).ljust(widths[idx]) for idx, col in enumerate(row)
            ) + " |"

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append(
                "|-" + "-|-".join("-" * widths[idx] for idx in range(len(widths))) + "-|"
            )
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)


REQUIRED_COLUMNS = {"Date", "IV30"}
IV_THRESHOLD = 0.03  # 3 percentage points verschil


@dataclass
class CsvParseResult:
    """Container met resultaten van het inlezen van de CSV."""

    records: list[dict[str, Any]]
    duplicates: list[str]
    invalid_dates: list[str]
    empty_rows: int


def _parse_csv_date(raw: str) -> str | None:
    """Parse ``raw`` naar ``YYYY-MM-DD`` indien mogelijk."""

    value = str(raw).strip()
    if not value:
        return None

    candidates = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y%m%d",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_atm_iv(raw: Any) -> float | None:
    value = parse_euro_float(raw if isinstance(raw, str) else str(raw))
    if value is None:
        return None
    return value / 100.0


def read_iv_csv(path: Path) -> CsvParseResult:
    """Lees een CSV-bestand en geef ATM IV records terug."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = sorted(REQUIRED_COLUMNS - set(fieldnames))
        if missing:
            raise ValueError(f"Ontbrekende kolommen in CSV: {', '.join(missing)}")

        records_map: dict[str, dict[str, Any]] = {}
        duplicates: list[str] = []
        invalid_dates: list[str] = []
        empty_rows = 0

        for row in reader:
            date_raw = row.get("Date")
            iv_raw = row.get("IV30")
            if not (date_raw and str(iv_raw).strip()):
                empty_rows += 1
                continue

            parsed_date = _parse_csv_date(date_raw)
            if not parsed_date:
                invalid_dates.append(str(date_raw).strip())
                continue

            atm_iv = _parse_atm_iv(iv_raw)
            if atm_iv is None:
                empty_rows += 1
                continue

            record = {"date": parsed_date, "atm_iv": atm_iv}
            if parsed_date in records_map:
                duplicates.append(parsed_date)
            records_map[parsed_date] = record

    sorted_records = sorted(records_map.values(), key=lambda r: r["date"])
    return CsvParseResult(sorted_records, duplicates, invalid_dates, empty_rows)


def _build_preview_rows(
    symbol: str,
    csv_records: Sequence[dict[str, Any]],
    existing_map: dict[str, dict[str, Any]],
) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in csv_records:
        date = record["date"]
        new_iv = record.get("atm_iv")
        old_iv = existing_map.get(date, {}).get("atm_iv")
        status = "Nieuw" if date not in existing_map else "Update"
        diff = None
        if old_iv is not None and new_iv is not None:
            diff = new_iv - old_iv

        rows.append(
            [
                date,
                status,
                f"{old_iv:.4f}" if old_iv is not None else "-",
                f"{new_iv:.4f}" if new_iv is not None else "-",
                f"{diff:+.4f}" if diff is not None else "-",
            ]
        )

    if len(rows) > 12:
        logger.info(
            f"Voorbeeld toont eerste 12 regels van {len(rows)} voor {symbol}."
        )
        return rows[:12]
    return rows


def _collect_gaps(dates: Iterable[str]) -> list[tuple[str, str, int]]:
    ordered = sorted({d for d in dates if d})
    if len(ordered) < 2:
        return []

    result: list[tuple[str, str, int]] = []
    previous = datetime.strptime(ordered[0], "%Y-%m-%d")
    for raw in ordered[1:]:
        current = datetime.strptime(raw, "%Y-%m-%d")
        delta = (current - previous).days - 1
        if delta > 0:
            result.append((previous.strftime("%Y-%m-%d"), raw, delta))
        previous = current
    return result


def _load_supporting(path: Path) -> dict[str, dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for record in data:
        if isinstance(record, dict) and "date" in record:
            result[str(record["date"])] = record
    return result


def _merge_records(
    target: Path, csv_records: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], Path | None]:
    existing = load_json(target)
    if not isinstance(existing, list):
        existing = []

    merged: dict[str, dict[str, Any]] = {}
    for record in existing:
        if isinstance(record, dict) and "date" in record:
            merged[str(record["date"])] = dict(record)

    for record in csv_records:
        date = record["date"]
        base = merged.get(date, {})
        base.update(record)
        base["date"] = date
        merged[date] = base

    merged_list = sorted(merged.values(), key=lambda r: r.get("date", ""))

    backup_path: Path | None = None
    if target.exists():
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"temp_{target.name}")
    dump_json(merged_list, tmp)
    tmp.replace(target)

    return merged_list, backup_path


def run_iv_backfill_flow() -> None:
    """Interactieve flow voor het backfillen van IV-data."""

    symbol = prompt("Ticker symbool: ").strip().upper()
    if not symbol:
        print("❌ Geen symbool opgegeven")
        return

    csv_input = prompt("Pad naar CSV-bestand: ").strip()
    if not csv_input:
        print("❌ Geen CSV-pad opgegeven")
        return

    csv_path = Path(csv_input).expanduser()
    if not csv_path.exists():
        print(f"❌ CSV niet gevonden: {csv_path}")
        return

    try:
        parsed = read_iv_csv(csv_path)
    except Exception as exc:
        logger.error(f"IV CSV parse-fout: {exc}")
        print(f"❌ CSV inlezen mislukt: {exc}")
        return

    if not parsed.records:
        print("⚠️ Geen geldige rijen gevonden in CSV.")
        return

    summary_dir = Path(
        cfg.get("IV_SUMMARY_DIR", "tomic/data/iv_daily_summary")
    ).expanduser()
    summary_file = summary_dir / f"{symbol}.json"

    existing_data = load_json(summary_file)
    existing_map: dict[str, dict[str, Any]] = {}
    if isinstance(existing_data, list):
        for record in existing_data:
            if isinstance(record, dict) and "date" in record:
                existing_map[str(record["date"])] = record

    csv_map = {record["date"]: record for record in parsed.records}
    csv_dates = set(csv_map)
    existing_dates = set(existing_map)
    new_dates = sorted(csv_dates - existing_dates)
    overlap_dates = sorted(csv_dates & existing_dates)

    updates: list[dict[str, Any]] = []
    unchanged = 0
    for date in overlap_dates:
        new_iv = csv_map[date]["atm_iv"]
        old_iv = existing_map.get(date, {}).get("atm_iv")
        if old_iv is None:
            updates.append({"date": date, "old": old_iv, "new": new_iv})
        else:
            if abs(new_iv - old_iv) > IV_THRESHOLD:
                updates.append({"date": date, "old": old_iv, "new": new_iv})
            else:
                unchanged += 1

    hv_dir = Path(cfg.get("HV_DIR", "tomic/data/historical_volatility")).expanduser()
    hv_file = hv_dir / f"{symbol}.json"
    hv_map = _load_supporting(hv_file)

    spot_dir = Path(cfg.get("SPOT_DIR", "tomic/data/spot_prices")).expanduser()
    spot_file = spot_dir / f"{symbol}.json"
    spot_map = _load_supporting(spot_file)

    missing_hv = sorted(csv_dates - set(hv_map))
    missing_spot = sorted(csv_dates - set(spot_map))

    gaps = _collect_gaps(csv_dates)

    preview_rows = _build_preview_rows(symbol, parsed.records, existing_map)
    headers = ["Datum", "Status", "ATM IV (oud)", "ATM IV (nieuw)", "Δ"]
    print("\nVoorbeeld wijzigingen:")
    print(tabulate(preview_rows, headers=headers, tablefmt="github"))

    summary_rows = [
        ["Nieuwe dagen", len(new_dates)],
        ["Updates (>3%)", len(updates)],
        ["Overlap <=3%", unchanged],
        ["Dubbele rijen in CSV", len(parsed.duplicates)],
        ["Lege/ongeldige rijen", parsed.empty_rows + len(parsed.invalid_dates)],
        ["CSV-hiaten", len(gaps)],
        ["Ontbrekende HV-dagen", len(missing_hv)],
        ["Ontbrekende spot-dagen", len(missing_spot)],
    ]
    print("\nSamenvatting:")
    print(tabulate(summary_rows, headers=["Metriek", "Aantal"], tablefmt="github"))

    if parsed.duplicates:
        logger.warning(
            f"Dubbele datums gevonden in CSV voor {symbol}: {parsed.duplicates[:5]}"
        )
    if parsed.invalid_dates:
        logger.warning(
            f"Ongeldige datums overgeslagen voor {symbol}: {parsed.invalid_dates[:5]}"
        )

    if missing_hv:
        logger.warning(
            f"HV ontbreekt voor {len(missing_hv)} dagen ({symbol}); geen actie ondernomen"
        )
        print(
            f"⚠️ HV ontbreekt voor {len(missing_hv)} dagen. Controleer historical_volatility."
        )

    if missing_spot:
        logger.warning(
            f"Spot ontbreekt voor {len(missing_spot)} dagen ({symbol}); geen actie ondernomen"
        )
        print(
            f"⚠️ Spotdata ontbreekt voor {len(missing_spot)} dagen. Geen HV-backfill gestart."
        )

    if gaps:
        logger.info(f"Gevonden {len(gaps)} hiaten in CSV voor {symbol}: {gaps[:3]}")

    if not (new_dates or updates):
        print("ℹ️ Geen nieuwe of gewijzigde dagen gevonden.")
        return

    if not prompt_yes_no("Wijzigingen toepassen? (nee = dry-run)"):
        print("Dry-run voltooid. Geen wijzigingen geschreven.")
        logger.info(f"Dry-run voor IV backfill {symbol} zonder wijzigingen")
        return

    merged_records, backup_path = _merge_records(summary_file, parsed.records)
    logger.success(
        f"IV backfill voltooid voor {symbol}: {len(parsed.records)} records verwerkt"
    )
    print(
        "✅ IV backfill opgeslagen naar"
        f" {summary_file} (totaal {len(merged_records)} records)"
    )
    if backup_path:
        print(f"Backup aangemaakt: {backup_path}")


def main() -> None:
    """CLI entrypoint voor ``python -m tomic.cli.iv_backfill_flow``."""

    run_iv_backfill_flow()


if __name__ == "__main__":
    main()

