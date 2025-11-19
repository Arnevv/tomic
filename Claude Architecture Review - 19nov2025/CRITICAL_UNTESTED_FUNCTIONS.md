# Critical Untested Functions in TOMIC

## 1. Portfolio Service (Completely Untested)
**File**: `tomic/services/portfolio_service.py`

### Functions Needing Tests
```python
class PortfolioService:
    def build_candidate(...) -> Candidate  # Line ~80+
    def build_factsheet(...) -> Factsheet  # Line ~80+
    def rank_candidates(...) -> None       # Line ~80+
```

**Why Critical**: All trading recommendations depend on these. Portfolio metrics drive trading decisions.

**Test Requirements**:
- Unit test for Candidate creation (with/without mid sources, preview prices)
- Unit test for Factsheet generation (with/without earnings dates, IV data)
- Unit test for candidate ranking (score calculation, tie-breaking)
- Edge case: empty portfolio
- Edge case: missing metrics
- Edge case: extreme values (0.99 delta, 100+ gamma)

---

## 2. IB Connection Management (Minimal Testing)
**File**: `tomic/api/ib_connection.py`

### Functions Needing Tests
```python
def get_contract_details(contract, timeout_ms=None) -> Any  # Line 70
def request_snapshot_with_mdtype(...) -> dict               # Line 100+
def contractDetails(reqId, contractDetails) -> None          # Line 42
def contractDetailsEnd(reqId) -> None                        # Line 48
def tickPrice(reqId, tickType, price, attrib) -> None       # Line 54
def tickSnapshotEnd(reqId) -> None                          # Line 64
```

**Why Critical**: Connection failures cause silent data loss. Thread safety issues could corrupt data.

**Test Requirements**:
- Timeout handling (when wait() returns False)
- Error callback handling
- Thread safety (concurrent requests)
- Request cancellation (missing details)
- Negative price filtering (sentinel -1.0 values)
- Request ID tracking (no collisions)

---

## 3. Order Submission Validation (Partial Testing)
**File**: `tomic/services/order_submission.py`

### Functions Needing Tests
```python
class OrderSubmissionService:
    def validate(...) -> list[str]        # Validation logic
    def submit(...) -> None               # Submission logic
```

### Missing Edge Cases
- Quote age threshold violations (quote_age_sec > 5.0)
- Preview price blocking (mid_source = "model" should error)
- Missing bid/ask values
- Combo order max quote age (different from standard)
- Invalid combo leg ratios
- Zero credit orders (negative edge cases)

---

## 4. Configuration Functions (Completely Untested)
**File**: `tomic/services/_config.py`

### Functions Needing Tests
```python
def cfg_value(key: str, default: Any) -> Any                           # Line 15
def exit_spread_config() -> dict[str, Any]                             # Line 53
def exit_repricer_config() -> dict[str, Any]                           # Line 83
def exit_fallback_config() -> dict[str, Any]                           # Line 104
def exit_force_exit_config() -> dict[str, Any]                         # Line 133
def exit_price_ladder_config() -> dict[str, Any]                       # Line 168
```

**Why Critical**: These control critical exit behavior. Wrong config = broken exit logic.

**Test Requirements**:
- Each function with valid config
- Each function with missing config (should use defaults)
- Each function with invalid types (string "invalid", negative numbers)
- Each function with empty strings (should default)
- Boundary values (0.0, 1.0, max float)
- Nested config object parsing (spread.absolute vs flat EXIT_SPREAD_ABSOLUTE)

**Example Tests Needed**:
```python
def test_exit_spread_config_uses_default_absolute():
    # When EXIT_SPREAD_ABSOLUTE not set, should use _DEFAULT_EXIT_SPREAD_ABSOLUTE
    
def test_exit_spread_config_from_nested_options():
    # When EXIT_ORDER_OPTIONS.spread.absolute is set
    
def test_exit_force_exit_config_with_invalid_limit_cap_type():
    # When limit_cap.type is invalid string, should ignore
    
def test_exit_price_ladder_config_parses_ms_to_seconds():
    # When step_wait_ms is set, should convert to seconds
```

---

## 5. Exit Flow Orchestration (Partial Testing)
**File**: `tomic/services/exit_flow.py`

### Functions Needing Tests
```python
def execute_exit_flow(intent, config) -> ExitFlowResult       # Line 50+
    # Missing tests for:
    # - Primary order success
    # - Primary fails → fallback triggered
    # - Fallback fails → force exit triggered
    # - All attempts fail (status=failed)
    # - Partial fills (some legs don't fill)
    # - Quote age violations (quote_age_sec > threshold)
    # - Repricer wait timing
    # - Price ladder step logic
```

**Why Critical**: Exit flow is the safety mechanism. Failures here = unable to exit positions.

**Test Requirements**:
- Three-stage exit (primary → fallback → force)
- Each stage with success and failure scenarios
- Quote age filtering logic
- Repricer wait logic (when to reprice)
- Price ladder incrementing
- Order result aggregation
- Storage of exit results

---

## 6. Proposal Generation (Untested)
**File**: `tomic/services/proposal_generation.py`

### Functions Needing Tests
```python
def generate_proposal_overview(...) -> ProposalGenerationResult     # Line 45
def _load_positions(path: Path) -> Iterable[dict]                  # Line 27
def _load_metrics_for_symbols(symbols) -> Mapping[str, object]     # Line 41
```

**Why Critical**: Entry point for all trading proposal generation.

**Test Requirements**:
- Valid positions file loads
- Missing positions file raises ProposalGenerationError
- Metrics file loading (with/without file present)
- Metric fallback to vol_json
- Warning accumulation (warnings list)
- Integration with generate_proposals

---

## 7. Historical Volatility Calculations (Untested)
**File**: `tomic/services/marketdata/volatility_service.py`

### Functions Needing Tests
```python
class HistoricalVolatilityCalculatorService:
    def load_price_data(symbol: str) -> list[tuple[str, float]]     # Line 33
    def compute_new_records(symbol, price_records, existing_dates, end_date) # Line 49
```

**Why Critical**: HV data feeds into IV metrics used in strategy scoring.

**Test Requirements**:
- Price data loading (sorting, date parsing)
- Computing new HV records (rolling windows)
- Date filtering (only new records)
- Window size handling (max_window)
- Missing data handling (gaps in price history)
- NaN/None filtering

---

## 8. Greeks Aggregation Edge Cases (Partially Tested)
**File**: `tomic/analysis/greeks.py`

### Functions with Missing Edge Cases
```python
def compute_portfolio_greeks(positions) -> Dict[str, float]       # Line 6
def compute_greeks_by_symbol(positions) -> Dict[str, Dict]        # Line 24
```

### Missing Test Cases
- Positions with None greek values (should skip)
- Positions with position=0 (shouldn't contribute)
- Positions with different field names (qty vs position, Delta vs delta)
- Very large multipliers (>10000)
- Negative deltas with positive positions
- Empty position list
- Missing multiplier field (assume 1)
- Position with only some greeks (delta but not gamma)

**Current Coverage**: Only 4 basic assertions in test_compute_portfolio_greeks_basic

---

## 9. Strategy Scoring Normalization (Partial Testing)
**File**: `tomic/analysis/scoring.py`

### Functions with Missing Tests
```python
def resolve_min_risk_reward(strategy_cfg, criteria) -> float        # Line 65
def _clamp(value: float, minimum=0.0, maximum=1.0) -> float        # Line 88
def _normalize_ratio(value, cap) -> float | None                   # Line 92
def _normalize_pos(value, floor, span) -> float | None             # Line 98
```

### Missing Test Cases
- RR resolution when strategy_cfg and criteria both set (which wins?)
- Clamping at boundaries (exactly 0.0, exactly 1.0, below 0, above 1)
- Normalization with cap=0 (should return None)
- Normalization with None values
- Score conflicts between schema versions
- Mid source normalization with missing sources

---

## 10. Utility Functions Not Tested
**File**: `tomic/services/_percent.py`

### Functions
```python
def normalize_percent(value: Any) -> float | None                   # Line 7
```

### Missing Tests
- Value > 1 divided by 100
- Value 0.5 (already 0-1) unchanged
- Value 150 converted to 1.5 (out of range) → None
- Value "invalid string" → None
- Value None → None
- Boundary: exactly 1.0
- Boundary: exactly 0.0
- Boundary: 0.01 (1%)
- Boundary: 99 (should become 0.99)

---

## Test Writing Priority

### Week 1 (Critical Path)
1. `_config.py` - 20 parametrized tests (simple)
2. `portfolio_service.py` - 10 unit tests (medium complexity)
3. `_percent.py` - 10 tests (simple)
4. Greeks edge cases - 15 tests (simple)

### Week 2
5. `order_submission.py` edge cases - 10 tests
6. `ib_connection.py` - 15 tests (complex, threading)
7. Exit flow - 20 tests (integration)

### Week 3
8. Proposal generation - 8 tests
9. HV calculations - 12 tests
10. Strategy scoring edge cases - 10 tests

---

## Testing Tools/Patterns to Use

### For Simple Functions
```python
@pytest.mark.parametrize("input,expected", [
    ("test_case_1", expected_output_1),
    ("test_case_2", expected_output_2),
])
def test_function(input, expected):
    assert function(input) == expected
```

### For Mocking IB Connection
```python
from unittest.mock import Mock, MagicMock, patch

@patch('tomic.api.ib_connection.EClient')
def test_get_contract_details(mock_client):
    client = IBClient()
    # Mock the request/response cycle
    client._contract_details_requests[1] = {
        'event': threading.Event(),
        'details': [mock_detail],
        'error': None
    }
```

### For Fixtures
```python
@pytest.fixture
def sample_position():
    return {
        'symbol': 'AAA',
        'delta': 0.5,
        'gamma': 0.01,
        'position': 1,
        'multiplier': 100
    }
```

