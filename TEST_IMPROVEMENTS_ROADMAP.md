# Test Coverage Improvement Roadmap

## Summary Statistics
- **Total Python Files**: 126 (tomic + tests)
- **Test Files**: 102
- **Estimated Coverage**: ~63% (uneven across modules)
- **Critical Gaps**: Portfolio service, IB connection, order submission validation

---

## Quick Wins (Can Implement This Week)

### 1. Add Tests for `_config.py` (20 tests, 2-3 hours)
**File**: `tomic/services/_config.py`
**Why**: Controls exit order behavior, completely untested

```python
# tests/services/test_config.py
@pytest.mark.parametrize("value,expected", [
    (None, 0.50),
    ("", 0.50),
    ("0.75", 0.75),
    ("invalid", 0.50),
])
def test_exit_spread_config_absolute_with_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("EXIT_SPREAD_ABSOLUTE", raising=False)
    else:
        monkeypatch.setenv("EXIT_SPREAD_ABSOLUTE", str(value))
    result = exit_spread_config()
    assert result["absolute"] == expected
```

### 2. Add Edge Case Tests for Greeks (15 tests, 2 hours)
**File**: `tomic/analysis/greeks.py`
**Why**: Missing edge cases could cause silent bugs

```python
# tests/analysis/test_greeks_edge_cases.py
def test_compute_portfolio_greeks_with_none_values():
    positions = [
        {"delta": None, "gamma": 0.1, "position": 1, "multiplier": 100},
        {"delta": 0.5, "gamma": None, "position": 1, "multiplier": 100},
    ]
    result = compute_portfolio_greeks(positions)
    assert result["Delta"] == 50.0
    assert result["Gamma"] == 10.0  # Only processes non-None
    
def test_compute_portfolio_greeks_with_zero_position():
    positions = [
        {"delta": 0.5, "gamma": 0.1, "position": 0, "multiplier": 100},
    ]
    result = compute_portfolio_greeks(positions)
    assert result["Delta"] == 0.0
    assert result["Gamma"] == 0.0
```

### 3. Add Tests for `_percent.py` (10 tests, 1 hour)
**File**: `tomic/services/_percent.py`
**Why**: Simple but untested, easy to add

```python
# tests/services/test_percent.py
@pytest.mark.parametrize("value,expected", [
    (0.5, 0.5),      # Already normalized
    (50, 0.5),       # 50% -> 0.5
    (150, None),     # Out of range
    (1, 1.0),        # Boundary
    (0, 0.0),        # Boundary
    (None, None),    # Invalid
    ("invalid", None),  # Invalid
])
def test_normalize_percent(value, expected):
    assert normalize_percent(value) == expected
```

### 4. Create Shared Test Fixtures (1-2 hours)
**File**: `tests/conftest.py`
**Why**: Reduce duplication, improve consistency

```python
# Add to conftest.py
@pytest.fixture
def sample_short_put_spread_leg():
    return {
        "symbol": "AAA",
        "expiry": "20250117",
        "strike": 100.0,
        "right": "P",
        "type": "put",
        "position": -1,
        "bid": 2.0,
        "ask": 2.2,
        "mid": 2.1,
        "delta": -0.4,
        "gamma": 0.02,
        "vega": 0.15,
        "theta": -0.05,
        "iv": 0.25,
        "multiplier": 100,
        "quote_age_sec": 0.5,
        "mid_source": "true",
    }

@pytest.fixture
def sample_position_with_greeks():
    return {
        "symbol": "AAA",
        "delta": 0.5,
        "gamma": 0.1,
        "vega": 0.2,
        "theta": -0.05,
        "position": 1,
        "multiplier": 100,
    }
```

---

## Medium-Term Improvements (Weeks 2-3)

### 5. Test Portfolio Service (10 tests, 4-5 hours)
**File**: `tests/services/test_portfolio_service.py` (NEW)

```python
def test_build_candidate_from_proposal():
    proposal = StrategyProposal(...)
    candidate = PortfolioService().build_candidate(proposal, symbol="AAA", ...)
    assert isinstance(candidate, Candidate)
    assert candidate.symbol == "AAA"
    assert candidate.score is not None

def test_build_factsheet_with_earnings():
    # Test factsheet with earnings date
    ...

def test_build_factsheet_without_metrics():
    # Test graceful handling when IV data missing
    ...

def test_rank_candidates_sorts_by_score():
    candidates = [
        Candidate(..., score=0.5),
        Candidate(..., score=0.7),
        Candidate(..., score=0.6),
    ]
    ranked = PortfolioService().rank_candidates(candidates)
    assert ranked[0].score == 0.7
    assert ranked[1].score == 0.6
    assert ranked[2].score == 0.5
```

### 6. Add Edge Cases to Order Submission (8-10 tests, 4 hours)
**File**: `tests/services/test_order_submission.py`
**Add to existing file**

```python
def test_prepare_order_blocks_stale_quotes(monkeypatch):
    # quote_age_sec > 5.0 should block
    proposal = StrategyProposal(
        strategy="short_put_spread",
        legs=[
            {..., "quote_age_sec": 5.1},  # Stale!
        ],
    )
    with pytest.raises(OrderSubmissionError):
        prepare_order_instructions(proposal, ...)

def test_prepare_order_requires_positive_credit():
    # For strategies in POSITIVE_CREDIT_STRATS
    proposal = StrategyProposal(
        strategy="naked_put",
        legs=[...],
    )
    proposal.credit = -10.0  # Invalid!
    with pytest.raises(OrderSubmissionError):
        prepare_order_instructions(proposal, ...)
```

### 7. Add Exit Flow Tests (15-20 tests, 6-8 hours)
**File**: `tests/services/test_exit_flow_detailed.py` (NEW)

```python
def test_execute_exit_flow_primary_success(monkeypatch):
    intent = StrategyExitIntent(...)
    config = ExitFlowConfig(...)
    
    # Mock successful primary exit
    def mock_build_plan(intent_arg, config_arg):
        return ExitOrderPlan(orders=[...], reason="primary")
    monkeypatch.setattr(exit_orders, "build_exit_order_plan", mock_build_plan)
    
    result = execute_exit_flow(intent, config)
    assert result.status == "success"
    assert result.attempts[0].stage == "primary"

def test_execute_exit_flow_primary_fails_fallback_succeeds(monkeypatch):
    # Test fallback logic when primary fails
    ...

def test_execute_exit_flow_respects_quote_age_threshold(monkeypatch):
    # Test that stale quotes are rejected
    intent = StrategyExitIntent(
        legs=[{..., "quote_age_sec": 10.0}]  # > 5.0 threshold
    )
    result = execute_exit_flow(intent, config)
    assert "quote_age" in result.reason or result.status != "success"
```

### 8. Add IB Connection Tests (12-15 tests, 6-8 hours)
**File**: `tests/api/test_ib_connection_detailed.py` (NEW)

```python
def test_get_contract_details_timeout():
    client = IBClient()
    client.nextValidId(1)
    
    # Simulate timeout (event.wait returns False)
    client.get_contract_details(Mock(), timeout_ms=100)
    # After timeout, should raise TimeoutError
    
    with pytest.raises(TimeoutError):
        client.get_contract_details(Mock(), timeout_ms=50)

def test_contractDetails_thread_safety():
    client = IBClient()
    client.nextValidId(1)
    
    # Simulate concurrent requests
    import threading
    results = []
    
    def add_contract_detail(req_id):
        client.contractDetails(req_id, Mock())
        
    threads = [
        threading.Thread(target=add_contract_detail, args=(i,))
        for i in range(1, 11)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # All requests should complete without error
```

### 9. Add Proposal Generation Tests (8 tests, 3-4 hours)
**File**: `tests/services/test_proposal_generation.py` (NEW)

```python
def test_generate_proposal_overview_loads_positions(tmp_path):
    positions_file = tmp_path / "positions.json"
    positions_file.write_text(json.dumps([
        {"symbol": "AAA", "position": 1},
        {"symbol": "BBB", "position": -1},
    ]))
    
    result = generate_proposal_overview(positions_path=positions_file)
    assert result.proposals is not None
    assert len(result.warnings) >= 0

def test_generate_proposal_overview_missing_positions_file():
    with pytest.raises(ProposalGenerationError):
        generate_proposal_overview(positions_path="/nonexistent/path.json")

def test_generate_proposal_overview_with_metrics():
    # Test with explicit metrics file
    ...
```

---

## Long-Term Improvements (Weeks 4+)

### 10. Refactor for Testability
**Goal**: Reduce coupling, enable better testing

**Changes Needed**:
1. Create interface for `MarketDataService`
   ```python
   # tomic/core/market_data_protocol.py
   from typing import Protocol
   
   class MarketDataProvider(Protocol):
       def get_snapshot(self, symbol: str) -> dict: ...
       def get_quotes(self, legs: list) -> list: ...
   ```

2. Create interface for `IBConnection`
   ```python
   # tomic/api/ib_protocol.py
   class IBClient(Protocol):
       def get_contract_details(self, contract) -> Any: ...
       def request_snapshot(self, contract) -> dict: ...
   ```

3. Dependency injection in portfolio service
   ```python
   class PortfolioService:
       def __init__(self, market_data: MarketDataProvider, ...):
           self.market_data = market_data
   ```

### 11. Add Property-Based Tests
**Tool**: hypothesis library

```python
# tests/analysis/test_greeks_hypothesis.py
from hypothesis import given, strategies as st

@given(
    delta=st.floats(min_value=-1.0, max_value=1.0),
    gamma=st.floats(min_value=0.0, max_value=1.0),
    position=st.integers(min_value=-100, max_value=100),
    multiplier=st.integers(min_value=1, max_value=10000),
)
def test_greeks_aggregation_commutative(delta, gamma, position, multiplier):
    pos1 = {"delta": delta, "gamma": gamma, "position": position, "multiplier": multiplier}
    pos2 = {"delta": delta, "gamma": gamma, "position": position, "multiplier": multiplier}
    
    result1 = compute_portfolio_greeks([pos1, pos2])
    result2 = compute_portfolio_greeks([pos2, pos1])
    
    assert result1 == result2  # Order should not matter
```

### 12. Add Performance Benchmarks
**Tool**: pytest-benchmark

```python
# tests/bench/bench_greeks.py
def test_greek_aggregation_performance(benchmark):
    positions = [
        {"delta": 0.5, "gamma": 0.1, "position": 1, "multiplier": 100}
        for _ in range(1000)
    ]
    benchmark(compute_portfolio_greeks, positions)
```

---

## Testing Patterns to Adopt

### 1. Use Parametrize for Variations
Instead of:
```python
def test_function_case1():
    ...
def test_function_case2():
    ...
def test_function_case3():
    ...
```

Use:
```python
@pytest.mark.parametrize("input,expected", [
    (case1, expected1),
    (case2, expected2),
    (case3, expected3),
])
def test_function(input, expected):
    assert function(input) == expected
```

### 2. Use Fixtures for Reusable Data
```python
@pytest.fixture
def sample_position():
    return {...}

def test_function(sample_position):
    # Use sample_position
    ...
```

### 3. Use pytest.raises for Error Cases
```python
def test_function_invalid_input():
    with pytest.raises(ValueError):
        function(invalid_input)
```

### 4. Use monkeypatch for Mocking
```python
def test_function(monkeypatch):
    monkeypatch.setattr(module, "function", mock_function)
    # Test with mocked function
```

---

## Coverage Target

| Module | Current | Target | Priority |
|--------|---------|--------|----------|
| API | 26% | 60% | High |
| Services | 65% | 85% | Medium |
| Analysis | 95% | 98% | Low |
| Strategies | 45% | 70% | Medium |
| CLI | 64% | 75% | Low |
| **Overall** | **63%** | **78%** | - |

---

## Validation Checklist

After adding tests, verify:
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Check coverage: `pytest tests/ --cov=tomic --cov-report=html`
- [ ] All new tests pass
- [ ] No regressions in existing tests
- [ ] Mock data matches production patterns
- [ ] Edge cases covered (None, 0, negative, extreme values)
- [ ] Error conditions tested
- [ ] Test names clearly describe what they test

---

## Resources

- Pytest docs: https://docs.pytest.org/
- Property-based testing: https://hypothesis.readthedocs.io/
- Pytest-benchmark: https://pytest-benchmark.readthedocs.io/
- Coverage tools: https://coverage.readthedocs.io/

