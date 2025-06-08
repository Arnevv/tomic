"""Analysis utilities."""

from .greeks import compute_portfolio_greeks, compute_greeks_by_symbol
from .volatility_fetcher import download_html, parse_patterns
from .metrics import (
    compute_term_structure,
    render_kpi_box,
    historical_volatility,
    average_true_range,
)

__all__ = [
    "compute_portfolio_greeks",
    "compute_greeks_by_symbol",
    "compute_term_structure",
    "render_kpi_box",
    "historical_volatility",
    "average_true_range",
    "download_html",
    "parse_patterns",
]
