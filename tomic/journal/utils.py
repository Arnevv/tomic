import json
from pathlib import Path
from typing import Any, Iterable, List, Union

from tomic.config import get as cfg_get

JOURNAL_FILE = Path(cfg_get("JOURNAL_FILE", "journal.json"))


PathLike = Union[str, Path]


def load_journal(path: PathLike = JOURNAL_FILE) -> List[Any]:
    """Return parsed journal data or an empty list if file is missing."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_journal(journal: Iterable[Any], path: PathLike = JOURNAL_FILE) -> None:
    """Write journal data back to ``path``."""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(list(journal), f, indent=2)
