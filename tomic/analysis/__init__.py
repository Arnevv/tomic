"""Analysis utilities."""

from .greeks import compute_portfolio_greeks
from .volatility_fetcher import download_html, parse_patterns
from .metrics import compute_term_structure, render_kpi_box

__all__ = [
    "compute_portfolio_greeks",
    "compute_term_structure",
    "render_kpi_box",
    "download_html",
    "parse_patterns",
]
