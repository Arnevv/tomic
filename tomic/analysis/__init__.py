"""Analysis utilities."""

from .greeks import compute_portfolio_greeks
from .metrics import compute_term_structure, render_kpi_box

__all__ = ["compute_portfolio_greeks", "compute_term_structure", "render_kpi_box"]
