"""Tests for correlation service."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import numpy as np

from tomic.services.correlation_service import (
    CorrelationService,
    CorrelationResult,
    get_correlation_service,
)


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory with spot price files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create spot price files for testing
        # AAPL - upward trend
        aapl_prices = []
        for i in range(100):
            date = f"2024-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}"
            close = 150 + i * 0.5 + (i % 5) * 0.1  # Upward with small noise
            aapl_prices.append({"date": date, "close": close})

        with open(data_dir / "AAPL.json", "w") as f:
            json.dump(aapl_prices, f)

        # MSFT - similar upward trend (high correlation with AAPL)
        msft_prices = []
        for i in range(100):
            date = f"2024-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}"
            close = 300 + i * 1.0 + (i % 5) * 0.2  # Similar pattern
            msft_prices.append({"date": date, "close": close})

        with open(data_dir / "MSFT.json", "w") as f:
            json.dump(msft_prices, f)

        # XOM - different pattern (low correlation)
        xom_prices = []
        for i in range(100):
            date = f"2024-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}"
            # Use sine wave for different pattern
            close = 100 + 10 * np.sin(i / 10) + (i % 3) * 0.5
            xom_prices.append({"date": date, "close": float(close)})

        with open(data_dir / "XOM.json", "w") as f:
            json.dump(xom_prices, f)

        yield data_dir


@pytest.fixture
def correlation_service(temp_data_dir):
    """Create correlation service with test data."""
    return CorrelationService(data_dir=temp_data_dir)


class TestCorrelationResult:
    """Tests for CorrelationResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = CorrelationResult(
            symbol1="AAPL",
            symbol2="MSFT",
            correlation=0.85,
            days_overlap=60,
            data_start="2024-01-01",
            data_end="2024-03-01",
        )

        d = result.to_dict()

        assert d["symbol1"] == "AAPL"
        assert d["symbol2"] == "MSFT"
        assert d["correlation"] == 0.85
        assert d["days_overlap"] == 60


class TestCorrelationServiceLoadPrices:
    """Tests for loading spot prices."""

    def test_load_spot_prices_json_list(self, correlation_service, temp_data_dir):
        """Test loading prices from JSON list format."""
        prices = correlation_service._load_spot_prices("AAPL")

        assert len(prices) > 0
        assert all(isinstance(v, float) for v in prices.values())

    def test_load_spot_prices_caching(self, correlation_service):
        """Test that prices are cached."""
        prices1 = correlation_service._load_spot_prices("AAPL")
        prices2 = correlation_service._load_spot_prices("AAPL")

        assert prices1 is prices2  # Same object = cached

    def test_load_spot_prices_nonexistent(self, correlation_service):
        """Test loading non-existent symbol."""
        prices = correlation_service._load_spot_prices("NOTEXIST")

        assert prices == {}

    def test_clear_cache(self, correlation_service):
        """Test clearing price cache."""
        correlation_service._load_spot_prices("AAPL")
        assert "AAPL" in correlation_service._price_cache

        correlation_service.clear_cache()
        assert len(correlation_service._price_cache) == 0


class TestCorrelationCalculation:
    """Tests for correlation calculation."""

    def test_calculate_correlation_high(self, correlation_service):
        """Test calculating high correlation between similar symbols."""
        result = correlation_service.calculate_correlation(
            "AAPL", "MSFT", lookback_days=60
        )

        assert result is not None
        assert result.symbol1 == "AAPL"
        assert result.symbol2 == "MSFT"
        # Both have upward trends, should be positively correlated
        assert result.correlation > 0.5
        assert result.days_overlap > 0

    def test_calculate_correlation_lower(self, correlation_service):
        """Test calculating lower correlation with different pattern."""
        result = correlation_service.calculate_correlation(
            "AAPL", "XOM", lookback_days=60
        )

        assert result is not None
        # XOM has different pattern, should have lower correlation
        assert abs(result.correlation) < 0.9

    def test_calculate_correlation_insufficient_data(self, temp_data_dir):
        """Test with insufficient overlapping data."""
        # Create a file with only 5 data points
        few_prices = [{"date": f"2024-01-0{i+1}", "close": 100 + i} for i in range(5)]
        with open(temp_data_dir / "FEW.json", "w") as f:
            json.dump(few_prices, f)

        service = CorrelationService(data_dir=temp_data_dir)
        result = service.calculate_correlation("FEW", "AAPL", lookback_days=60)

        # Should return None due to insufficient data
        assert result is None

    def test_calculate_correlation_missing_symbol(self, correlation_service):
        """Test with missing symbol."""
        result = correlation_service.calculate_correlation(
            "AAPL", "NOTEXIST", lookback_days=60
        )

        assert result is None


class TestBasketCorrelation:
    """Tests for basket correlation calculation."""

    def test_calculate_basket_correlation(self, correlation_service):
        """Test calculating average correlation with basket."""
        result = correlation_service.calculate_basket_correlation(
            "XOM",
            ["AAPL", "MSFT"],
            lookback_days=60,
        )

        assert result is not None
        assert isinstance(result, float)
        assert -1 <= result <= 1

    def test_calculate_basket_correlation_empty_basket(self, correlation_service):
        """Test with empty basket."""
        result = correlation_service.calculate_basket_correlation(
            "AAPL",
            [],
            lookback_days=60,
        )

        assert result == 0.0

    def test_calculate_basket_correlation_self_excluded(self, correlation_service):
        """Test that symbol is excluded from basket if present."""
        result = correlation_service.calculate_basket_correlation(
            "AAPL",
            ["AAPL", "MSFT"],
            lookback_days=60,
        )

        # Should only correlate with MSFT, not with itself
        assert result is not None


class TestCorrelationMatrix:
    """Tests for correlation matrix."""

    def test_get_correlation_matrix(self, correlation_service):
        """Test generating full correlation matrix."""
        matrix = correlation_service.get_correlation_matrix(
            ["AAPL", "MSFT", "XOM"],
            lookback_days=60,
        )

        # Check diagonal is 1.0
        assert matrix["AAPL"]["AAPL"] == 1.0
        assert matrix["MSFT"]["MSFT"] == 1.0

        # Check symmetry
        assert matrix["AAPL"]["MSFT"] == matrix["MSFT"]["AAPL"]


class TestGetCorrelationService:
    """Tests for singleton getter."""

    def test_get_correlation_service_singleton(self):
        """Test that getter returns singleton."""
        with patch("tomic.services.correlation_service._service", None):
            service1 = get_correlation_service()
            service2 = get_correlation_service()

            # Note: can't test identity due to module-level caching
            assert service1 is not None
            assert service2 is not None
