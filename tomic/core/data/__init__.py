"""Core data providers used by pricing services."""

from .interest_rates import InterestRateProvider, InterestRateQuote

__all__ = ["InterestRateProvider", "InterestRateQuote"]
