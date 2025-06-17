from __future__ import annotations

"""Simple SQLite store for price history and volatility stats."""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import sqlite3

from .metrics import historical_volatility


@dataclass
class PriceRecord:
    """Daily closing price for a symbol."""

    symbol: str
    date: str  # YYYY-MM-DD
    close: float
    volume: int | None = None
    atr: float | None = None


@dataclass
class VolRecord:
    """Snapshot of volatility statistics for a symbol."""

    symbol: str
    date: str
    iv: float | None
    hv30: float | None
    hv60: float | None
    hv90: float | None
    iv_rank: float | None
    iv_percentile: float | None


def init_db(path: str | Path) -> sqlite3.Connection:
    """Initialise SQLite database and return connection."""
    path = Path(path)
    # Ensure parent directories exist to avoid OperationalError on open
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS PriceHistory (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            volume INTEGER,
            atr REAL,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS VolStats (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            iv REAL,
            hv30 REAL,
            hv60 REAL,
            hv90 REAL,
            iv_rank REAL,
            iv_percentile REAL,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    conn.commit()
    return conn


def save_price_history(conn: sqlite3.Connection, records: Iterable[PriceRecord]) -> None:
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO PriceHistory (symbol, date, close, volume, atr) VALUES (?, ?, ?, ?, ?)",
        [(r.symbol, r.date, r.close, r.volume, r.atr) for r in records],
    )
    conn.commit()


def rolling_hv(closes: Sequence[float], *, window: int) -> list[float]:
    """Return list of HV values for all rolling windows."""
    result = []
    for i in range(window, len(closes) + 1):
        hv = historical_volatility(closes[i - window : i], window=window)
        if hv is not None:
            result.append(hv)
    return result


def iv_rank(iv: float, series: Sequence[float]) -> float | None:
    if not series:
        return None
    lo = min(series)
    hi = max(series)
    if hi == lo:
        return None
    return (iv - lo) / (hi - lo) * 100


def iv_percentile(iv: float, series: Sequence[float]) -> float | None:
    if not series:
        return None
    count = sum(1 for hv in series if hv < iv)
    return count / len(series) * 100


def save_vol_stats(
    conn: sqlite3.Connection,
    record: VolRecord,
    closes: Sequence[float],
) -> None:
    hv_series = rolling_hv(closes, window=30)
    # ``historical_volatility`` returns values as percentages (e.g. ``20`` for
    # ``20%``) whereas ``record.iv`` is stored as a decimal (e.g. ``0.2`` for
    # ``20%``).  Convert the IV to the same scale as the HV series before
    # computing rank and percentile so the statistics are meaningful.
    scaled_iv = record.iv * 100 if record.iv is not None else None
    rank = iv_rank(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
    pct = (
        iv_percentile(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
    )
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO VolStats (symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.symbol,
            record.date,
            record.iv,
            record.hv30,
            record.hv60,
            record.hv90,
            rank,
            pct,
        ),
    )
    conn.commit()


def get_latest_vol_stats(conn: sqlite3.Connection, symbol: str) -> VolRecord | None:
    """Return the most recent ``VolRecord`` for ``symbol`` or ``None``."""
    cur = conn.execute(
        "SELECT symbol, date, iv, hv30, hv60, hv90, iv_rank, iv_percentile "
        "FROM VolStats WHERE symbol=? ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return VolRecord(*row)


def load_latest_stats(
    conn: sqlite3.Connection, symbols: Iterable[str]
) -> dict[str, VolRecord]:
    """Return a mapping of symbol to latest ``VolRecord`` for ``symbols``."""
    result: dict[str, VolRecord] = {}
    for sym in symbols:
        rec = get_latest_vol_stats(conn, sym)
        if rec is not None:
            result[sym] = rec
    return result
