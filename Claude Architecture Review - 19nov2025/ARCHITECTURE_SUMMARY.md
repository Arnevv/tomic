# TOMIC Architecture Summary

## Quick Reference

### Codebase Size
- **Total Modules**: 245 Python files
- **Leaf Modules** (no internal dependencies): 141 (57%)
- **Max Dependencies** in a single module: 33
- **Circular Dependencies**: 0 ✓
- **Reciprocal Imports**: 0 ✓

### Overall Assessment: **GOOD ARCHITECTURE**
Clean layering with proper separation of concerns, no architectural debt.

---

## 9-Layer Architecture

```
┌─────────────────────────────────────────────┐
│  LAYER 9: CLI (54 modules)                  │  User Interface
│  ├─ controlpanel (33 deps - TOO COUPLED)    │
│  ├─ app_services (7 deps)                   │
│  └─ Various workflows                       │
├─────────────────────────────────────────────┤
│  LAYER 8: EXPORT (7 modules)                │  Output
│  ├─ csv_exporter                            │
│  ├─ json_exporter                           │
│  └─ journal_exporter                        │
├─────────────────────────────────────────────┤
│  LAYER 7: SERVICES (23 modules)             │  Orchestration
│  ├─ strategy_pipeline (13 importers)        │
│  ├─ ib_marketdata (11 deps)                 │
│  ├─ chain_processing (9 deps)               │
│  └─ order_submission, exit_flow, etc.       │
├─────────────────────────────────────────────┤
│  LAYER 6: STRATEGIES (14 modules)           │  Strategy Logic
│  ├─ strategies.* (iron condor, spreads)     │
│  ├─ strike_selector                         │
│  ├─ strategy_candidates                     │
│  └─ strategy.* (models, reason_engine)      │
├─────────────────────────────────────────────┤
│  LAYER 5: ANALYSIS (18 modules)             │  Business Logic
│  ├─ proposal_engine (11 deps) ◆ HUB         │
│  ├─ greeks (7 importers)                    │
│  ├─ metrics (6 importers)                   │
│  └─ volatility_fetcher, rules, scoring      │
├─────────────────────────────────────────────┤
│  LAYER 4: CORE DATA (13 modules)            │  Domain Model
│  ├─ portfolio.services (12 deps) ◆ HUB      │
│  ├─ pricing.* (mid_service, mid_tags)       │
│  ├─ config.* (strike_selection, models)     │
│  └─ data.* (chain_normalizer)               │
├─────────────────────────────────────────────┤
│  LAYER 3: API (18 modules)                  │  TWS Connection
│  ├─ ib_connection (7 importers) ◆ HUB       │
│  ├─ base_client                             │
│  ├─ getonemarket                            │
│  └─ option_metrics, market_client, etc.     │
├─────────────────────────────────────────────┤
│  LAYER 2: IBAPI (32 modules)                │  IBKR Protocol
│  ├─ connection, client, contract            │
│  └─ order, execution, decoder               │
├─────────────────────────────────────────────┤
│  LAYER 1: FOUNDATION (5 modules)            │  Core Utils
│  ├─ logutils (71 importers) ★ CRITICAL     │
│  ├─ config (44 importers) ★ CRITICAL       │
│  ├─ utils (21 importers)                    │
│  ├─ models (7 importers)                    │
│  └─ criteria (RULES object)                 │
├─────────────────────────────────────────────┤
│  HELPERS (16 modules)                       │  Cross-cutting
│  ├─ helpers.dateutils (12 importers)        │
│  ├─ helpers.price_utils (11 importers)      │
│  ├─ helpers.numeric (11 importers)          │
│  └─ bs_utils, config, quality_check, etc.   │
└─────────────────────────────────────────────┘

Legend:
  ◆ = Orchestrator module (multiple dependencies expected)
  ★ = Critical foundation (many importers, single point of failure)
  ! = Issue area (TOO COUPLED for its layer)
```

---

## Critical Dependencies

### Most Imported (Bottleneck Modules)
| Module | Importers | Role |
|--------|-----------|------|
| **logutils** | 71 | Logging system ⚠️ CRITICAL |
| **config** | 44 | App configuration ⚠️ CRITICAL |
| **journal.utils** | 23 | JSON I/O utilities |
| **utils** | 21 | General utilities |
| **strategy_pipeline** | 13 | Main orchestrator |
| **helpers.dateutils** | 12 | Date utilities |
| **helpers.price_utils** | 11 | Price calculations |
| **helpers.numeric** | 11 | Math utilities |

### Most Connected (High Dependencies)
| Module | Dependencies | Role |
|--------|--------------|------|
| **cli.controlpanel** | 33 | UI aggregator ⚠️ TOO COUPLED |
| **cli.controlpanel.portfolio_ui** | 23 | Portfolio UI |
| **cli.portfolio.menu_flow** | 15 | Menu orchestrator |
| **services.order_submission** | 12 | Order placement |
| **core.portfolio.services** | 12 | Portfolio ops ✓ |
| **services.ib_marketdata** | 11 | Market data service |
| **analysis.proposal_engine** | 11 | Proposal generator ✓ |

---

## Data Flow Pipeline

```
TWS Connection
    ↓
api.ib_connection.IBClient
    ↓
api.getonemarket.run()  →  fetch option chain
    ↓
services.ib_marketdata.fetch_quote_snapshot()  →  create snapshot
    ↓
services.chain_processing.load_and_prepare_chain()  →  normalize
    ↓
analysis.proposal_engine.generate_proposals()
    ├─→ analysis.greeks.compute_portfolio_greeks()
    ├─→ analysis.metrics.compute_term_structure()
    ├─→ criteria.RULES (apply entry rules)
    └─→ services.strategy_pipeline.run()
        ├─→ strike_selector.StrikeSelector
        ├─→ strategy_candidates.generate_strategy_candidates()
        ├─→ strategies.* (iron_condor, spreads, etc.)
        └─→ core.pricing.MidService (price proposals)
    ↓
core.portfolio.services.prepare_order()  →  prepare for submission
    ↓
services.order_submission.OrderSubmissionService  →  submit to TWS
    ↓
export.csv_exporter.export_proposals_csv()  →  output CSV
    ↓
journal.service.update_journal()  →  persist trades
```

---

## Key Module Relationships

### Proposal Generation Cluster (Well-Coupled ✓)
- **analysis.proposal_engine** (orchestrator)
  - imports: greeks, metrics, criteria, chain_processing, strategy_pipeline
  - coordinates entire proposal generation
  
- **services.strategy_pipeline** (executor)
  - imports: strike_selector, strategy_candidates, strategies, pricing
  - filters, ranks, scores proposals

### Portfolio Operations Cluster (Well-Coupled ✓)
- **core.portfolio.services** (orchestrator)
  - imports: greeks, criteria, order_submission, exit_flow, export
  - coordinates all portfolio operations
  
- **services.order_submission** (executor)
  - imports: api.ib_connection, core.pricing
  - submits orders to TWS

### Market Data Cluster (Well-Coupled ✓)
- **services.ib_marketdata** (fetcher)
  - imports: api.base_client, api.ib_connection
  - fetches and manages snapshots
  
- **services.chain_processing** (normalizer)
  - imports: core.data, helpers
  - normalizes chains for analysis

---

## Issues & Recommendations

### Critical Issues

❌ **cli.controlpanel is TOO COUPLED (33 dependencies)**
- Severity: MEDIUM
- Problem: Acts as catch-all aggregator for main menu
- Fix: Break into smaller focused menu modules
- Priority: MEDIUM
- Effort: MEDIUM

### Potential Issues

⚠️ **logutils ubiquity (71 importers)**
- Risk: Single point of failure for logging
- Mitigation: Stable interface, well-tested
- Status: Acceptable (necessary)

⚠️ **config criticality (44 importers)**
- Risk: Configuration system is critical
- Mitigation: Validate early, separate load/use
- Status: Good practice needed

### Strengths

✅ NO circular dependencies (0)
✅ NO reciprocal imports (0)
✅ 57% leaf modules (easy to test)
✅ Clear unidirectional flow
✅ Proper foundation layers
✅ Well-defined orchestrators

---

## Quick Troubleshooting Guide

**"Proposal generation is slow"** → Check:
- `services.strategy_pipeline` (main executor)
- `analysis.proposal_engine` (orchestrator)
- `strike_selector` (strike selection logic)

**"Order submission fails"** → Check:
- `api.ib_connection` (TWS connection)
- `services.order_submission` (order logic)
- `core.portfolio.services` (portfolio ops)

**"Rules not being applied"** → Check:
- `criteria.RULES` (rules definition)
- `analysis.rules` (rule evaluation)
- `analysis.proposal_engine` (uses rules)

**"Greeks calculations incorrect"** → Check:
- `analysis.greeks` (calculation logic)
- `core.pricing.*` (pricing models)
- `helpers.numeric` (math utilities)

**"CSV export broken"** → Check:
- `export.csv_exporter` (export logic)
- `export.utils` (metadata)
- `infrastructure.storage` (file I/O)

---

## Module Health Checklist

When modifying a module, verify:
- [ ] Single responsibility principle
- [ ] <10 dependencies (non-orchestrators)
- [ ] <20 public exports
- [ ] Clear documentation
- [ ] >80% test coverage
- [ ] No deprecated patterns
- [ ] Type hints for public API
- [ ] Proper error handling

Current Status:
- ✓ Most modules pass
- ✗ cli.controlpanel fails dependency check
- ⚠ Some analysis modules need documentation

---

## For New Contributors

1. **Understanding the flow**: Start with `/DEPENDENCY_ANALYSIS.txt` (section 4)
2. **Finding where to add code**: Check layer descriptions above
3. **Modifying existing code**: Review the issues section
4. **Testing changes**: Focus on modules in the "Critical Dependencies" table
5. **Avoiding regressions**: Don't add circular dependencies

---

## Files & Further Reading

- **Detailed Analysis**: `/home/user/tomic/DEPENDENCY_ANALYSIS.txt`
- **Architecture Overview**: This file
- **Code Location**: `/home/user/tomic/tomic/`

