"""Unified command line entry point using ``argparse``."""
from __future__ import annotations

import argparse

from . import controlpanel
from . import csv_quality_check
from . import option_lookup
from . import portfolio_scenario
from . import generate_proposals


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TOMIC command line utilities")
    sub = parser.add_subparsers(dest="cmd")

    sub_cp = sub.add_parser("controlpanel", help="Start interactieve control panel")
    sub_cp.set_defaults(func=lambda a: controlpanel.main())

    sub_csv = sub.add_parser("csv-quality-check", help="Controleer CSV-bestand")
    sub_csv.add_argument("path", nargs="?", help="Pad naar CSV")
    sub_csv.add_argument("symbol", nargs="?", help="Ticker symbool")
    sub_csv.set_defaults(
        func=lambda a: csv_quality_check.main(
            [a.path, a.symbol] if a.path else []
        )
    )

    sub_lookup = sub.add_parser("option-lookup", help="Zoek open interest op")
    sub_lookup.add_argument("symbol", nargs="?")
    sub_lookup.add_argument("expiry", nargs="?")
    sub_lookup.add_argument("strike", nargs="?")
    sub_lookup.add_argument("type", nargs="?")
    sub_lookup.set_defaults(
        func=lambda a: option_lookup.main(
            [a.symbol, a.expiry, a.strike, a.type] if a.symbol else []
        )
    )

    sub_scen = sub.add_parser("portfolio-scenario", help="Simuleer portfolio shift")
    sub_scen.add_argument("positions", nargs="?")
    sub_scen.set_defaults(
        func=lambda a: portfolio_scenario.main([a.positions] if a.positions else [])
    )

    sub_prop = sub.add_parser(
        "generate-proposals",
        help="Genereer strategievoorstellen",
    )
    sub_prop.add_argument("positions", nargs="?", help="Pad naar positions.json")
    sub_prop.add_argument("export_dir", nargs="?", help="Directory met optionchains")
    sub_prop.set_defaults(
        func=lambda a: generate_proposals.main(
            [p for p in [a.positions, a.export_dir] if p]
        )
    )

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
