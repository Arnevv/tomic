"""Analysis utilities."""

from .greeks import compute_portfolio_greeks, compute_greeks_by_symbol
from tomic.webdata.utils import download_html, parse_patterns
from .metrics import (
    compute_term_structure,
    render_kpi_box,
    historical_volatility,
    average_true_range,
)
from .vol_db import (
    PriceRecord,
    VolRecord,
    init_db,
    save_price_history,
    save_vol_stats,
)

__all__ = [
    "compute_portfolio_greeks",
    "compute_greeks_by_symbol",
    "compute_term_structure",
    "render_kpi_box",
    "historical_volatility",
    "average_true_range",
    "PriceRecord",
    "VolRecord",
    "init_db",
    "save_price_history",
    "save_vol_stats",
    "download_html",
    "parse_patterns",
]
