import os
from datetime import datetime, date
from pathlib import Path
import math
import re

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.helpers.csv_utils import parse_euro_float


def filter_future_expiries(expirations: list[str]) -> list[str]:
    """Return expiries after :func:`today` sorted chronologically."""

    future_dates: list[date] = []
    today_date = today()
    for exp in expirations:
        try:
            dt = datetime.strptime(exp, "%Y%m%d").date()
        except Exception:
            continue
        if dt > today_date:
            future_dates.append(dt)

    future_dates.sort()
    return [d.strftime("%Y%m%d") for d in future_dates]


def _is_third_friday(dt: datetime) -> bool:
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_weekly(dt: datetime) -> bool:
    return dt.weekday() == 4 and not _is_third_friday(dt)


def extract_weeklies(expirations: list[str], count: int = 4) -> list[str]:
    """Return the next ``count`` weekly expiries from ``expirations``."""

    fridays = []
    for exp in filter_future_expiries(expirations):
        dt = datetime.strptime(exp, "%Y%m%d")
        if _is_weekly(dt):
            fridays.append(exp)
        if len(fridays) == count:
            break
    return fridays


def extract_monthlies(expirations: list[str], count: int = 3) -> list[str]:
    """Return the next ``count`` third-Friday expiries from ``expirations``."""

    months = []
    for exp in filter_future_expiries(expirations):
        dt = datetime.strptime(exp, "%Y%m%d")
        if _is_third_friday(dt):
            months.append(exp)
        if len(months) == count:
            break
    return months


def today() -> date:
    """Return ``TOMIC_TODAY`` or today's date."""

    env = os.getenv("TOMIC_TODAY")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    return date.today()


def select_near_atm(
    strikes: list[float],
    expiries: list[str],
    spot_price: float | None,
    *,
    width: int = 10,
    count: int = 4,
) -> tuple[list[str], list[float]]:
    """Return the first ``count`` expiries and strikes near ``spot_price``.

    Strikes are included when their rounded value is within ``width`` points of
    ``round(spot_price)``. This mirrors the subset used in
    :func:`fetch_single_option.run`.
    """

    center = round(spot_price or 0)
    sel_strikes = [s for s in strikes if abs(round(s) - center) <= width]
    return expiries[:count], sel_strikes


def load_price_history(symbol: str) -> list[dict]:
    """Return price history records for ``symbol`` sorted by date."""

    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if isinstance(data, list):
        data.sort(key=lambda r: r.get("date", ""))
        return data
    return []


def latest_close_date(symbol: str) -> str | None:
    """Return the most recent close date for ``symbol`` from price history."""

    data = load_price_history(symbol)
    if data:
        return str(data[-1].get("date"))
    return None


def get_option_mid_price(option: dict) -> float | None:
    """Return midpoint price for ``option`` or close price as fallback."""

    try:
        bid = float(option.get("bid"))
        ask = float(option.get("ask"))
        if not math.isnan(bid) and not math.isnan(ask) and bid > 0 and ask > 0:
            return (bid + ask) / 2
    except Exception:
        pass
    close = option.get("close")
    try:
        val = float(close) if close is not None else None
        if val is None or math.isnan(val):
            return None
        return val
    except Exception:
        return None


def prompt_user_for_price(
    strike: float | str,
    expiry: str | None,
    opt_type: str | None,
    position: int,
) -> float | None:
    """Return user-supplied mid price for ``strike`` if confirmed."""

    pos_txt = "long" if position > 0 else "short"
    right = normalize_right(opt_type or "") or opt_type or ""
    header = (
        f"\N{WARNING SIGN} Geen bid/ask/mid gevonden voor {pos_txt} {right} {strike}"
    )
    if expiry:
        header += f" (expiry: {expiry})"
    ans = input(f"{header}\nWil je handmatig een waarde invullen? [y/N]: ").strip().lower()
    if ans not in {"y", "yes"}:
        return None
    while True:
        val = input("Voer mid-prijs in (bijv. 0.25): ").strip().replace(",", ".")
        if val == "":
            return None
        try:
            price = float(val)
            if price > 0:
                return price
        except ValueError:
            pass
        ans = input("Ongeldige waarde. Opnieuw proberen? [y/N]: ").strip().lower()
        if ans not in {"y", "yes"}:
            break
    return None


def normalize_right(val: str) -> str:
    """Return normalized option right as 'call' or 'put'."""

    val = (val or "").strip().lower()
    if val in {"c", "call"}:
        return "call"
    if val in {"p", "put"}:
        return "put"
    return ""


def get_leg_right(leg: dict) -> str:
    """Return normalized option right for ``leg``.

    The ``leg`` dictionary may define the option right under either the
    ``right`` or ``type`` key.  This helper fetches whichever is available and
    returns it normalized as ``"call"`` or ``"put"`` using
    :func:`normalize_right`.
    """

    return normalize_right(leg.get("right") or leg.get("type"))


def get_leg_qty(leg: dict) -> float:
    """Return absolute quantity for ``leg``.

    The quantity may be specified under the ``"qty"``, ``"quantity"`` or
    ``"position"`` keys. If none of these keys are present, a default quantity
    of ``1`` is assumed.
    """

    return abs(
        float(leg.get("qty") or leg.get("quantity") or leg.get("position") or 1)
    )


def latest_atr(symbol: str) -> float | None:
    """Return the most recent ATR value for ``symbol`` from price history."""

    data = load_price_history(symbol)
    for rec in reversed(data):
        atr = rec.get("atr")
        try:
            if atr is not None:
                return float(atr)
        except Exception:
            continue
    return None


_NUMERIC_KEYS = {
    "delta",
    "mid",
    "edge",
    "margin",
    "pos",
    "credit",
    "strike",
    "bid",
    "ask",
    "close",
    "iv",
    "theta",
    "vega",
    "gamma",
    "volume",
    "open_interest",
}

# Legacy keys that may appear in CSVs without underscores or in other forms
LEGACY_LEG_KEYS = {
    "openinterest": "open_interest",
    "impliedvolatility": "iv",
    "implied_volatility": "iv",
    "delta": "delta",  # redundant but explicit
    "vega": "vega",
    "theta": "theta",
}


def normalize_leg(leg: dict) -> dict:
    """Cast numeric fields in ``leg`` to ``float`` if possible.

    CamelCase keys are converted to ``snake_case`` before numeric parsing.
    """

    for key in list(leg.keys()):
        canonical = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        canonical = LEGACY_LEG_KEYS.get(canonical, canonical)
        val = leg[key]
        if canonical in _NUMERIC_KEYS:
            leg[canonical] = parse_euro_float(val)
            if canonical != key:
                del leg[key]
        elif canonical != key:
            leg[canonical] = val
            del leg[key]
    return leg

