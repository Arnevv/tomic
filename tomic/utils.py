import os
from datetime import datetime, date
from pathlib import Path
import math
import re
from typing import Any, Callable, Mapping, Literal, Optional, TypedDict

from tomic.config import get as cfg_get
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.helpers.csv_utils import parse_euro_float


class OptionLeg(TypedDict, total=False):
    """Normalized representation of an option leg used for strategy scoring."""

    expiry: Optional[str]
    type: Optional[str]
    strike: Optional[float]
    spot: Optional[float]
    iv: Optional[float]
    delta: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    model: Optional[float]
    edge: Optional[float]
    volume: Optional[float]
    open_interest: Optional[float]
    position: int
    mid_fallback: Optional[str]
    missing_metrics: list[str] | None
    metrics_ignored: bool | None

def today() -> date:
    """Return ``TOMIC_TODAY`` or today's date."""

    env = os.getenv("TOMIC_TODAY")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    return date.today()




def filter_future_expiries(expirations: list[str]) -> list[str]:
    """Return expiries after :func:`today` sorted chronologically."""

    from tomic.helpers.dateutils import parse_date

    future_dates: list[date] = []
    today_date = today()
    for exp in expirations:
        dt = parse_date(exp)
        if dt and dt > today_date:
            future_dates.append(dt)

    future_dates.sort()
    return [d.strftime("%Y%m%d") for d in future_dates]


def _is_third_friday(dt: date) -> bool:
    return dt.weekday() == 4 and 15 <= dt.day <= 21


def _is_weekly(dt: date) -> bool:
    return dt.weekday() == 4 and not _is_third_friday(dt)


def extract_expiries(
    expirations: list[str],
    count: int,
    predicate: Callable[[date], bool],
) -> list[str]:
    """Return the next ``count`` expiries matching ``predicate``."""

    from tomic.helpers.dateutils import parse_date

    selected: list[str] = []
    for exp in filter_future_expiries(expirations):
        dt = parse_date(exp)
        if dt and predicate(dt):
            selected.append(exp)
            if len(selected) == count:
                break
    return selected


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

    from tomic.helpers.price_utils import _load_latest_close

    return _load_latest_close(symbol, return_date_only=True)


def get_option_mid_price(option: dict) -> tuple[float | None, bool]:
    """Return midpoint price for ``option`` and whether close was used."""

    try:
        bid = float(option.get("bid"))
        ask = float(option.get("ask"))
        if not math.isnan(bid) and not math.isnan(ask) and bid > 0 and ask > 0:
            return (bid + ask) / 2, False
    except Exception:
        pass
    close = option.get("close")
    try:
        val = float(close) if close is not None else None
        if val is None or math.isnan(val):
            return None, False
        return val, True
    except Exception:
        return None, False


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


def build_leg(quote: Mapping[str, Any], side: Literal["long", "short"]) -> OptionLeg:
    """Construct a normalized leg dictionary from an option quote.

    ``quote`` may contain various option fields with differing naming
    conventions. The quote is first normalized via :func:`normalize_leg` after
    which only missing metrics (``mid``, ``model``, ``delta`` and ``edge``) are
    populated.
    """

    leg = normalize_leg(dict(quote))
    leg["position"] = 1 if side == "long" else -1

    mid_source = leg.get("mid_source")
    if leg.get("mid") in (None, "", 0, "0"):
        mid, used_close = get_option_mid_price(leg)
        leg["mid"] = mid
        if leg.get("mid_from_parity"):
            leg["mid_fallback"] = "parity"
        elif used_close:
            leg["mid_fallback"] = "close"
        elif mid_source in {"parity", "model", "close"}:
            leg["mid_fallback"] = mid_source
    else:
        if mid_source in {"parity", "model", "close"}:
            leg["mid_fallback"] = mid_source

    if mid_source:
        leg["mid_source"] = mid_source
    if "mid_reason" in leg:
        leg["mid_reason"] = leg.get("mid_reason")
    if "spread_flag" in leg:
        leg["spread_flag"] = leg.get("spread_flag")
    if "quote_age_sec" in leg:
        leg["quote_age_sec"] = leg.get("quote_age_sec")
    if "one_sided" in leg:
        leg["one_sided"] = bool(leg.get("one_sided"))

    from .helpers.bs_utils import populate_model_delta

    populate_model_delta(leg)

    if leg.get("edge") in (None, "", 0, "0"):
        mid = leg.get("mid")
        model = leg.get("model")
        if mid is not None and model is not None:
            leg["edge"] = model - mid

    return leg  # type: ignore[return-value]

