from __future__ import annotations

"""Utilities for validating and inspecting rule configuration.

The commands defined here provide a safe way for non-developers to
inspect and validate the :mod:`tomic.criteria` configuration.  They can
optionally trigger a reload so a running service picks up the new
configuration without a restart.
"""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .. import criteria
from .. import config


def _load(path: str | None = None) -> criteria.RulesConfig:
    """Load rules from ``path`` re-reading the file every time."""
    criteria.load_rules.cache_clear()
    return criteria.load_rules(path)


def _show(path: str | None) -> int:
    """Display the current rules configuration."""
    cfg = _load(path)
    print(json.dumps(cfg.model_dump(), indent=2, sort_keys=True))
    return 0


def _validate(path: str | None, reload: bool = False) -> int:
    """Validate configuration file and optionally reload services."""
    cfg_path = Path(path) if path else Path(criteria.__file__).resolve().parent.parent / "criteria.yaml"
    if not cfg_path.exists():
        print(f"Configuration file not found: {cfg_path}")
        return 1
    try:
        cfg = _load(str(cfg_path))
    except ValidationError as exc:  # pragma: no cover - exercised in tests
        print("Invalid configuration:\n" + str(exc))
        return 1
    print("Configuration OK")
    if reload:
        # Update global state so long running processes pick up changes
        criteria.RULES = cfg
        config.reload()
        print("Reloaded running services")
    return 0


def _reload(path: str | None) -> int:
    """Reload configuration unconditionally."""
    cfg = _load(path)
    criteria.RULES = cfg
    config.reload()
    print("Reloaded running services")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage rules configuration")
    sub = parser.add_subparsers(dest="cmd")

    p_show = sub.add_parser("show", help="Display merged configuration")
    p_show.add_argument("path", nargs="?", help="Path to criteria.yaml")
    p_show.set_defaults(func=lambda a: _show(a.path))

    p_val = sub.add_parser("validate", help="Validate configuration file")
    p_val.add_argument("path", nargs="?", help="Path to criteria.yaml")
    p_val.add_argument("--reload", action="store_true", help="Reload after validation")
    p_val.set_defaults(func=lambda a: _validate(a.path, reload=a.reload))

    p_rel = sub.add_parser("reload", help="Reload configuration")
    p_rel.add_argument("path", nargs="?", help="Path to criteria.yaml")
    p_rel.set_defaults(func=lambda a: _reload(a.path))

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
