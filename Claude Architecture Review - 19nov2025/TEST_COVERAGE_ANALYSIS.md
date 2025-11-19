# TOMIC Test Coverage Analysis Report

## Executive Summary

The TOMIC codebase has **uneven test coverage** with critical gaps in:
- Core business logic for portfolio calculations and Greeks aggregation
- Order submission and execution workflows
- TWS/IB connection handling
- Exit flow logic
- Service layer configuration

**Coverage Estimate**: ~50-60% of critical business logic has tests, but many are integration tests requiring mocks.

---

## 1. TEST COVERAGE MAPPING

### A. API Module (tomic/api)
**Total Files**: 19  
**Test Files**: 5  
**Coverage**: ~26%

#### Tested:
- test_base_client.py (minimal - 22 lines)
- test_fetch_single_option_documentation.py
- test_getonemarket_async_module.py
- test_historical_iv.py
- test_option_metrics.py

#### Untested/Poorly Tested:
- `ib_connection.py` - **CRITICAL** IBClient connection management (get_contract_details, request_snapshot_with_mdtype)
- `market_client.py` - Market data collection orchestration
- `client_registry.py` - Client ID management
- `getallmarkets_async.py` - Async market data fetching
- `earnings_importer.py` - Earnings data import
- `margin_calc.py` - Margin calculations
- `open_interest.py` - Open interest data
- `market_export.py` - Market data export utilities

**Issue**: base_client.py test only validates error signature, doesn't test actual error handling behavior

---

### B. Services Module (tomic/services)
**Total Files**: 23  
**Test Files**: 15  
**Coverage**: ~65% (but many are integration-style tests)

#### Tested:
- test_chain_processing.py
- test_chain_sources.py
- test_config_options.py
- test_exit_fallback.py
- test_exit_flow.py
- test_exit_orders.py
- test_ib_marketdata.py
- test_market_scan_service.py
- test_market_snapshot.py
- test_order_submission.py
- test_pipeline_refresh.py
- test_pipeline_runner.py
- test_proposal_details.py
- test_strategy_pipeline.py
- test_trade_management_service.py

#### Untested/Critical Gaps:
- **`portfolio_service.py`** - CRITICAL - Portfolio calculations, candidate ranking, factsheet generation
  - Functions: `PortfolioService` class methods, `Candidate` class, `Factsheet` class
  - No unit tests at all
  
- **`proposal_generation.py`** - CRITICAL - Proposal generation workflow orchestration
  - Functions: `generate_proposal_overview()`, `_load_positions()`, `_load_metrics_for_symbols()`
  - Used by CLI but never tested in isolation

- **`marketdata/volatility_service.py`** - CRITICAL
  - Functions: `HistoricalVolatilityCalculatorService` (compute_new_records, load_price_data)
  - No tests for historical volatility calculations

- **`marketdata/storage_service.py`** - Storage backend for volatility data
  - No tests

- **`_config.py`** - Configuration helpers
  - Functions: `exit_spread_config()`, `exit_repricer_config()`, `exit_fallback_config()`, `exit_force_exit_config()`, `exit_price_ladder_config()`
  - Complex config parsing with defaults - untested

- **`_percent.py`** - Simple percentage normalization (untested)
- **`_id_sequence.py`** - Thread-safe ID generation (untested)
- **`utils.py`** - Service utilities (untested)

---

### C. Analysis Module (tomic/analysis)
**Total Files**: 18  
**Test Files**: 42 (many detailed tests)  
**Coverage**: ~95%+ (Most comprehensive)

#### Well-Tested:
- test_greeks.py - Portfolio greeks aggregation
- test_metrics.py, test_metrics_calc.py - Metrics calculations
- test_strategy_scoring.py - Strategy scoring logic
- test_proposal_engine.py - Proposal generation
- test_scoring_helpers.py - Scoring utilities
- test_strategy_rules_loader.py - Configuration loading
- test_rule_engine.py - Rules validation
- test_calendar_metrics.py - Calendar spread metrics
- test_ratio_spread_metrics.py - Ratio metrics
- test_iv_history.py - IV history fetching
- test_liquidity_filter.py - Liquidity filtering

#### Minimal Tests:
- Greeks test is basic (test_compute_portfolio_greeks_basic with 4 assertions)
- Missing edge cases for Greeks with None values
- Missing tests for Greeks with extreme values

---

### D. Strategies Module (tomic/strategies)
**Total Files**: 11  
**Test Files**: 5  
**Coverage**: ~45%

#### Tested:
- test_generators_snapshot.py - Tests all strategy generators (iron_condor, short_put_spread, etc.)
- test_prepare_option_chain.py - Option chain preparation
- test_ratio_like.py - Ratio spreads
- test_reason_engine.py - Rejection reasons
- test_strike_selection.py - Strike selection logic

#### Untested (Individual Strategy Implementations):
- `atm_iron_butterfly.py` - No dedicated unit tests
- `backspread_put.py` - No dedicated unit tests
- `calendar.py` - No dedicated unit tests
- `naked_put.py` - No dedicated unit tests
- Individual strategies rely on snapshot test

**Issue**: Generators snapshot test validates structure but not correctness of calculations

---

### E. CLI Module (tomic/cli)
**Total Files**: 55  
**Test Files**: 35  
**Coverage**: ~64%

#### Well-Tested:
- test_cli_app.py - CLI dispatch routing
- test_exit_flow.py - Exit flow orchestration
- test_controlpanel_proposals.py - Control panel UI
- test_bs_calculator.py - Black-Scholes calculations
- test_fetch_prices.py - Price fetching
- test_portfolio_menu_flow.py - Portfolio menu
- test_volatility_recommender.py - Volatility recommendations
- test_earnings_info.py - Earnings information

#### Untested or Minimal:
- `controlpanel/portfolio.py` - Portfolio UI logic
- `option_lookup.py` - Option symbol lookup
- `option_lookup_bulk.py` - Bulk option lookup
- `link_positions.py` - Position linking
- `close_trade.py` - Trade closing logic
- `event_watcher.py` - Event monitoring
- `portfolio_greeks.py` - Portfolio Greeks display
- `strategy_dashboard.py` - Strategy dashboard UI
- `trading_plan.py` - Trading plan generation
- CLI services modules have scattered tests

---

## 2. CRITICAL UNTESTED AREAS

### A. Order Submission & Execution
**Files**: `services/order_submission.py`, `services/exit_orders.py`, `services/exit_fallback.py`

**Functions Missing Tests**:
1. `OrderSubmissionService` class - Order creation and submission
2. `build_exit_order_plan()` - Exit order planning logic
3. `detect_fallback_reason()` - Fallback mechanism detection
4. `build_vertical_execution_candidates()` - Vertical spread execution
5. Edge cases:
   - Missing quotes (quote_age_sec > threshold)
   - Preview prices (mid_source = "model")
   - Combo order transmission
   - Quote rejection due to age

**Risk**: **HIGH** - Core trading flow, missing edge case coverage

---

### B. TWS/IB Connection Handling
**Files**: `api/ib_connection.py`, `api/base_client.py`

**Functions Missing Tests**:
1. `IBClient.get_contract_details()` - Contract detail requests with timeouts
2. `IBClient.request_snapshot_with_mdtype()` - Market data snapshot requests
3. `IBClient.cancelContractDetails()` - Request cancellation
4. `IBClient.contractDetails()` - Contract detail callbacks
5. `BaseIBApp.error()` - Error handling (only tests signature)
6. Thread safety of request/response handling
7. Timeout scenarios
8. Network failures

**Test Quality Issues**:
- base_client test doesn't validate actual error logging
- No tests for threading edge cases
- No tests for timeout behavior
- No tests for concurrent requests

**Risk**: **CRITICAL** - Connection failures could cause silent data loss

---

### C. Strategy Scoring & Selection
**Files**: `analysis/scoring.py`, `services/proposal_details.py`

**Gaps**:
1. `resolve_min_risk_reward()` - Min RR threshold selection (uses criteria config)
2. `_normalize_pos()`, `_normalize_ratio()` - Normalization edge cases
3. Missing tests for:
   - Strategies with None scores
   - RR threshold conflicts between strategy config and criteria
   - Score clamping at 0 and 1
   - Proposal rejection reasons (ReasonEngine integration)

**Risk**: **MEDIUM** - Scoring drives proposal selection, incorrect logic affects trading decisions

---

### D. Exit Flow Logic
**Files**: `services/exit_flow.py`, `cli/exit_flow.py`

**Gaps**:
1. `execute_exit_flow()` - Main exit orchestration
2. Exit attempt result aggregation
3. Fallback logic (primary → secondary → force exit)
4. Price ladder incremental adjustments
5. Repricer wait logic
6. Integration of exit_orders + exit_fallback
7. Missing edge cases:
   - All legs cannot be exited
   - Quote age threshold violations
   - Partial position fills
   - Cancellation during repricing

**Risk**: **HIGH** - Exit flow is critical for risk management

---

### E. Portfolio Calculations
**Files**: `services/portfolio_service.py`, `services/marketdata/volatility_service.py`

**Untested Functions**:
1. `PortfolioService.build_candidate()` - Candidate creation from proposal
2. `PortfolioService.build_factsheet()` - Factsheet generation
3. `compute_margin_and_rr()` - Margin and risk/reward calculations
4. `HistoricalVolatilityCalculatorService.compute_new_records()` - HV backfill
5. Greeks aggregation for portfolio (basic tests exist but edge cases missing)

**Edge Cases**:
- Missing data (None values)
- Extreme values (very high/low IV, delta, gamma)
- Portfolio with no positions
- Margin requirement changes

**Risk**: **HIGH** - Portfolio metrics drive trading decisions

---

### F. Greeks Calculations
**Files**: `analysis/greeks.py`, `analytics/test_greek_aggregation.py`

**Current Tests**:
- Basic portfolio greeks (test_compute_portfolio_greeks_basic)
- Greeks by symbol (test_compute_greeks_by_symbol)

**Missing Tests**:
1. Edge cases:
   - `None` values in greeks (partially tested)
   - Negative greeks (basic tests exist)
   - Very large multipliers
   - Position = 0
   - Missing delta/gamma/vega/theta
2. Aggregation consistency across schemas
3. Greeks with different action types (BUY vs SELL)
4. Greeks with qty vs position field differences
5. Portfolio-level vs leg-level Greeks consistency

**Risk**: **MEDIUM** - Greeks used for risk monitoring, incorrect aggregation could mask exposure

---

## 3. TEST QUALITY ISSUES

### A. Tests Without Meaningful Assertions
1. **test_base_client.py** (22 lines)
   - Only validates that error() method exists
   - Doesn't verify logging behavior
   - Doesn't test WARNING_ERROR_CODES or IGNORED_ERROR_CODES logic

### B. Hardcoded Mock Data Not Matching Production
1. **test_order_submission.py**
   - Mock legs use hardcoded bid/ask values
   - No tests with real quote patterns (missing edges, stale quotes)
   
2. **test_proposal_details.py**
   - Sample legs have idealized Greeks values
   - Missing tests for:
     - Mismatched field names (delta vs Delta)
     - Missing greek fields
     - Numeric precision issues

3. **test_exit_flow.py**
   - Mock positions always have valid quotes
   - No tests for quote_age_sec > threshold scenarios

### C. Integration Tests Requiring Real IB Connection
None found currently, but **risk**: IB connection tests use mocks with `monkeypatch.setattr(connect_ib, ...)`:
- `test_getonemarket_async_module.py`
- `test_historical_iv.py`
- `test_option_metrics.py`
- `test_fetch_prices.py`
- `test_volatility_fetcher.py`

If these mocks are incomplete, real IB tests would fail silently.

### D. Missing Edge Case Tests
1. **Order submission**:
   - Preview prices blocked correctly? (test exists)
   - Combo max quote age enforcement? (no test)
   - Missing bid/ask handling? (no test)

2. **Exit flow**:
   - Partial fills? (no test)
   - Quote rejection? (no test)
   - Timeout handling? (no test)

3. **Greeks**:
   - Null greeks fields? (partially tested)
   - Extreme values (0.99 delta, 100+ gamma)? (no test)

4. **Portfolio calculations**:
   - Empty portfolio? (no test)
   - Single position? (no test)
   - Synthetic positions with ratio legs? (no test)

---

## 4. TESTABILITY BLOCKERS

### A. Tight Coupling Issues
1. **Portfolio Service coupled to file system**
   - `portfolio_service.py` depends on file loading in proposal_generation
   - Hard to test without temp files

2. **IB Connection tightly coupled to callbacks**
   - `ib_connection.py` uses threading with callbacks
   - Hard to test synchronously without ThreadEvent mocks

3. **Exit flow coupled to order submission**
   - `exit_flow.py` calls order_submission functions
   - Hard to test without mocking the entire order submission chain

### B. Functions Mixing Side Effects with Calculations
1. **`order_submission.prepare_order_instructions()`**
   - Creates Order/Contract objects (side effect)
   - Validates credit requirement (calculation)
   - Hard to test the validation without the side effect

2. **`proposal_generation.generate_proposal_overview()`**
   - Loads files (side effect)
   - Calls generate_proposals (calculation)
   - Hard to test proposal logic without file I/O

3. **`exit_flow.execute_exit_flow()`**
   - Makes API calls (side effect)
   - Orchestrates retry logic (calculation)
   - Hard to test retry without actual API calls

### C. Missing Interfaces/Protocols for Mocking
1. **Market data service**
   - No interface for IBMarketDataService
   - Hard to inject mock market data

2. **Portfolio service**
   - No interface for external dependencies
   - Hard to test without actual file system

3. **Order submission**
   - No interface for IB connection
   - Monkeypatching required in tests

---

## 5. CONFTEST.PY ANALYSIS

**Location**: `/home/user/tomic/tests/conftest.py`

**Shared Fixtures**:
1. **stub_external_modules()** (autouse=True)
   - Stubs: ibapi, pandas, numpy, aiohttp, requests
   - Provides minimal module interface without implementation
   - Prevents ImportError for optional dependencies

**Issues**:
- No shared fixtures for common test objects (proposals, positions, legs)
- No shared mock for IB connection
- No shared fixtures for configuration
- Mock data inconsistencies across test files (different field names, different precision)

**Recommendations**:
- Create `@pytest.fixture` for:
  - Sample option legs (with configurable values)
  - Sample proposals (iron_condor, short_put_spread, etc.)
  - Sample positions (with varied greeks/margining)
  - Mock IB connection
  - Temporary config overrides

---

## 6. MOCK USAGE PATTERNS

### Pattern 1: monkeypatch.setattr (Most Common)
```python
monkeypatch.setattr(order_submission, "connect_ib", lambda **kwargs: FakeApp())
```
✅ **Good**: Clear intent, easy to trace
❌ **Issue**: Each test defines its own fake, inconsistency

### Pattern 2: Fixture-based stubs
```python
@pytest.fixture
def sample_intent() -> StrategyExitIntent:
```
✅ **Good**: Reusable, consistent
❌ **Issue**: Not all critical fixtures defined

### Pattern 3: Module stubs in conftest
```python
sys.modules["ibapi"] = ibapi_pkg
```
✅ **Good**: Works around dependency issues
❌ **Issue**: Stubs are too minimal, don't expose all needed attributes

---

## 7. TEST DATA FIXTURES

### Location Analysis
- Main fixtures: `/home/user/tomic/tests/conftest.py`
- Additional fixtures in individual test files:
  - `test_order_submission.py` - Order/proposal fixtures
  - `test_exit_flow.py` - Exit intent fixtures
  - `test_proposal_details.py` - Proposal fixtures
  - `test_market_snapshot.py` - Metrics fixtures

### Issues with Shared Fixtures
1. **Inconsistent field names**:
   - Some tests use `mid`, others use `model_price`
   - Some use `position`, others use `qty` or `quantity`
   - Some use `type`, others use `right` (C/P)

2. **Missing productions scenarios**:
   - No fixture with expired options
   - No fixture with stale quotes (quote_age_sec > threshold)
   - No fixture with missing bid/ask
   - No fixture with zero liquidity (volume=0)

3. **Multiplier inconsistencies**:
   - Options usually 100x multiplier
   - Fixtures sometimes omit multiplier
   - Some tests assume 100, others don't

---

## PRIORITY RANKING: What to Test First

### Priority 1 - CRITICAL (Blocks production correctness)
1. **Portfolio service** (`portfolio_service.py`)
   - Functions: `build_candidate()`, `build_factsheet()`, `rank_candidates()`
   - Impact: All recommendations use this
   - Effort: Medium (5-10 unit tests)

2. **IB Connection error handling** (`api/ib_connection.py`)
   - Functions: Error callbacks, timeout handling, thread safety
   - Impact: Connection failures could cause data loss
   - Effort: Medium (10-15 integration tests needed)

3. **Order submission validation** (`services/order_submission.py`)
   - Functions: Preview price blocking, quote age validation
   - Impact: Could submit invalid orders
   - Effort: Medium (8-12 unit tests)

4. **Config parsing** (`services/_config.py`)
   - Functions: All exit config functions
   - Impact: Misconfiguration could break exit flow
   - Effort: Low (15-20 simple parametrized tests)

### Priority 2 - HIGH (Affects trading accuracy)
5. **Exit flow orchestration** (`services/exit_flow.py`)
   - Functions: `execute_exit_flow()`, retry logic, fallback
   - Impact: Exit flow is critical for risk management
   - Effort: High (20+ integration tests)

6. **Strategy scoring edge cases** (`analysis/scoring.py`)
   - Functions: Score normalization, RR threshold resolution
   - Impact: Wrong scores → wrong recommendations
   - Effort: Low-Medium (10-15 parametrized tests)

7. **Greeks aggregation edge cases** (`analysis/greeks.py`)
   - Functions: Null handling, multiplier consistency
   - Impact: Wrong Greeks → wrong risk assessment
   - Effort: Low (10-12 parametrized tests)

### Priority 3 - MEDIUM (Improves coverage)
8. **Proposal generation** (`services/proposal_generation.py`)
   - Functions: End-to-end proposal generation
   - Impact: Used by CLI but untested
   - Effort: Medium (8-10 integration tests)

9. **Historical volatility calculations** (`services/marketdata/volatility_service.py`)
   - Functions: HV backfill, rolling window calculations
   - Impact: Affects IV metrics used in scoring
   - Effort: Medium (10-15 tests)

10. **Individual strategy generators** (`strategies/*.py`)
    - Current: Only snapshot test validates structure
    - Missing: Unit tests for each strategy's generate() function
    - Effort: Low (3-5 tests per strategy)

---

## RECOMMENDED IMPROVEMENTS

### Short Term (Week 1)
1. Add 20 parametrized tests for `_config.py` config functions
2. Add 10 unit tests for `portfolio_service.py` core functions
3. Add fixture for standard test data (shared across tests)
4. Add 10 edge case tests for Greeks (None values, extreme values)

### Medium Term (Week 2-3)
5. Refactor `order_submission.py` to separate validation from side effects
6. Add 15 tests for exit flow (primary → fallback → force exit)
7. Add 10 tests for IB connection error handling
8. Add tests for each strategy generator function

### Long Term (Week 4+)
9. Create interfaces for injectable dependencies (market data, IB connection)
10. Add integration tests with real market data (fixtures)
11. Add performance benchmarks for critical functions (Greeks, scoring)
12. Add property-based tests for numerical calculations (hypothesis)

---

## SUMMARY STATISTICS

| Module | Total Files | Test Files | Estimated Coverage | Health |
|--------|------------|-----------|-------------------|--------|
| API | 19 | 5 | 26% | 🔴 Poor |
| Services | 23 | 15 | 65% | 🟡 Fair |
| Analysis | 18 | 42 | 95%+ | 🟢 Excellent |
| Strategies | 11 | 5 | 45% | 🟡 Fair |
| CLI | 55 | 35 | 64% | 🟡 Fair |
| **Total** | **126** | **102** | **~63%** | **🟡 Fair** |

**Key Finding**: Analysis module is well-tested, but critical business logic in portfolio_service, order_submission, and IB connection handling is poorly tested.

