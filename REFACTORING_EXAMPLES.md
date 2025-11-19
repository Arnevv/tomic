# Refactoring Examples: Before & After

## Example 1: Extracting ROM Calculation

### BEFORE: Business Logic in CLI (strategy_dashboard.py:250-254)

```python
def print_strategy_full(strategy, *, details: bool = False):
    """Print a strategy with entry info, current status, KPI box and alerts."""
    # ... lots of code ...
    
    pnl_val = strategy.get("unrealizedPnL")
    if pnl_val is not None:
        margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
        rom_now = (pnl_val / margin_ref) * 100  # ← BUSINESS LOGIC HERE
        mgmt_lines.append(f"📍 PnL: {pnl_val:+.2f} (ROM: {rom_now:+.1f}%)")
    # ... more code ...
```

**Problems:**
- ROM calculation cannot be tested independently
- If formula changes, must update CLI AND all tests that depend on it
- Hard to reuse in other places (other CLI files, notebooks, etc.)

### AFTER: Business Logic in Service Layer

**1. Create `tomic/services/metrics_calculation.py`:**
```python
"""Financial metrics calculations for options strategies."""

def calculate_rom(pnl: float, margin: float) -> float:
    """Calculate Return on Margin as percentage.
    
    Args:
        pnl: Profit/loss value
        margin: Margin used for the position
        
    Returns:
        ROM percentage (e.g., 10.0 for 10%)
        
    Examples:
        >>> calculate_rom(100, 1000)
        10.0
        >>> calculate_rom(-50, 1000)
        -5.0
    """
    if not margin or margin == 0:
        return 0.0
    return (pnl / margin) * 100


def calculate_theta_efficiency(theta: float, margin: float) -> float:
    """Calculate theta as percentage of margin.
    
    Theta efficiency measures how much daily P&L a strategy generates
    per $1,000 of margin used.
    
    Args:
        theta: Theta value (daily P&L from theta)
        margin: Margin used (default 1000)
        
    Returns:
        Theta efficiency as percentage
    """
    if not margin or margin == 0:
        return 0.0
    return abs(theta / margin) * 100


def rate_theta_efficiency(efficiency: float) -> tuple[str, str]:
    """Rate theta efficiency with label and emoji.
    
    Args:
        efficiency: Theta efficiency percentage
        
    Returns:
        (rating_label, emoji) tuple
    """
    if efficiency < 0.5:
        return ("uninteresting", "⚠️")
    elif efficiency < 1.5:
        return ("acceptable", "🟡")
    elif efficiency < 2.5:
        return ("good", "✅")
    else:
        return ("ideal", "🟢")
```

**2. Write unit tests `tests/test_metrics_calculation.py`:**
```python
import pytest
from tomic.services.metrics_calculation import (
    calculate_rom,
    calculate_theta_efficiency,
    rate_theta_efficiency,
)


class TestCalculateROM:
    def test_positive_rom(self):
        assert calculate_rom(100, 1000) == 10.0
    
    def test_negative_rom(self):
        assert calculate_rom(-100, 1000) == -10.0
    
    def test_zero_pnl(self):
        assert calculate_rom(0, 1000) == 0.0
    
    def test_zero_margin_returns_zero(self):
        assert calculate_rom(100, 0) == 0.0
    
    def test_none_margin_returns_zero(self):
        assert calculate_rom(100, None) == 0.0


class TestThetaEfficiencyRating:
    def test_uninteresting_rating(self):
        rating, emoji = rate_theta_efficiency(0.3)
        assert rating == "uninteresting"
        assert emoji == "⚠️"
    
    def test_acceptable_rating(self):
        rating, emoji = rate_theta_efficiency(1.0)
        assert rating == "acceptable"
        assert emoji == "🟡"
    
    def test_good_rating(self):
        rating, emoji = rate_theta_efficiency(2.0)
        assert rating == "good"
        assert emoji == "✅"
    
    def test_ideal_rating(self):
        rating, emoji = rate_theta_efficiency(3.0)
        assert rating == "ideal"
        assert emoji == "🟢"
```

**3. Refactor `strategy_dashboard.py`:**
```python
from tomic.services.metrics_calculation import (
    calculate_rom,
    calculate_theta_efficiency,
    rate_theta_efficiency,
)

def print_strategy_full(strategy, *, details: bool = False):
    """Print a strategy with entry info, current status, KPI box and alerts."""
    # ... lots of code ...
    
    pnl_val = strategy.get("unrealizedPnL")
    if pnl_val is not None:
        margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
        rom_now = calculate_rom(pnl_val, margin_ref)  # ← USE SERVICE
        mgmt_lines.append(f"📍 PnL: {pnl_val:+.2f} (ROM: {rom_now:+.1f}%)")
    
    # ... more code ...
    
    margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    if theta is not None and margin:
        theta_efficiency = calculate_theta_efficiency(theta, margin)  # ← USE SERVICE
        rating_label, emoji = rate_theta_efficiency(theta_efficiency)  # ← USE SERVICE
        mgmt_lines.append(
            f"📍 Theta-rendement: {theta_efficiency:.2f}% per $1.000 margin - {emoji} {rating_label}"
        )
```

**Benefits:**
- ROM calculation can now be tested independently: `test_calculate_rom()`
- Rating logic can be tested independently: `test_theta_efficiency_rating()`
- Can be reused in reports, notebooks, other CLI functions
- Formula changes only require updating the service and its tests
- Easy to understand business logic in isolation

---

## Example 2: Extracting Portfolio Aggregation

### BEFORE: Multiple Calculations in Display (strategy_dashboard.py:458-478)

```python
def main(argv=None):
    # ... data loading ...
    
    strategies = group_strategies(positions, journal)
    strategies.sort(key=lambda s: trade_id_key(s.get("trade_id")))
    compute_term_structure(strategies)
    
    # ← BUSINESS LOGIC EMBEDDED IN MAIN
    type_counts = defaultdict(int)
    total_delta_dollar = 0.0
    total_vega = 0.0
    dtes = []
    total_pnl = 0.0
    total_margin = 0.0
    for s in strategies:
        type_counts[s.get("type")] += 1
        if s.get("delta_dollar") is not None:
            total_delta_dollar += s["delta_dollar"]
        if s.get("vega") is not None:
            total_vega += s["vega"]
        if s.get("days_to_expiry") is not None:
            dtes.append(s["days_to_expiry"])
        pnl_val = s.get("unrealizedPnL")
        margin_ref = s.get("init_margin") or s.get("margin_used") or 1000
        if pnl_val is not None:
            total_pnl += pnl_val
            total_margin += margin_ref
    
    avg_rom = (total_pnl / total_margin) * 100 if total_margin else 0.0
    
    print("=== Portfolio-overzicht ===")
    print(f"- Aantal strategieën: {len(strategies)}")
    print(f"- Gemiddeld ROM: {avg_rom:.1f}%")
    print(f"- Netto Δ$: ${total_delta_dollar:,.0f}")
    print(f"- Totale vega: {total_vega:+.2f}")
    if dtes:
        avg_dte = sum(dtes) / len(dtes)
        print(f"- Gemiddelde DTE: {avg_dte:.1f} dagen")
```

**Problems:**
- Multiple responsibility: data loading, aggregation, AND display
- Aggregations can't be tested without loading files
- Hard to reuse aggregations in other contexts

### AFTER: Service + Presenter Pattern

**1. Create `tomic/services/portfolio_aggregation.py`:**
```python
"""Portfolio-level aggregation and metrics."""
from dataclasses import dataclass
from typing import Sequence
from tomic.services.metrics_calculation import calculate_rom


@dataclass
class PortfolioMetrics:
    """Aggregated portfolio metrics."""
    strategy_count: int
    total_delta_dollar: float
    total_vega: float
    average_dte: float | None
    total_pnl: float
    total_margin: float
    average_rom: float
    strategy_type_counts: dict[str, int]


class PortfolioAggregator:
    """Aggregates metrics across all strategies in a portfolio."""
    
    def __init__(self, strategies: Sequence[dict]):
        self.strategies = strategies
    
    def aggregate(self) -> PortfolioMetrics:
        """Calculate all portfolio metrics.
        
        Returns:
            PortfolioMetrics dataclass with aggregated values
        """
        type_counts = {}
        total_delta_dollar = 0.0
        total_vega = 0.0
        dtes = []
        total_pnl = 0.0
        total_margin = 0.0
        
        for strategy in self.strategies:
            # Count strategies by type
            strategy_type = strategy.get("type")
            if strategy_type:
                type_counts[strategy_type] = type_counts.get(strategy_type, 0) + 1
            
            # Aggregate greeks
            if isinstance(strategy.get("delta_dollar"), (int, float)):
                total_delta_dollar += strategy["delta_dollar"]
            
            if isinstance(strategy.get("vega"), (int, float)):
                total_vega += strategy["vega"]
            
            # Collect DTEs
            if isinstance(strategy.get("days_to_expiry"), (int, float)):
                dtes.append(strategy["days_to_expiry"])
            
            # Aggregate P&L
            pnl_val = strategy.get("unrealizedPnL")
            margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
            if isinstance(pnl_val, (int, float)):
                total_pnl += pnl_val
                total_margin += margin_ref
        
        # Calculate averages
        average_dte = sum(dtes) / len(dtes) if dtes else None
        average_rom = calculate_rom(total_pnl, total_margin)
        
        return PortfolioMetrics(
            strategy_count=len(self.strategies),
            total_delta_dollar=total_delta_dollar,
            total_vega=total_vega,
            average_dte=average_dte,
            total_pnl=total_pnl,
            total_margin=total_margin,
            average_rom=average_rom,
            strategy_type_counts=type_counts,
        )
```

**2. Write tests `tests/test_portfolio_aggregation.py`:**
```python
from tomic.services.portfolio_aggregation import PortfolioAggregator


def test_aggregate_empty_portfolio():
    aggregator = PortfolioAggregator([])
    metrics = aggregator.aggregate()
    assert metrics.strategy_count == 0
    assert metrics.total_delta_dollar == 0.0


def test_aggregate_single_strategy():
    strategies = [{
        "type": "Iron Condor",
        "delta_dollar": 100,
        "vega": 5.0,
        "days_to_expiry": 30,
        "unrealizedPnL": 200,
        "init_margin": 1000,
    }]
    aggregator = PortfolioAggregator(strategies)
    metrics = aggregator.aggregate()
    
    assert metrics.strategy_count == 1
    assert metrics.total_delta_dollar == 100
    assert metrics.total_vega == 5.0
    assert metrics.average_dte == 30.0
    assert metrics.average_rom == 20.0  # 200/1000 * 100


def test_aggregate_multiple_strategies():
    strategies = [
        {
            "type": "Iron Condor",
            "delta_dollar": 100,
            "vega": 5.0,
            "days_to_expiry": 30,
            "unrealizedPnL": 200,
            "init_margin": 1000,
        },
        {
            "type": "Call Spread",
            "delta_dollar": -50,
            "vega": -2.0,
            "days_to_expiry": 15,
            "unrealizedPnL": -100,
            "init_margin": 500,
        },
    ]
    aggregator = PortfolioAggregator(strategies)
    metrics = aggregator.aggregate()
    
    assert metrics.strategy_count == 2
    assert metrics.total_delta_dollar == 50
    assert metrics.total_vega == 3.0
    assert metrics.average_dte == 22.5  # (30 + 15) / 2
    assert metrics.average_rom == 6.67  # 100/1500 * 100
```

**3. Create `tomic/formatting/portfolio_presenter.py`:**
```python
"""Format portfolio metrics for display."""
from tomic.services.portfolio_aggregation import PortfolioMetrics


class PortfolioPresenter:
    """Format aggregated portfolio metrics for CLI display."""
    
    @staticmethod
    def format_overview(metrics: PortfolioMetrics) -> str:
        """Format portfolio overview for display.
        
        Args:
            metrics: PortfolioMetrics object
            
        Returns:
            Formatted string for printing
        """
        lines = [
            "=== Portfolio-overzicht ===",
            f"- Aantal strategieën: {metrics.strategy_count}",
            f"- Gemiddeld ROM: {metrics.average_rom:.1f}%",
            f"- Netto Δ$: ${metrics.total_delta_dollar:,.0f}",
            f"- Totale vega: {metrics.total_vega:+.2f}",
        ]
        
        if metrics.average_dte is not None:
            lines.append(f"- Gemiddelde DTE: {metrics.average_dte:.1f} dagen")
        
        return "\n".join(lines)
```

**4. Refactor `strategy_dashboard.py:main()`:**
```python
from tomic.services.portfolio_aggregation import PortfolioAggregator
from tomic.formatting.portfolio_presenter import PortfolioPresenter

def main(argv=None):
    # ... data loading ...
    
    strategies = group_strategies(positions, journal)
    strategies.sort(key=lambda s: trade_id_key(s.get("trade_id")))
    compute_term_structure(strategies)
    
    # ← USE SERVICE
    aggregator = PortfolioAggregator(strategies)
    metrics = aggregator.aggregate()
    
    # ← USE PRESENTER
    print(PortfolioPresenter.format_overview(metrics))
    
    # ... rest of display ...
```

**Benefits:**
- `PortfolioAggregator` can be tested independently
- Aggregations can be reused in reports, APIs, notebooks
- Display formatting is separate and testable
- Easy to add new metrics without touching CLI code
- Easy to change how metrics are displayed

---

## Example 3: Extracting Data Processing

### BEFORE: CSV Parsing in CLI (iv_backfill_flow.py:107-145)

```python
def read_iv_csv(path: Path) -> CsvParseResult:
    """Lees een CSV-bestand en geef ATM IV records terug."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = sorted(REQUIRED_COLUMNS - set(fieldnames))
        if missing:
            raise ValueError(f"Ontbrekende kolommen in CSV: {', '.join(missing)}")
        
        # ... 25+ lines of parsing logic ...
```

**Problems:**
- Complex validation logic can't be tested independently
- If CSV format changes, hard to isolate where changes are needed
- Hard to reuse in other data import flows

### AFTER: Service Layer

**1. Create `tomic/services/iv_data_service.py`:**
```python
"""IV data processing and persistence."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import csv
from datetime import datetime


REQUIRED_COLUMNS = {"Date", "IV30"}
IV_THRESHOLD = 0.03  # 3 percentage points


@dataclass
class CsvParseResult:
    """Results from parsing IV CSV."""
    records: list[dict[str, Any]]
    duplicates: list[str]
    invalid_dates: list[str]
    empty_rows: int


class IVCsvParser:
    """Parse IV data from CSV files."""
    
    def __init__(self, required_columns: set[str] | None = None):
        self.required_columns = required_columns or REQUIRED_COLUMNS
    
    def parse(self, path: Path) -> CsvParseResult:
        """Parse IV CSV file.
        
        Args:
            path: Path to CSV file
            
        Returns:
            CsvParseResult with parsed records
            
        Raises:
            ValueError: If required columns are missing
        """
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = sorted(self.required_columns - set(fieldnames))
            if missing:
                raise ValueError(f"Missing columns: {', '.join(missing)}")
            
            records_map = {}
            duplicates = []
            invalid_dates = []
            empty_rows = 0
            
            for row in reader:
                date_raw = row.get("Date")
                iv_raw = row.get("IV30")
                
                if not (date_raw and str(iv_raw).strip()):
                    empty_rows += 1
                    continue
                
                parsed_date = self._parse_date(date_raw)
                if not parsed_date:
                    invalid_dates.append(str(date_raw).strip())
                    continue
                
                atm_iv = self._parse_iv(iv_raw)
                if atm_iv is None:
                    empty_rows += 1
                    continue
                
                record = {"date": parsed_date, "atm_iv": atm_iv}
                if parsed_date in records_map:
                    duplicates.append(parsed_date)
                records_map[parsed_date] = record
            
            sorted_records = sorted(records_map.values(), key=lambda r: r["date"])
            return CsvParseResult(sorted_records, duplicates, invalid_dates, empty_rows)
    
    @staticmethod
    def _parse_date(raw: str) -> str | None:
        """Parse date string to YYYY-MM-DD format."""
        value = str(raw).strip()
        if not value:
            return None
        
        formats = [
            "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y",
            "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
            "%d.%m.%Y", "%Y%m%d",
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
    
    @staticmethod
    def _parse_iv(raw: Any) -> float | None:
        """Parse IV value (percentage to decimal)."""
        from tomic.helpers.csv_utils import parse_euro_float
        value = parse_euro_float(raw if isinstance(raw, str) else str(raw))
        return value / 100.0 if value is not None else None
```

**2. Write tests:**
```python
from pathlib import Path
import tempfile
from tomic.services.iv_data_service import IVCsvParser


def test_parse_valid_csv():
    """Test parsing a valid IV CSV."""
    csv_content = "Date,IV30\n2024-01-01,25.5\n2024-01-02,26.0\n"
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        f.flush()
        
        parser = IVCsvParser()
        result = parser.parse(Path(f.name))
        
        assert len(result.records) == 2
        assert result.records[0]["date"] == "2024-01-01"
        assert result.records[0]["atm_iv"] == 0.255
        assert len(result.duplicates) == 0
        assert result.empty_rows == 0


def test_parse_handles_duplicates():
    """Test that duplicates are detected."""
    csv_content = "Date,IV30\n2024-01-01,25.5\n2024-01-01,26.0\n"
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        f.flush()
        
        parser = IVCsvParser()
        result = parser.parse(Path(f.name))
        
        assert len(result.records) == 1
        assert len(result.duplicates) == 1
        assert result.duplicates[0] == "2024-01-01"
```

**Benefits:**
- Parsing can be tested independently with test data
- Easy to add new date formats
- Easy to add validation rules
- Can be reused in other import flows
- Changes to format only affect this one class

---

## Key Takeaways

1. **Extract calculations to services** (ROM, theta efficiency, etc.)
2. **Extract data processing to services** (parsing, validation, merging)
3. **Extract aggregations to services** (portfolio metrics, summaries)
4. **Keep CLI files focused on IO and presentation**
5. **Write unit tests for all extracted services**
6. **Use presenter classes for display formatting**

This pattern makes the code:
- Testable (each service can be tested independently)
- Reusable (services can be used in multiple contexts)
- Maintainable (changes are isolated to one place)
- Clear (separation of concerns)

