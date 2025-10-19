from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from tomic import config as cfg
from tomic.cli.app_services import ControlPanelServices
from tomic.cli.controlpanel_session import ControlPanelSession
from tomic.cli.common import Menu, prompt, prompt_yes_no
from tomic.core import config as runtime_config
from tomic.earnings import build_import_plan, preview_changes, summarise_changes, apply_import
from tomic.logutils import logger

try:  # pragma: no cover - optional dependency
    from tabulate import tabulate
except Exception:  # pragma: no cover - fallback when tabulate is missing

    def tabulate(
        rows: Iterable[Iterable[object]],
        headers: Iterable[str] | None = None,
        tablefmt: str = "simple",
    ) -> str:
        table = list(rows)
        if headers:
            table_rows = [list(headers)] + [list(row) for row in table]
        else:
            table_rows = [list(row) for row in table]
        if not table_rows:
            return ""
        widths = [max(len(str(cell)) for cell in column) for column in zip(*table_rows)]

        def fmt(row: Iterable[object]) -> str:
            values = [str(cell).ljust(widths[idx]) for idx, cell in enumerate(row)]
            return "| " + " | ".join(values) + " |"

        lines: list[str] = []
        if headers:
            header = list(headers)
            lines.append(fmt(header))
            lines.append("|-" + "-|-".join("-" * widths[idx] for idx in range(len(widths))) + "-|")
            body = table
        else:
            body = table_rows
        for row in body:
            lines.append(fmt(row))
        return "\n".join(lines)


def build_export_menu(
    session: ControlPanelSession,
    services: ControlPanelServices,
    *,
    run_module: Callable[..., None],
    prompt_fn: Callable[[str, str | None], str] = prompt,
    prompt_yes_no_fn: Callable[[str, bool], bool] = prompt_yes_no,
    runtime_config_module=runtime_config,
) -> Menu:
    """Return the export submenu used by the control panel."""

    def export_chain_bulk() -> None:
        symbol = prompt_fn("Ticker symbool: ", "")
        if not symbol:
            print("Geen symbool opgegeven")
            return
        try:
            run_module("tomic.cli.option_lookup_bulk", symbol)
        except Exception:
            print("❌ Export mislukt")

    def csv_check() -> None:
        path = prompt_fn("Pad naar CSV-bestand: ", "")
        if not path:
            print("Geen pad opgegeven")
            return
        try:
            run_module("tomic.cli.csv_quality_check", path)
        except Exception:
            print("❌ Kwaliteitscheck mislukt")

    def polygon_chain() -> None:
        symbol = prompt_fn("Ticker symbool: ", "").strip().upper()
        if not symbol:
            print("❌ Geen symbool opgegeven")
            return
        try:
            path = services.export.fetch_polygon_chain(symbol)
        except Exception as exc:
            print(f"❌ Ophalen van optionchain mislukt: {exc}")
            return
        if path:
            print(f"✅ Option chain opgeslagen in: {Path(path).resolve()}")
        else:
            date_dir = Path(cfg.get("EXPORT_DIR", "exports")) / datetime.now().strftime("%Y%m%d")
            print(f"⚠️ Geen exportbestand gevonden in {date_dir.resolve()}")

    def run_github_action() -> None:
        try:
            run_module("tomic.cli.fetch_prices_polygon")
        except Exception:
            print("❌ Ophalen van prijzen mislukt")
            return
        try:
            changed = services.export.git_commit(
                "Update price history",
                Path("tomic/data/spot_prices"),
                Path("tomic/data/iv_daily_summary"),
                Path("tomic/data/historical_volatility"),
            )
            if not changed:
                print("No changes to commit")
        except Exception:
            print("❌ Git-commando mislukt")

    def run_intraday_action() -> None:
        try:
            run_module("tomic.cli.fetch_intraday_polygon")
        except Exception:
            print("❌ Ophalen van intraday prijzen mislukt")
            return
        try:
            changed = services.export.git_commit(
                "Update intraday prices",
                Path("tomic/data/spot_prices"),
            )
            if not changed:
                print("No changes to commit")
        except Exception:
            print("❌ Git-commando mislukt")

    def fetch_earnings() -> None:
        try:
            run_module("tomic.cli.fetch_earnings_alpha")
        except Exception:
            print("❌ Earnings ophalen mislukt")

    def _format_changes_table(changes: list[dict[str, object]]) -> str:
        rows = []
        for idx, change in enumerate(changes, start=1):
            rows.append(
                [
                    idx,
                    change.get("symbol", ""),
                    change.get("old_future") or "-",
                    change.get("new_future") or "-",
                    change.get("action", ""),
                    int(change.get("removed_same_month", 0) or 0),
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
        return tabulate(rows, headers=headers, tablefmt="github")

    def import_market_chameleon_earnings() -> None:
        runtime_config_module.load()
        last_csv = runtime_config_module.get("import.last_earnings_csv_path") or ""
        csv_input = prompt_fn(
            "Voer pad in naar MarketChameleon-CSV (ENTER voor laatst gebruikt): ",
            last_csv,
        )
        if not csv_input:
            print("❌ Geen pad opgegeven")
            return
        csv_path = Path(csv_input).expanduser()
        if not csv_path.exists():
            print(f"❌ CSV niet gevonden: {csv_path}")
            return
        runtime_config_module.set_value("import.last_earnings_csv_path", str(csv_path))
        try:
            plan = build_import_plan(csv_path, runtime_config_module=runtime_config_module, cfg_module=cfg)
        except Exception as exc:  # pragma: no cover - parse errors
            logger.error("CSV import mislukt: %s", exc)
            print(f"❌ CSV import mislukt: {exc}")
            return
        if not plan.csv_map:
            print("ℹ️ Geen geldige earnings gevonden in CSV.")
            return
        try:
            changes = preview_changes(plan)
        except Exception as exc:  # pragma: no cover - update errors
            logger.error("Voorbereiden van import mislukt: %s", exc)
            print(f"❌ Voorbereiden van import mislukt: {exc}")
            return
        if not changes:
            print("ℹ️ Geen wijzigingen nodig volgens CSV.")
            return
        summary = summarise_changes(changes)
        print("\nDry-run wijzigingen:")
        print(_format_changes_table(changes))
        print(f"\nVerwijderd vanwege dezelfde maand: {summary['removed_same_month']}")
        print(
            "Samenvatting: totaal={total} vervangen={replaced} ingevoegd={inserted}".format(
                **summary
            )
        )
        if not prompt_yes_no_fn("Doorvoeren?", True):
            print("Import geannuleerd.")
            return
        try:
            updated, backup_path = apply_import(plan)
        except Exception as exc:  # pragma: no cover - filesystem errors
            logger.error("Opslaan van earnings JSON mislukt: %s", exc)
            print(f"❌ Opslaan mislukt: {exc}")
            return
        runtime_config_module.set_value("data.earnings_json_path", str(plan.json_path))
        if backup_path:
            print(f"Klaar. Backup: {backup_path}")
        else:
            print("Klaar. JSON bestand aangemaakt zonder backup.")
        logger.success(
            "Earnings import voltooid voor %s symbolen naar %s",
            len(changes),
            plan.json_path,
        )
        if not isinstance(updated, dict):  # pragma: no cover - defensive
            return

    menu = Menu("📁 DATA & MARKTDATA")
    menu.add("OptionChain ophalen via TWS API", export_chain_bulk)
    menu.add("OptionChain ophalen via Polygon API", polygon_chain)
    menu.add("Controleer CSV-kwaliteit", csv_check)
    menu.add("Run GitHub Action lokaal", run_github_action)
    menu.add("Run GitHub Action lokaal - intraday", run_intraday_action)
    menu.add(
        "Backfill historical_volatility obv spotprices",
        lambda: run_module("tomic.scripts.backfill_hv"),
    )
    menu.add("ATR Calculator", lambda: run_module("tomic.cli.atr_calculator"))
    menu.add("IV backfill", lambda: run_module("tomic.cli.iv_backfill_flow"))
    menu.add("Fetch Earnings", fetch_earnings)
    menu.add("Import nieuwe earning dates van MarketChameleon", import_market_chameleon_earnings)
    return menu


__all__ = ["build_export_menu"]
