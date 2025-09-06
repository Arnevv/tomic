"""Utility helpers for portfolio-related CLI commands."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from tomic.config import get as cfg_get
from tomic.helpers.account import _fmt_money
from tomic.journal.utils import load_json
from tomic.logutils import logger


def load_positions(path: str) -> List[Dict[str, Any]]:
    """Load positions JSON file and return list of open positions."""
    data = load_json(path)
    return [p for p in data if p.get("position")]


def load_account_info(path: str) -> dict:
    """Load account info JSON file and return as dict."""
    if not os.path.exists(path):
        return {}
    try:
        return load_json(path)
    except json.JSONDecodeError as e:  # pragma: no cover - invalid JSON
        print(f"\u26a0\ufe0f Kan accountinfo niet laden uit {path}: {e}")
        return {}


def refresh_portfolio_data() -> None:
    """Fetch latest portfolio data via the IB API and update timestamp."""
    from tomic.api import getaccountinfo

    logger.info("\ud83d\udd04 Vernieuw portfolio data via getaccountinfo")
    try:
        getaccountinfo.main()
    except Exception as exc:  # pragma: no cover - network/IB errors
        logger.error(f"\u274c Fout bij ophalen portfolio: {exc}")
        return

    meta_path = Path(cfg_get("PORTFOLIO_META_FILE", "portfolio_meta.json"))
    try:
        meta_path.write_text(json.dumps({"last_update": datetime.now().isoformat()}))
    except OSError as exc:  # pragma: no cover - I/O errors
        logger.error(f"\u26a0\ufe0f Kan meta file niet schrijven: {exc}")


def print_account_summary(values: dict, portfolio: dict) -> None:
    """Print concise one-line account overview with icons."""
    net_liq = values.get("NetLiquidation")
    margin = values.get("InitMarginReq")
    used_pct = None
    try:
        used_pct = (float(margin) / float(net_liq)) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        used_pct = None
    delta = portfolio.get("Delta")
    vega = portfolio.get("Vega")
    parts = [
        f"\ud83d\udcb0 Netliq: {_fmt_money(net_liq)}",
        f"\ud83c\udfe6 Margin used: {_fmt_money(margin)}",
    ]
    parts.append(f"\ud83d\udcc9 \u0394: {delta:+.2f}" if delta is not None else "\ud83d\udcc9 \u0394: n.v.t.")
    parts.append(
        f"\ud83d\udcc8 Vega: {vega:+.0f}" if vega is not None else "\ud83d\udcc8 Vega: n.v.t."
    )
    if used_pct is not None:
        parts.append(f"\ud83d\udce6 Used: {used_pct:.0f}%")
    print("=== ACCOUNT ===")
    print(" | ".join(parts))
