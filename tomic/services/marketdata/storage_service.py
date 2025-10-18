from __future__ import annotations

"""Storage helpers for historical volatility data."""

from pathlib import Path
from typing import Iterable, Sequence

from ...config import get as cfg_get
from ...journal.utils import load_json, save_json


class HistoricalVolatilityStorageService:
    """Manage reading and writing historical volatility files."""

    def __init__(self, base_dir: Path | None = None) -> None:
        default_dir = cfg_get(
            "HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"
        )
        self.base_dir = Path(base_dir or default_dir)

    def load(self, symbol: str) -> tuple[list[dict], Path]:
        """Load stored historical volatility records for ``symbol``."""

        path = self.base_dir / f"{symbol}.json"
        data = load_json(path)
        records = list(data) if isinstance(data, Sequence) else []
        records = [dict(record) for record in records if isinstance(record, dict)]
        records.sort(key=lambda r: r.get("date", ""))
        return records, path

    def append(self, symbol: str, new_records: Iterable[dict]) -> Path:
        """Append ``new_records`` to the stored file for ``symbol``."""

        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / f"{symbol}.json"
        existing = load_json(path)
        records = list(existing) if isinstance(existing, Sequence) else []
        records = [dict(record) for record in records if isinstance(record, dict)]
        records.extend(dict(record) for record in new_records)
        records.sort(key=lambda r: r.get("date", ""))
        save_json(records, path)
        return path
