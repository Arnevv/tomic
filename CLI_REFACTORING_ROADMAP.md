# CLI Code Refactoring Roadmap

## Quick Reference: Critical Issues

### File Size & Issues Count
```
controlpanel/portfolio_ui.py    888 lines  → 4 major issues    [CRITICAL]
portfolio/menu_flow.py          695 lines  → 3 major issues    [CRITICAL]
rejections/handlers.py          608 lines  → 3 major issues    [HIGH]
strategy_dashboard.py           547 lines  → 7 major issues    [CRITICAL]
controlpanel/__init__.py        535 lines  → Multiple issues   [HIGH]
iv_backfill_flow.py            390 lines  → 6 major issues    [CRITICAL]
exit_flow.py                   351 lines  → 2 major issues    [HIGH]
```

**Total: 40+ instances of mixed concerns across 7 files**

---

## Business Logic Embedded in CLI (Cannot be unit tested)

### 1. Financial Calculations in Presentation Layer
- **ROM Calculation** (strategy_dashboard.py:253)
  - `rom_now = (pnl_val / margin_ref) * 100`
  - Should move to: `tomic/services/metrics_calculation.py`

- **Theta Efficiency Rating** (strategy_dashboard.py:267)
  - Threshold-based logic (< 0.5, < 1.5, < 2.5)
  - Should move to: `tomic/analysis/greeks_analysis.py`

- **Average Contract Price** (strategy_dashboard.py:247)
  - `avg_price = cost_basis / total_contracts`
  - Should move to: `tomic/analysis/position_analysis.py`

- **Spot Change Percentage** (strategy_dashboard.py:181)
  - `diff_pct = ((spot_now - spot_open) / spot_open) * 100`
  - Should move to: `tomic/metrics.py`

### 2. Data Processing in Presentation Layer
- **CSV Parsing with Validation** (iv_backfill_flow.py:107-145)
  - Should move to: `tomic/services/iv_data_service.py`

- **Date Parsing Logic** (iv_backfill_flow.py:74-97)
  - Should move to: `tomic/helpers/date_parsing.py`

- **Data Merging Algorithm** (iv_backfill_flow.py:208-239)
  - Should move to: `tomic/services/data_merge_service.py`

- **Gap Analysis** (iv_backfill_flow.py:181-194)
  - Should move to: `tomic/analysis/iv_analysis.py`

### 3. Aggregation Logic in Display
- **Portfolio Aggregations** (strategy_dashboard.py:458-478)
  - Type counts, delta aggregation, vega totals, DTE averaging, PnL/margin totals
  - Should move to: `tomic/services/portfolio_aggregation.py`

### 4. API Calls in Presentation Functions
- **Proposal Refresh in Display** (controlpanel/portfolio_ui.py:350)
  - `portfolio_services.refresh_proposal_from_ib()` in `_show_proposal_details()`
  - Should move to: `tomic/services/proposal_refresh_service.py`

- **Spot Price Fetching in Display** (controlpanel/portfolio_ui.py:543, 651)
  - Multiple API calls in `show_market_info()`
  - Should move to: `tomic/services/market_info_service.py`

- **Data Loading in Main Flow** (portfolio/menu_flow.py:164-175)
  - Multiple `load_*` calls in orchestration function
  - Should move to: Service layer

---

## Orchestration Mixing Multiple Responsibilities

### 1. strategy_dashboard.py:main() - 176 lines
```
Lines 432-448: Data loading
Lines 455-457: Data grouping & organization
Lines 458-478: Portfolio aggregations & calculations
Lines 490-515: Alert generation & severity evaluation
Lines 518-527: Portfolio strategy presentation
```
**Split into:**
- `PortfolioDataLoader` service
- `PortfolioPresenter` for display

### 2. portfolio/menu_flow.py:process_chain() - 140 lines
```
Lines 133-138: Chain preparation
Lines 140-162: Interpolation & user interaction
Lines 164-175: Spot price resolution
Lines 181-191: Chain evaluation setup & execution
Lines 192-212: Presentation & rejection summary
```
**Split into:**
- `ChainProcessor` service
- `ChainEvaluationOrchestrator` service
- `ChainProcessingFlow` CLI wrapper

### 3. iv_backfill_flow.py:run_iv_backfill_flow() - 139 lines
```
Lines 245-258: User input & validation
Lines 260-269: CSV parsing
Lines 276-282: Existing data loading
Lines 290-315: Data analysis & comparison
Lines 318-340: Summary table generation
Lines 365-379: Data merging & persistence
```
**Split into:**
- `IVDataService` for all operations
- `IVBackfillOrchestrator` for coordination
- `IVBackfillInteractiveFlow` CLI wrapper

---

## Refactoring Phases

### Phase 1: Extract Calculation Services (Week 1)
**Priority: HIGHEST** - Enables unit testing of core metrics

```python
# NEW: tomic/services/metrics_calculation.py
def calculate_rom(pnl: float, margin: float) -> float:
    """Calculate Return on Margin percentage."""
    return (pnl / margin) * 100 if margin else 0.0

def calculate_theta_efficiency(theta: float, margin: float) -> float:
    """Calculate theta as percentage of margin."""
    return abs(theta / margin) * 100 if margin else 0.0

def rate_theta_efficiency(efficiency: float) -> tuple[str, str]:
    """Rate theta efficiency and return rating + emoji."""
    if efficiency < 0.5:
        return ("uninteresting", "⚠️")
    elif efficiency < 1.5:
        return ("acceptable", "🟡")
    elif efficiency < 2.5:
        return ("good", "✅")
    else:
        return ("ideal", "🟢")

def calculate_spot_change_percent(current: float, open_price: float) -> float | None:
    """Calculate spot price change as percentage."""
    try:
        return ((current - open_price) / open_price) * 100
    except (ZeroDivisionError, TypeError):
        return None
```

**Test examples:**
```python
def test_calculate_rom():
    assert calculate_rom(100, 1000) == 10.0
    assert calculate_rom(0, 1000) == 0.0

def test_theta_efficiency_rating():
    efficiency = calculate_theta_efficiency(5.0, 1000)
    rating, emoji = rate_theta_efficiency(efficiency)
    assert emoji == "✅"  # 0.5% is "good"
```

### Phase 2: Extract Portfolio Services (Week 1-2)
**Priority: HIGH** - Enables portfolio metrics testing

```python
# NEW: tomic/services/portfolio_aggregation.py
class PortfolioAggregator:
    def __init__(self, strategies: Sequence[dict]):
        self.strategies = strategies
    
    def aggregate_deltas(self) -> float:
        """Sum all delta dollars across strategies."""
        return sum(
            s.get("delta_dollar", 0) 
            for s in self.strategies 
            if isinstance(s.get("delta_dollar"), (int, float))
        )
    
    def aggregate_vega(self) -> float:
        """Sum all vega across strategies."""
        return sum(
            s.get("vega", 0) 
            for s in self.strategies 
            if isinstance(s.get("vega"), (int, float))
        )
    
    def calculate_portfolio_rom(self) -> float:
        """Calculate average ROM across portfolio."""
        total_pnl = sum(...)
        total_margin = sum(...)
        return calculate_rom(total_pnl, total_margin) if total_margin else 0.0
```

### Phase 3: Extract IV Data Services (Week 2)
**Priority: HIGH** - Enables data processing testing

```python
# NEW: tomic/services/iv_data_service.py
class IVCsvParser:
    def parse(self, path: Path) -> CsvParseResult:
        """Parse IV CSV with validation."""
        # Move logic from read_iv_csv()
        ...

class DateGapAnalyzer:
    def find_gaps(self, dates: Sequence[str]) -> list[tuple[str, str, int]]:
        """Find gaps in date sequence."""
        # Move logic from _collect_gaps()
        ...

class IVDataMerger:
    def merge(self, target: Path, new_records: Sequence[dict]) -> tuple[list[dict], Path | None]:
        """Merge IV data with atomic writes."""
        # Move logic from _merge_records()
        ...
```

### Phase 4: Refactor Large CLI Files (Week 3)
**Priority: MEDIUM** - Improves maintainability

1. **strategy_dashboard.py**
   - Extract `_load_positions()`, `_load_account()`, `_load_journal()` → Service
   - Extract calculations to Phase 1 services
   - Keep only print/format functions

2. **controlpanel/portfolio_ui.py**
   - Extract `_show_proposal_details()` → Service + thin wrapper
   - Extract `show_market_info()` → Service layer
   - Extract `_print_factsheet()` → Presenter only

3. **portfolio/menu_flow.py**
   - Extract `process_chain()` → `ChainProcessingOrchestrator` service
   - Extract spot price resolution → `SpotPriceResolver` service
   - Keep only menu flow wrapper

4. **iv_backfill_flow.py**
   - Extract `run_iv_backfill_flow()` → `IVBackfillOrchestrator` service
   - Keep only interactive menu wrapper

---

## Testing Impact

### Current State
```python
# CANNOT TEST - requires full CLI execution
from tomic.cli.strategy_dashboard import calculate_rom
# ❌ ImportError: calculate_rom is not in this module
# ❌ Even if imported, requires loading positions.json, account_info.json, etc.
```

### After Refactoring
```python
# CAN TEST - isolated business logic
from tomic.services.metrics_calculation import calculate_rom

def test_calculate_rom():
    assert calculate_rom(100, 1000) == 10.0  # ✅ PASS

# NO MOCKING NEEDED - no external dependencies
```

---

## Quick Impact Summary

| Aspect | Current | After Refactoring |
|--------|---------|-------------------|
| **Testable Code** | ~10% | ~80% |
| **CLI File Size** | 888 lines max | <200 lines (thin wrapper) |
| **Business Logic Locations** | Spread across 7+ files | Centralized in services |
| **Unit Test Coverage** | Impossible for calculations | >90% possible |
| **Code Reusability** | Low (CLI-specific) | High (service layer) |
| **Maintainability** | Difficult (mixed concerns) | Easy (separation) |

---

## Implementation Checklist

- [ ] **Week 1:**
  - [ ] Create `tomic/services/metrics_calculation.py` with 4 functions
  - [ ] Extract financial calculations from `strategy_dashboard.py`
  - [ ] Write unit tests for all metrics functions
  - [ ] Create `tomic/services/portfolio_aggregation.py`

- [ ] **Week 2:**
  - [ ] Create `tomic/services/iv_data_service.py`
  - [ ] Extract IV data operations from `iv_backfill_flow.py`
  - [ ] Create `tomic/helpers/date_parsing.py`
  - [ ] Refactor `iv_backfill_flow.py` to use new services

- [ ] **Week 3:**
  - [ ] Refactor `strategy_dashboard.py` - extract calculations
  - [ ] Refactor `controlpanel/portfolio_ui.py` - extract proposal service
  - [ ] Create proposal refresh/presentation services
  - [ ] Write integration tests

- [ ] **Week 4:**
  - [ ] Refactor `portfolio/menu_flow.py` - extract orchestration
  - [ ] Create `ChainProcessingOrchestrator` service
  - [ ] Refactor `rejections/handlers.py` - extract business logic
  - [ ] Final integration testing & documentation

---

## Files to Create (New Services)

1. `tomic/services/metrics_calculation.py` - Financial metrics
2. `tomic/services/portfolio_aggregation.py` - Portfolio aggregations
3. `tomic/services/iv_data_service.py` - IV data processing
4. `tomic/services/proposal_refresh_service.py` - Proposal data fetching
5. `tomic/services/market_info_service.py` - Market snapshot processing
6. `tomic/helpers/date_parsing.py` - Date parsing utilities
7. `tomic/analysis/iv_analysis.py` - IV-specific analytics
8. `tomic/analysis/greeks_analysis.py` - Greeks rating & analysis

---

## Key Principle

> **Move all business logic OUT of CLI files.**
> 
> CLI files should only:
> 1. Accept user input
> 2. Call service methods
> 3. Format and display results
