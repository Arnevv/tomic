# TOMIC Architecture Review Report

**Date:** 2025-11-19
**Reviewer:** Senior Python Architect
**Scope:** Full codebase review for architecture, code quality, and technical debt

---

## Executive Summary

TOMIC ("Tactical Option Modeling & Insight Console") is a well-structured Python trading analysis platform with **245 modules** across **52,693 lines of code** and **137 test files**. The codebase demonstrates good architectural intent with a 9-layer design and zero circular dependencies.

### Overall Assessment: **YELLOW (Good foundation, critical gaps need attention)**

**Strengths:**
- Clean 9-layer architecture with clear separation
- Zero circular dependencies
- Comprehensive test suite (137 files, ~63% coverage)
- Good configuration system (YAML-based criteria)
- Loguru logging infrastructure

**Critical Issues:**
- Hardcoded account number in order submission (security risk)
- Bare except clauses in critical threading code
- Business logic embedded in CLI (40+ instances)
- Missing error handling around TWS API calls
- ~37% of critical trading code untested

---

## 1. High-Level Architecture Map

### 1.1 9-Layer Architecture

```
LAYER 9: CLI (54 modules)           → User Interface & Orchestration
LAYER 8: EXPORT (7 modules)         → Output/Persistence
LAYER 7: SERVICES (23 modules)      → Business Orchestration
LAYER 6: STRATEGIES (14 modules)    → Strategy Logic
LAYER 5: ANALYSIS (18 modules)      → Business Calculations
LAYER 4: CORE DATA (13 modules)     → Domain Models
LAYER 3: API (18 modules)           → TWS Connection
LAYER 2: IBAPI (32 modules)         → Protocol Wrapper
LAYER 1: FOUNDATION (logutils, config, helpers)
```

### 1.2 Module Dependency Statistics

| Metric | Value | Status |
|--------|-------|--------|
| Total modules | 245 | - |
| Leaf modules (no internal deps) | 141 (57%) | Good |
| Circular dependencies | 0 | Excellent |
| Avg dependencies per module | 3.2 | Healthy |
| Max dependencies (cli.controlpanel) | 33 | Too High |

### 1.3 Entry Points

| Entry Point | File | Purpose |
|-------------|------|---------|
| Main CLI | `tomic/cli/app.py` | Unified argparse CLI |
| Control Panel | `tomic/cli/controlpanel/__main__.py` | Interactive menu system |
| Strategy Dashboard | `tomic/cli/strategy_dashboard.py` | Opportunity dashboard |
| Exit Flow | `tomic/cli/exit_flow.py` | Position exit workflow |

### 1.4 Data Flow Pipeline

```
TWS API (IB Connection)
    ↓
api.ib_connection.IBClient
    ↓
api.getonemarket.run() → services.ib_marketdata
    ↓
services.chain_processing → Normalization
    ↓
analysis.proposal_engine → Main Orchestrator
├→ analysis.greeks
├→ analysis.metrics
└→ services.strategy_pipeline
    ├→ strike_selector
    ├→ strategy_candidates
    └→ strategies.* (7 strategies)
    ↓
core.portfolio.services
    ↓
services.order_submission → TWS
    ↓
journal.service → Persistence
```

### 1.5 Configuration Files

| File | Purpose | Lines |
|------|---------|-------|
| `criteria.yaml` | Central rules for all strategies | ~500 |
| `config/symbols.yaml` | 165 trading symbols | ~170 |
| `config/strategies.yaml` | Per-strategy parameters | ~200 |
| `config/runtime.yaml` | Runtime settings | ~50 |

---

## 2. Code Quality & Technical Debt Assessment

### 2.1 Critical Issues (MUST FIX)

#### Issue #1: Hardcoded Account Number (SECURITY RISK)

**Location:** `tomic/services/order_submission.py:1175, 1385`

```python
order.account = account or "DUK809533"  # CRITICAL: Wrong account = real money loss
```

**Problem:** If account parameter is None, orders execute on wrong account.
**Fix:** Raise `ValueError` if account is not provided instead of using fallback.
**Risk:** HIGH - Could execute trades on wrong account.

---

#### Issue #2: Bare Except in Critical Threading Code

**Location:** `tomic/ibapi/reader.py:48`

```python
except:  # Catches KeyboardInterrupt, SystemExit - thread dies silently
    logger.exception("unhandled exception in EReader thread")
```

**Problem:** Catches all exceptions including `KeyboardInterrupt`, `SystemExit`. If EReader thread dies, orders hang indefinitely with no indication.
**Fix:** Change to `except Exception:` and implement thread health monitoring.
**Risk:** HIGH - Silent connection death with no recovery.

---

#### Issue #3: Missing Timeout Checks on Event.wait()

**Location:** `tomic/api/market_client.py:737, 876`

```python
self.spot_event.wait(2)   # Returns True/False but ignored
self.data_event.wait(10)  # Code continues regardless of timeout
```

**Problem:** Code continues whether timeout succeeded or failed - race conditions, spot price may be stale or None.
**Fix:** Check return value and raise `TimeoutError` if False.
**Risk:** HIGH - Race conditions, stale data in trading decisions.

---

#### Issue #4: Exception Swallowing with pass

**Locations:**
- `tomic/api/ib_connection.py:93-96`
- `tomic/api/market_client.py:485-488`
- `tomic/api/historical_iv.py:158-161`

```python
except Exception:
    pass  # Request ID never cancelled on IB server
```

**Problem:** Request ID resource exhaustion on IB server, connection issues silently ignored.
**Fix:** Log at WARNING level, consider retry logic.
**Risk:** MEDIUM - Resource leaks, silent failures.

---

### 2.2 High Priority Issues (SHOULD FIX)

#### Issue #5: Business Logic in CLI (40+ instances)

**Worst offenders:**

| File | Lines | Issues | Impact |
|------|-------|--------|--------|
| `cli/strategy_dashboard.py` | 547 | 7 major | Cannot unit test ROM calculations, theta efficiency |
| `cli/iv_backfill_flow.py` | 390 | 6 major | CSV parsing, data merging untestable |
| `cli/controlpanel/portfolio_ui.py` | 888 | 4 major | Portfolio aggregations in display code |
| `cli/portfolio/menu_flow.py` | 695 | 3 major | Position linking logic in menu |
| `cli/rejections/handlers.py` | 608 | 3 major | Filtering logic in presentation |

**Example (strategy_dashboard.py:253):**
```python
def print_strategy_full(strategy, earnings_data):
    # Business calculation embedded in display function
    rom = (strategy.max_profit / strategy.margin) * 100  # Should be in service
    theta_eff = strategy.theta / strategy.net_credit  # Should be in analysis
    print(f"ROM: {rom:.1f}%")  # Mixed with presentation
```

**Fix:** Extract to `services.strategy_metrics.py` with functions like:
- `calculate_rom(strategy) -> float`
- `calculate_theta_efficiency(strategy) -> float`

**Impact:** ~10% of code is currently unit testable → could reach 80%+

---

#### Issue #6: Duplicated Code Patterns

**A. Option Lookup Files (95% duplication)**
- `tomic/cli/option_lookup.py`
- `tomic/cli/option_lookup_bulk.py`

**Fix:** Extract to `option_lookup_base.py` with shared logic.

**B. Greeks Calculations (3 implementations)**
- `analysis/greeks.py` - `compute_portfolio_greeks()`
- `analysis/greeks.py` - `compute_greeks_by_symbol()`
- `metrics.py` - `aggregate_greeks()` (schema-based, better)

**Fix:** Standardize on schema-based approach, deprecate older functions.

**C. Table Formatting (repeated pattern)**
- Manual column-width calculation in `cli/portfolio_greeks.py`
- Better pattern exists in `formatting/table_builders.py`

**Fix:** Consolidate all table rendering to use `TableSpec`/`ColumnSpec`.

---

#### Issue #7: Critical Untested Code

| Module | Test Coverage | Risk |
|--------|--------------|------|
| `services/portfolio_service.py` | 0% | Used by all recommendations |
| `api/ib_connection.py` | 0% | Thread safety untested |
| `services/_config.py` | 0% | Controls exit behavior |
| `services/proposal_generation.py` | 0% | Entry point for trading |

**Impact:** ~37% of trading-critical code has no tests.

---

### 2.3 Medium Priority Issues (NICE TO HAVE)

#### Issue #8: Logging Problems

**A. Noisy DEBUG logs in hot path**
```python
# tomic/ibapi/connection.py:68-83
# 6 DEBUG logs in sendMsg() - megabytes of logs
```

**B. 65+ print() statements in single file**
- `cli/controlpanel/portfolio_ui.py` - not capturable by logging

**C. Missing request IDs in order pipeline**
- Cannot trace order from proposal → execution

**Fix:** Add `trade_id` UUID through entire pipeline.

---

#### Issue #9: Hardcoded Values (should be config)

| Value | Location | Recommended Config Key |
|-------|----------|------------------------|
| `req_id = 5000` | market_client.py | `ib.request_id_base.market_data` |
| `timeout = 120` | market_client.py | `ib.timeouts.market_data` |
| `INTEREST_RATE = 0.05` | bs_utils.py | `pricing.interest_rate` |
| `252` (trading days) | Multiple files | `market.trading_days_per_year` |

---

#### Issue #10: CLI Controlpanel Too Coupled

**Location:** `tomic/cli/controlpanel/__init__.py`

**Problem:** 33 dependencies - hard to maintain, test, extend.
**Fix:** Break into smaller focused menu modules:
- `portfolio_menu.py`
- `strategy_menu.py`
- `tools_menu.py`
- `data_menu.py`

---

## 3. Prioritized Technical Debt Roadmap

### Level 1: MUST FIX (Week 1) - Correctness & Stability

| Task | Files | Effort | Impact |
|------|-------|--------|--------|
| 1.1 Remove hardcoded account | `services/order_submission.py` | 30 min | CRITICAL - prevents wrong-account trades |
| 1.2 Fix bare except in EReader | `ibapi/reader.py` | 1 hr | HIGH - prevents silent connection death |
| 1.3 Add timeout checks on wait() | `api/market_client.py` | 2 hr | HIGH - prevents race conditions |
| 1.4 Stop exception swallowing | `api/ib_connection.py`, `market_client.py`, `historical_iv.py` | 2 hr | MEDIUM - enables debugging |
| 1.5 Add tests for _config.py | `tests/services/test_config.py` | 3 hr | MEDIUM - validates exit behavior |

**Total:** ~8-9 hours

---

### Level 2: SHOULD FIX (Weeks 2-3) - Development Velocity

| Task | Files | Effort | Impact |
|------|-------|--------|--------|
| 2.1 Extract strategy metrics from CLI | `cli/strategy_dashboard.py` → `services/strategy_metrics.py` | 4 hr | Enables unit testing ROM, theta |
| 2.2 Extract IV backfill logic | `cli/iv_backfill_flow.py` → `services/iv_backfill_service.py` | 6 hr | CSV parsing testable |
| 2.3 Merge option_lookup files | `cli/option_lookup.py`, `option_lookup_bulk.py` | 2 hr | Reduces duplication |
| 2.4 Standardize Greeks calculations | `analysis/greeks.py`, `metrics.py` | 3 hr | Single source of truth |
| 2.5 Add portfolio_service tests | `tests/services/test_portfolio_service.py` | 5 hr | Tests all recommendations |
| 2.6 Add ib_connection tests | `tests/api/test_ib_connection.py` | 6 hr | Tests thread safety |
| 2.7 Add request ID tracking | `services/order_submission.py` | 3 hr | Enables order audit trail |

**Total:** ~29 hours

---

### Level 3: NICE TO HAVE (Week 4+) - Long-term Health

| Task | Files | Effort | Impact |
|------|-------|--------|--------|
| 3.1 Break up controlpanel | `cli/controlpanel/__init__.py` | 8 hr | Reduces coupling to <15 deps |
| 3.2 Move hardcoded values to config | Multiple | 4 hr | Centralized configuration |
| 3.3 Reduce logging noise | `ibapi/connection.py` | 2 hr | Better debugging |
| 3.4 Convert prints to logger | `cli/controlpanel/portfolio_ui.py` | 3 hr | Capturable output |
| 3.5 Add proposal_generation tests | `tests/services/` | 4 hr | Tests trading entry point |
| 3.6 Consolidate table formatting | `cli/*.py` | 4 hr | DRY principle |

**Total:** ~25 hours

---

## 4. Quick Wins vs. Larger Refactors

### 4.1 Quick Wins (Few Hours Each)

#### Quick Win #1: Remove Hardcoded Account (30 min)

```python
# Before (order_submission.py:1175)
order.account = account or "DUK809533"

# After
if not account:
    raise ValueError("Account must be provided for order submission")
order.account = account
```

**Impact:** Prevents critical trading error immediately.

---

#### Quick Win #2: Fix Bare Except (1 hr)

```python
# Before (reader.py:48)
except:
    logger.exception("unhandled exception in EReader thread")

# After
except Exception as e:
    logger.exception("unhandled exception in EReader thread")
    # Notify connection manager of thread death
    self.conn.disconnect()
```

---

#### Quick Win #3: Add Timeout Checks (2 hr)

```python
# Before (market_client.py:737)
self.spot_event.wait(2)

# After
if not self.spot_event.wait(2):
    raise TimeoutError(f"Timeout waiting for spot price for {symbol}")
```

---

#### Quick Win #4: Add _config.py Tests (3 hr)

Create `tests/services/test_config.py` with parametrized tests for:
- `get_exit_spread_absolute()`
- `get_exit_spread_relative()`
- `get_exit_dte_threshold()`

---

#### Quick Win #5: Merge Option Lookup Files (2 hr)

Create `cli/option_lookup_base.py` with shared logic:
- Connection handling
- Contract creation
- Result formatting

Then have both files import from base.

---

### 4.2 Larger Refactors (Strong Long-term Payoff)

#### Large Refactor #1: Extract CLI Business Logic (2-3 days)

**Scope:** Extract from 7 CLI files to 4 new service modules

**New modules to create:**
1. `services/strategy_metrics.py` - ROM, theta efficiency, scores
2. `services/iv_backfill_service.py` - CSV parsing, data merging
3. `services/portfolio_display_service.py` - Aggregations, formatting data
4. `services/position_linking_service.py` - Position correlation logic

**Benefits:**
- Unit test coverage: 10% → 80%+
- CLI files shrink from 500-800 lines to <200
- Business logic reusable across different interfaces

---

#### Large Refactor #2: Implement Trade ID Tracking (1-2 days)

**Scope:** Add UUID tracking through entire order pipeline

```python
# services/order_submission.py
def submit_order(proposal, account) -> str:
    trade_id = str(uuid.uuid4())
    logger.info(f"[{trade_id}] Starting order submission for {proposal.symbol}")
    # ... rest of flow with trade_id in every log
    return trade_id
```

**Benefits:**
- Complete audit trail for any trade
- Easier debugging of order failures
- Compliance and journaling improved

---

#### Large Refactor #3: Break Up Controlpanel (2 days)

**Current:** `cli/controlpanel/__init__.py` with 33 dependencies, 535 lines

**Target structure:**
```
cli/controlpanel/
├── __init__.py          # Just imports and menu dispatch (100 lines)
├── portfolio_menu.py    # Portfolio operations
├── strategy_menu.py     # Strategy selection
├── tools_menu.py        # Calculators, lookups
├── data_menu.py         # Data fetching, health
└── common.py            # Shared menu utilities
```

**Benefits:**
- Each menu module <15 dependencies
- Easier to test individual flows
- Easier to add new menu items

---

## 5. Assumptions & Open Questions

### 5.1 Assumptions Made

1. **Account "DUK809533" is a paper trading account** - If not, this is an even more critical security issue.

2. **The project prioritizes correctness over performance** - Recommendations assume reliability matters more than latency.

3. **IB TWS runs locally** - Timeout values assume local connection; if remote, timeouts may need adjustment.

4. **Single user system** - No concurrent access considerations in the review.

5. **Python 3.10+** - Based on syntax patterns observed.

### 5.2 Open Questions

1. **Why is `cli/controlpanel` 33 dependencies?**
   Is this intentional as a "god object" orchestrator, or should it be split?

2. **Are there plans for automated/algorithmic trading?**
   Current architecture assumes manual decision support. Automation would require different patterns.

3. **What's the expected symbol scale?**
   Currently 165 symbols. Architecture seems fine for 500+, but 1000+ would need review.

4. **Is the EReader bare except intentional?**
   Perhaps there was a reason to catch SystemExit? If so, should be documented.

5. **Why duplicate Greeks implementations?**
   Is `compute_portfolio_greeks()` deprecated? If so, should be marked.

6. **What's the purpose of `ibkr-original-protofiles/`?**
   Are these reference only, or do they need to stay in sync with IB releases?

7. **Is there CI/CD beyond GitHub Actions?**
   The two workflows (fetch_earnings, fetch_prices) seem like scheduled data jobs, not CI.

---

## 6. Summary Metrics

| Category | Current | Target | Notes |
|----------|---------|--------|-------|
| Test Coverage | 63% | 78% | +55 tests for critical paths |
| CLI with mixed concerns | 7 files | 0 files | Extract to 4 service modules |
| Bare except clauses | 1 | 0 | Critical thread safety |
| Exception swallowing | 3 | 0 | Enable debugging |
| Hardcoded critical values | 2 | 0 | Account, request IDs |
| Max module dependencies | 33 | 15 | Split controlpanel |

---

## 7. Recommended Implementation Order

### Week 1: Critical Fixes
1. Remove hardcoded account (30 min)
2. Fix EReader bare except (1 hr)
3. Add timeout checks (2 hr)
4. Add _config.py tests (3 hr)
5. Stop exception swallowing (2 hr)

### Week 2: Testing & Extraction
6. Add portfolio_service tests (5 hr)
7. Extract strategy_metrics from CLI (4 hr)
8. Merge option_lookup files (2 hr)

### Week 3: More Extraction
9. Add ib_connection tests (6 hr)
10. Extract iv_backfill_service (6 hr)
11. Add request ID tracking (3 hr)

### Week 4: Structural Improvements
12. Break up controlpanel (8 hr)
13. Standardize Greeks (3 hr)
14. Move hardcoded to config (4 hr)

---

## 8. Conclusion

TOMIC has a solid architectural foundation with clean layering and no circular dependencies. The main technical debt centers around:

1. **Critical safety issues** (hardcoded account, missing timeouts) - Fix immediately
2. **Testability** (business logic in CLI) - 2-3 day refactor for major improvement
3. **Code duplication** - Several quick wins available

The 4-week roadmap above addresses all major issues while keeping the system stable. The total estimated effort is **~62 hours**, with the first week being most critical for trading safety.

**Priority recommendation:** Complete Week 1 tasks before any new feature development.

---

*Report generated by comprehensive codebase analysis on 2025-11-19*
