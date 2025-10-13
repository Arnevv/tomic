"""CLI entry point for importing MarketChameleon earnings exports."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from tomic import config as app_config
from tomic.api.earnings_importer import (
    load_json as load_earnings_json,
    parse_earnings_csv,
    save_json as save_earnings_json,
    update_next_earnings,
)
from tomic.core import config as runtime_config
from tomic.logutils import logger, setup_logging

try:  # pragma: no cover - optional dependency
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate is unavailable

    def tabulate(
        rows: list[list[object]],
        headers: list[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        values: list[list[str]] = [
            [str(cell) for cell in row]
            for row in ([headers] + rows if headers else rows)
        ]
        widths = [max(len(col[i]) for col in values) for i in range(len(values[0]))]

        def _format(row: Iterable[str]) -> str:
            parts = [str(cell).ljust(widths[i]) for i, cell in enumerate(row)]
            return "| " + " | ".join(parts) + " |"

        lines: list[str] = []
        if headers:
            lines.append(_format(values[0]))
            divider = "|-" + "-|-".join("-" * w for w in widths) + "-|"
            lines.append(divider)
            data_rows = values[1:]
        else:
            data_rows = values
        for row in data_rows:
            lines.append(_format(row))
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Pad naar MarketChameleon CSV")
    parser.add_argument(
        "--json",
        help="Pad naar earnings_dates.json (default uit configuratie)",
    )
    parser.add_argument(
        "--today",
        help="Overschrijf referentiedatum (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Pas wijzigingen daadwerkelijk toe (anders alleen dry-run)",
    )
    parser.add_argument(
        "--symbol-col",
        help="Kolomnaam voor symbolen in de CSV",
    )
    parser.add_argument(
        "--next-col",
        action="append",
        help="Kolomnamen voor volgende earnings (kan meerdere keren)",
    )
    parser.add_argument(
        "--tz",
        help="Timezone voor CSV datums wanneer pandas conversie nodig is",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Sla backup van bestaande JSON over",
    )
    return parser


def _resolve_today(override: str | date | None, cli_today: str | None) -> date:
    if cli_today:
        return datetime.strptime(cli_today, "%Y-%m-%d").date()
    if isinstance(override, date):
        return override
    if isinstance(override, str) and override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("today_override heeft ongeldig formaat, gebruik systeemdatum")
    return date.today()


def _normalise_candidates(values: Iterable[str] | str | None) -> list[str]:
    if values is None:
        return ["Next Earnings", "Next Earnings "]
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values]


def _format_changes(changes: list[dict]) -> tuple[str, int, int, int]:
    rows: list[list[object]] = []
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
    table = tabulate(rows, headers=headers, tablefmt="github")
    replaced = sum(1 for c in changes if c.get("action") == "replaced_closest_future")
    inserted = sum(
        1 for c in changes if c.get("action") in {"inserted_as_next", "created_symbol"}
    )
    return table, removed_total, replaced, inserted


def run(args: argparse.Namespace) -> int:
    runtime_config.load()

    csv_path = Path(args.csv).expanduser()
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    runtime_config.set_value("import.last_earnings_csv_path", str(csv_path))

    symbol_col = args.symbol_col or runtime_config.get("earnings_import.symbol_col") or "Symbol"
    next_candidates = args.next_col or runtime_config.get("earnings_import.next_col_candidates")
    tz = args.tz

    csv_map = parse_earnings_csv(
        str(csv_path),
        symbol_col=symbol_col,
        next_col_candidates=_normalise_candidates(next_candidates),
        tz=tz,
    )

    if not csv_map:
        logger.info("Geen wijzigingen gevonden – CSV map levert niets op")
        return 0

    json_path_value = args.json or runtime_config.get("data.earnings_json_path")
    if not json_path_value:
        json_path_value = app_config.get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")
    json_path = Path(str(json_path_value)).expanduser()

    json_data = load_earnings_json(json_path)

    today_override = runtime_config.get("earnings_import.today_override")
    today_date = _resolve_today(today_override, args.today)

    _, changes = update_next_earnings(
        json_data,
        csv_map,
        today_date,
        dry_run=True,
    )

    if not changes:
        print("Geen wijzigingen nodig volgens CSV.")
        return 0

    table, removed_total, replaced, inserted = _format_changes(changes)
    print(table)
    print(f"\nVerwijderd vanwege dezelfde maand: {removed_total}")
    print(
        f"Samenvatting: totaal={len(changes)} vervangen={replaced} ingevoegd={inserted}"
    )

    if not args.apply:
        print("Dry-run voltooid. Gebruik --apply om wijzigingen op te slaan.")
        return 0

    updated_data, _ = update_next_earnings(
        json_data,
        csv_map,
        today_date,
        dry_run=False,
    )

    save_earnings_json(updated_data, json_path, backup=not args.no_backup)
    runtime_config.set_value("data.earnings_json_path", str(json_path))

    backup_path = save_earnings_json.last_backup_path
    if backup_path:
        print(f"Backup: {backup_path}")
    print(f"Wijzigingen opgeslagen naar {json_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(stdout=True)
    try:
        return run(args)
    except Exception as exc:  # pragma: no cover - CLI level error propagation
        logger.error(f"Import mislukt: {exc}")
        print(f"❌ Import mislukt: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI execution path
    raise SystemExit(main())

