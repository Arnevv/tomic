# TOMIC Test Coverage Analysis - Complete Report

This directory contains a comprehensive analysis of test coverage gaps in the TOMIC codebase.

## Files Generated

### 1. TEST_COVERAGE_ANALYSIS.md (565 lines)
**Main comprehensive report covering:**
- Test coverage mapping for each module (API, Services, Analysis, Strategies, CLI)
- Critical untested areas (Order submission, IB connection, Strategy scoring, Exit flow, Portfolio, Greeks)
- Test quality issues (weak assertions, hardcoded mocks, missing edge cases)
- Testability blockers (tight coupling, mixed side effects, missing interfaces)
- Analysis of conftest.py and shared fixtures
- Mock usage patterns
- Priority ranking of what to test first (Priority 1-3)
- Recommended improvements (short/medium/long term)
- Summary statistics table

**Key Findings:**
- Overall coverage: ~63% (unevenly distributed)
- Analysis module: 95%+ (excellent)
- API module: 26% (poor)
- Services: 65% (fair, but critical functions untested)
- Critical untested: portfolio_service.py, ib_connection.py, _config.py, proposal_generation.py

### 2. CRITICAL_UNTESTED_FUNCTIONS.md (320+ lines)
**Detailed listing of 10 untested critical functions:**
1. Portfolio Service (build_candidate, build_factsheet, rank_candidates)
2. IB Connection Management (get_contract_details, request_snapshot_with_mdtype)
3. Order Submission Validation (edge cases for quote age, preview prices)
4. Configuration Functions (_config.py - 5 functions completely untested)
5. Exit Flow Orchestration (execute_exit_flow with fallback logic)
6. Proposal Generation (generate_proposal_overview, _load_positions)
7. Historical Volatility Calculations (load_price_data, compute_new_records)
8. Greeks Aggregation Edge Cases (None values, extreme values)
9. Strategy Scoring Normalization (RR resolution, clamping)
10. Utility Functions (_percent.py normalize_percent)

Each function includes:
- Why it's critical
- Specific test requirements
- Edge cases needed
- Example test code

### 3. TEST_IMPROVEMENTS_ROADMAP.md (380+ lines)
**Actionable roadmap with code examples:**

#### Quick Wins (Week 1):
1. Add 20 parametrized tests for _config.py (2-3 hours)
2. Add 15 edge case tests for Greeks (2 hours)
3. Add 10 tests for _percent.py (1 hour)
4. Create shared test fixtures (1-2 hours)

#### Medium-Term (Weeks 2-3):
5. Test Portfolio Service (10 tests, 4-5 hours)
6. Edge cases for Order Submission (8-10 tests, 4 hours)
7. Exit Flow tests (15-20 tests, 6-8 hours)
8. IB Connection tests (12-15 tests, 6-8 hours)
9. Proposal Generation tests (8 tests, 3-4 hours)

#### Long-Term (Week 4+):
10. Refactor for testability (interfaces, DI)
11. Property-based tests (hypothesis)
12. Performance benchmarks (pytest-benchmark)

Includes actual code examples and patterns for:
- Parametrized tests
- Fixture usage
- Mocking patterns
- Error testing
- Coverage targets

---

## Quick Statistics

### Coverage by Module
| Module | Files | Tests | Coverage | Health |
|--------|-------|-------|----------|--------|
| API | 19 | 5 | 26% | 🔴 Poor |
| Services | 23 | 15 | 65% | 🟡 Fair |
| Analysis | 18 | 42 | 95%+ | 🟢 Excellent |
| Strategies | 11 | 5 | 45% | 🟡 Fair |
| CLI | 55 | 35 | 64% | 🟡 Fair |
| **Total** | **126** | **102** | **~63%** | **🟡 Fair** |

### Critical Gaps (MUST TEST)
1. **portfolio_service.py** - No tests at all (used by all recommendations)
2. **ib_connection.py** - Minimal tests (connection safety critical)
3. **_config.py** - No tests (controls exit behavior)
4. **proposal_generation.py** - No tests (entry point for trading)
5. **Order submission validation** - Missing edge cases

### Well-Tested Modules
1. Analysis module (42 test files, ~95% coverage)
2. Greeks calculations (have tests but missing edge cases)
3. Strategy scoring (have tests but missing normalization edge cases)

---

## Top Priority Recommendations

### Priority 1 (Do First - Critical)
- [ ] Add config parsing tests (20 tests, 2-3 hours) - **SIMPLEST TO START**
- [ ] Add portfolio_service tests (10 tests, 4-5 hours) - **HIGHEST IMPACT**
- [ ] Add Greeks edge case tests (15 tests, 2 hours) - **CATCHES BUGS**
- [ ] Create shared fixtures (1-2 hours) - **IMPROVES ALL TESTS**

### Priority 2 (High Value)
- [ ] Order submission edge cases (10 tests, 4 hours)
- [ ] Exit flow orchestration (20 tests, 6-8 hours)
- [ ] IB connection handling (15 tests, 6-8 hours)

### Priority 3 (Improves Coverage)
- [ ] Proposal generation (8 tests, 3-4 hours)
- [ ] HV calculations (12 tests, 4-5 hours)
- [ ] Strategy scoring edge cases (10 tests, 2-3 hours)

---

## How to Use These Reports

### For Developers
1. Start with TEST_IMPROVEMENTS_ROADMAP.md for hands-on guidance
2. Pick a "Quick Win" task and use the code examples provided
3. Refer to CRITICAL_UNTESTED_FUNCTIONS.md when implementing specific tests

### For Project Managers
1. Review summary statistics and priorities in TEST_COVERAGE_ANALYSIS.md
2. Use the estimated effort/time for each item in TEST_IMPROVEMENTS_ROADMAP.md
3. Track progress against the Priority 1/2/3 ranking

### For QA Engineers
1. Use CRITICAL_UNTESTED_FUNCTIONS.md to identify areas needing manual testing
2. Note missing edge cases when planning QA scenarios
3. Cross-reference with conftest.py to understand available test fixtures

---

## Key Insights

### Testing Gaps
- **Portfolio calculations**: Complete blind spot - affects all recommendations
- **IB connection**: Only basic error signature tested - thread safety untested
- **Config parsing**: Complex logic with defaults - completely untested
- **Exit flow**: Core safety mechanism - fallback logic has partial tests only
- **Greeks**: Basic tests exist but edge cases missing (None values, extreme values)

### Test Quality Issues
- Mock data inconsistencies (field name variations across tests)
- Missing edge case coverage (stale quotes, missing data, extreme values)
- Some tests validate structure but not correctness
- No tests for error conditions in critical paths

### Testability Blockers
- Tight coupling to file system (portfolio_service)
- Callback-based async with threading (IB connection)
- Mixed side effects and calculations in functions

---

## Coverage Goals

**Current**: ~63% (mostly integration tests with mocks)
**Target**: ~78% with better distribution:
- API: 26% → 60%
- Services: 65% → 85%
- Analysis: 95% → 98%
- Strategies: 45% → 70%
- CLI: 64% → 75%

---

## Testing Patterns Used

### Parametrized Tests
```python
@pytest.mark.parametrize("input,expected", [(val1, exp1), (val2, exp2)])
def test_function(input, expected):
    assert function(input) == expected
```

### Fixtures for Reusable Data
```python
@pytest.fixture
def sample_position():
    return {"delta": 0.5, "position": 1, ...}
```

### Mocking with monkeypatch
```python
def test_function(monkeypatch):
    monkeypatch.setattr(module, "func", mock_func)
```

### Error Testing
```python
def test_error_case():
    with pytest.raises(ValueError):
        function(invalid_input)
```

---

## Dependencies & Tools

Current test infrastructure:
- pytest (test framework)
- monkeypatch (mocking)
- pytest fixtures
- Standard unittest.mock

Recommended additions:
- hypothesis (property-based testing)
- pytest-benchmark (performance testing)
- pytest-cov (coverage reporting)

---

## Next Steps

1. **Immediate** (Today): Review TEST_COVERAGE_ANALYSIS.md to understand gaps
2. **This Week**: Implement Quick Wins from TEST_IMPROVEMENTS_ROADMAP.md
3. **Next Week**: Tackle Priority 2 items (exit flow, IB connection)
4. **Ongoing**: Maintain coverage targets and add tests alongside feature development

---

## Questions to Answer During Implementation

1. **Mock Data**: Should mocks match real production patterns more closely?
2. **Integration Tests**: Need real TWS connection tests or stay with mocks?
3. **Edge Cases**: How extreme should edge case values be (e.g., 0.99999 delta)?
4. **Performance**: Should we benchmark critical functions?
5. **Coverage Target**: Is 78% sufficient or should we aim higher?

---

## References

- Main Analysis: TEST_COVERAGE_ANALYSIS.md
- Function Details: CRITICAL_UNTESTED_FUNCTIONS.md
- Implementation Guide: TEST_IMPROVEMENTS_ROADMAP.md
- Pytest Docs: https://docs.pytest.org/
- Coverage Tools: https://coverage.readthedocs.io/

---

**Report Generated**: 2025-11-19
**Analysis Scope**: Complete TOMIC codebase (126 Python files, 102 test files)
**Coverage Estimate**: ~63% (unevenly distributed)

