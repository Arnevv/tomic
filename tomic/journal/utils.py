import json
from pathlib import Path
from typing import Any, List

from tomic.config import get as cfg_get

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))


def load_journal(path: Path = JOURNAL_FILE) -> List[Any]:
    """Return parsed journal data or an empty list if file is missing."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_journal(journal: List[Any], path: Path = JOURNAL_FILE) -> None:
    """Write journal data back to ``path``."""
    with path.open("w", encoding="utf-8") as f:
        json.dump(journal, f, indent=2)
