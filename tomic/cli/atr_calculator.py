from __future__ import annotations

"""Compute ATR values for stored price history."""

from pathlib import Path
from typing import List

from tomic.config import get as cfg_get
from tomic.logutils import setup_logging, logger
from tomic.journal.utils import load_json, save_json


def _compute_atrs(closes: List[float], period: int = 14) -> List[float]:
    """Return ATR values for ``closes`` using a simple moving average."""
    atrs: List[float] = []
    trs: List[float] = []
    for i, close in enumerate(closes):
        if i == 0:
            atrs.append(0.0)
        else:
            tr = abs(close - closes[i - 1])
            trs.append(tr)
            window = trs[-period:]
            atrs.append(sum(window) / len(window))
    return atrs


def _process_file(path: Path) -> int:
    data = load_json(path)
    if not isinstance(data, list):
        return 0
    data.sort(key=lambda r: r.get("date", ""))
    closes: List[float] = []
    for rec in data:
        try:
            close = float(rec.get("close"))
        except (TypeError, ValueError):
            close = 0.0
        closes.append(close)
    atrs = _compute_atrs(closes)
    updated = 0
    for rec, atr in zip(data, atrs):
        if rec.get("atr") != atr:
            rec["atr"] = atr
            updated += 1
    if updated:
        save_json(data, path)
    return updated


def main(argv: List[str] | None = None) -> None:
    """Compute ATR values for all price history files."""
    setup_logging()
    logger.info("🚧 Berekenen ATR waarden")
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    files = sorted(base.glob("*.json"))
    total = 0
    for f in files:
        try:
            changed = _process_file(f)
        except Exception as exc:  # pragma: no cover - unexpected file issue
            logger.warning(f"{f.name}: kon niet verwerken ({exc})")
            continue
        if changed:
            logger.info(f"{f.name}: {changed} records bijgewerkt")
            total += 1
    logger.success(f"✅ ATR bijgewerkt voor {total} bestanden")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
