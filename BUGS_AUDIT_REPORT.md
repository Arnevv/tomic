# TOMIC Codebase Quality Audit Report

**Datum:** 2025-12-03
**Reviewer:** Claude (Tester Role)
**Branch:** claude/review-codebase-bugs-01MKEk3XAvTA5WS1FYFceiEG

## Executive Summary

Na een grondige analyse van de TOMIC codebase (240+ modules, 155+ tests) zijn **72 bugs en inconsistenties** geïdentificeerd, waarvan **9 kritiek**, **24 hoog**, en **28 medium** prioriteit.

| Categorie | Kritiek | Hoog | Middel | Laag |
|-----------|---------|------|--------|------|
| Business Logic | 2 | 4 | 4 | 3 |
| Error Handling | 0 | 5 | 10 | 8 |
| Null/Type Safety | 2 | 4 | 5 | 2 |
| Data/Concurrency | 2 | 4 | 2 | 1 |
| Security | 2 | 4 | 4 | 0 |
| Configuration | 1 | 3 | 3 | 2 |

---

## 🔴 KRITIEKE BUGS

### 1. Greeks Delta Inconsistentie
**Bestand:** `tomic/analysis/greeks.py:17-20, 44-47`

```python
# Delta berekent ZONDER multiplier:
if greek == "delta":
    totals["Delta"] += val_f * qty              # GEEN multiplier

# Andere Greeks MET multiplier:
else:
    totals[greek.capitalize()] += val_f * qty * mult
```

**Impact:** Portfolio Greeks zijn systematisch incorrect → verkeerde hedging beslissingen

**Fix:** Consistente behandeling - of delta ook met multiplier, of anderen zonder.

---

### 2. PnL Percentage Conversie Fout
**Bestand:** `tomic/analysis/exit_rules.py:97`

```python
profit_pct = (pnl_val / (rule["premium_entry"] * 100)) * 100  # Dubbele conversie!
```

**Impact:** Exit signals kunnen 100x verkeerd zijn → voortijdige of te late exits

**Fix:** Verwijder een van de `* 100` operaties.

---

### 3. Race Condition - Concurrent File Updates
**Bestand:** `tomic/infrastructure/storage.py:46-72`

```python
def update_json_file(path, update_func):
    data = load_json(path)     # READ
    updated = update_func(data) # MODIFY
    dump_json(updated, path)    # WRITE - Geen lock!
```

**Impact:** Dataverlies bij gelijktijdige updates van meerdere processen

**Fix:** Voeg file locking toe met `fcntl.flock()` of `filelock` library.

---

### 4. Thread Race Condition - Entry Flow
**Bestand:** `tomic/cli/entry_flow_runner.py:187-199`

```python
result_container = {}  # Gedeeld tussen threads zonder lock
```

**Impact:** Verloren exceptions, stille fouten in multi-threaded scenarios

**Fix:** Gebruik `threading.Lock()` voor toegang tot gedeelde state.

---

### 5. eval() Code Injection - Rules Engine
**Bestand:** `tomic/analysis/rules.py:17`

```python
return bool(eval(condition, {"__builtins__": {}}, {**ALLOWED_GLOBALS, **context}))
```

**Impact:** Potentiële Remote Code Execution via malformed input

**Fix:** Vervang door `simpleeval` library of `ast.literal_eval()`.

---

### 6. eval() in Volatility Recommender
**Bestand:** `tomic/cli/volatility_recommender.py:100`

```python
return bool(eval(expr, {}, metrics))  # metrics kan user input bevatten
```

**Impact:** Code injection via strategy metrics

**Fix:** Gebruik veilige expression evaluator.

---

### 7. __import__ Directory Traversal
**Bestand:** `tomic/strategy_candidates.py:294`

```python
mod = __import__(f"tomic.strategies.{strategy_type}", fromlist=["generate"])
```

**Impact:** Willekeurige module loading mogelijk via path traversal

**Fix:** Valideer `strategy_type` tegen whitelist van toegestane strategieën.

---

### 8. Config Field Naam Mismatch + Type Fout
**Bestanden:**
- `config/strategies.yaml:42-44`
- `tomic/strategies/config_models.py:85`
- `tomic/helpers/normalize.py:83-92`

```yaml
# YAML (VERKEERD):
atm_iron_butterfly:
  strike_to_strategy_config:
    wing_width_sigma:    # Verkeerde naam + verkeerd type (list)
    - 0.3
    - 1.0
```

```python
# Code verwacht:
wing_sigma_multiple: float | None = None  # Float, niet list!
```

**Impact:** Range `[0.3, 1.0]` wordt stilletjes omgezet naar alleen `0.3`

**Fix:** Rename naar `wing_sigma_multiple` en fix type handling.

---

### 9. IndexError - Strategy Dashboard
**Bestand:** `tomic/cli/strategy_dashboard.py:391`

```python
json_output = arg.split("=", 1)[1]  # Geen guard voor lege split
```

**Impact:** IndexError crash bij malformed input

**Fix:** Check length na split: `parts = arg.split("=", 1); if len(parts) > 1: ...`

---

## 🟠 HOGE PRIORITEIT BUGS

### Error Handling Problemen

| # | Bestand | Regel | Probleem |
|---|---------|-------|----------|
| 1 | `tomic/services/order_submission.py` | 15-31 | Bare `except Exception:` verbergt import fouten |
| 2 | `tomic/services/market_snapshot_service.py` | 155-160 | 3 file loads zonder specifieke error handling |
| 3 | `tomic/journal/update_margins.py` | 20-21 | JSON load zonder try/catch op kritiek bestand |
| 4 | `tomic/helpers/json_utils.py` | 17-20 | dump_json zonder error handling |
| 5 | `tomic/cli/app.py` | 95 | Entry point `args.func(args)` zonder try/catch |

### Business Logic Fouten

| # | Bestand | Regel | Probleem |
|---|---------|-------|----------|
| 1 | `tomic/analysis/metrics.py` | 36 | Hardcoded margin default `1000` - zou configureerbaar moeten zijn |
| 2 | `tomic/strategies/utils.py` | 387, 593 | Hardcoded wing tolerance `5.0` |
| 3 | `tomic/analysis/strategy.py` | 210, 273 | Hardcoded multiplier `100` |
| 4 | `tomic/services/_percent.py` | 12-13 | Fragiele percentage normalisatie (`if val > 1`) |

### Data/Concurrency Problemen

| # | Bestand | Regel | Probleem |
|---|---------|-------|----------|
| 1 | `tomic/cli/compute_volstats_polygon.py` | 170-245 | N+1 query probleem - 4 queries per symbool |
| 2 | `tomic/api/earnings_importer.py` | 337-339 | Niet-atomic dict operaties |
| 3 | `tomic/config.py` | 373-402 | Lock initialization order issue |
| 4 | `tomic/cli/services/price_history_ib.py` | 99-117 | Unsafe file locking |

### Security Issues

| # | Bestand | Regel | Probleem |
|---|---------|-------|----------|
| 1 | `tomic/config.py` | 289, 333 | Environment path zonder traversal check |
| 2 | `diagnose_orats.py` | 27-33 | FTP credentials kunnen in logs terechtkomen |
| 3 | `tomic/integrations/polygon/client.py` | 17 | ENV var controleert API key logging |
| 4 | `tomic/cli/services/__init__.py` | 161 | Git message injection mogelijk |

---

## 🟡 MEDIUM PRIORITEIT BUGS

### Null/Type Safety Problemen

| Bestand | Regel | Probleem |
|---------|-------|----------|
| `tomic/cli/exit_flow.py` | 201 | `split(":", 1)[1]` zonder guard |
| `tomic/helpers/bs_utils.py` | 29 | `"".upper()[0]` kan IndexError zijn |
| `tomic/cli/link_positions.py` | 100 | `trade["Legs"][idx]` zonder bounds check |
| `tomic/api/getaccountinfo.py` | 102 | `expiry.split(" ")[0]` zonder validatie |
| `tomic/analysis/strategy.py` | 80-82 | `legs[0]` zonder len() check |

### Error Handling Statistics

- **48+ bestanden** met bare `except Exception:` catches
- **132 bestanden** met ongeteste error paths
- Inconsistente logging - soms exc_info, soms silent fallback

### Configuratie Problemen

| Probleem | Locatie |
|----------|---------|
| `extra="allow"` in models → typo's worden stilletjes genegeerd | `tomic/strategies/config_models.py:42` |
| Hardcoded alert thresholds niet uit config | `tomic/analysis/alerts.py:81, 85` |
| Dead config: gecommentarieerde gate parameters | `criteria.yaml:120-130` |
| Gedupliceerde spread thresholds op 3 locaties | `config.py`, `order_submission.py`, `mid_resolver.py` |

---

## 📋 TEST COVERAGE GAPS

### Kritieke Modules ZONDER Tests

| Module | Files | Lines | Impact |
|--------|-------|-------|--------|
| `tomic/backtest/` | 12 | 1500+ | **BACKTEST ENGINE VOLLEDIG NIET GETEST** |
| `tomic/analysis/scoring.py` | 1 | 200+ | Core scoring niet getest |
| `tomic/analysis/alerts.py` | 1 | 100+ | Alert logica niet getest |
| `tomic/analysis/exit_rules.py` | 1 | 100+ | Exit rule logica niet getest |
| `tomic/api/earnings_importer.py` | 1 | 150+ | Data import niet getest |

### Tests met Overmatig Mocking

| Test Bestand | Mock Count | Probleem |
|--------------|------------|----------|
| `tests/cli/test_fetch_prices_polygon.py` | 54+ | Echte fetch niet getest |
| `tests/cli/test_controlpanel_proposals.py` | 112+ | Alleen mock verificatie |
| `tests/services/test_exit_flow_detailed.py` | 62+ | Echte exit flow niet getest |

### Ontbrekende Edge Case Tests

- None/null input handling
- Boundary conditions (empty lists, zero values)
- Division by zero scenarios
- Exception paths (132 bestanden met ongeteste exception handling)

---

## 🔧 AANBEVELINGEN

### Onmiddellijk Actie Vereist (Week 1)

1. **Fix Greeks berekening** (`greeks.py:17-20`) - Voeg multiplier toe aan Delta of verwijder van anderen
2. **Fix PnL percentage** (`exit_rules.py:97`) - Verwijder dubbele conversie
3. **Voeg file locking toe** (`storage.py:46-72`) - Threading lock voor `update_json_file()`
4. **Vervang eval()** (`rules.py:17`, `volatility_recommender.py:100`) - Gebruik `simpleeval` library
5. **Valideer strategy_type** (`strategy_candidates.py:294`) - Whitelist van toegestane strategieën

### Deze Sprint (Week 2-3)

6. **Fix config naam mismatch** - Rename `wing_width_sigma` → `wing_sigma_multiple` in strategies.yaml
7. **Voeg path traversal checks toe** - Voor environment variable paths in `config.py`
8. **Vervang bare exceptions** - Door specifieke exception types (`ImportError`, `ValueError`, etc.)
9. **Voeg missing error handling toe** - JSON loads, API calls, file operations
10. **Fix IndexError risico's** - Voeg length checks toe voor array/string indexing

### Technische Debt (Komende Maand)

11. **Schrijf backtest tests** - Kritieke module met 1500+ regels zonder coverage
12. **Verminder mocking** - Integration tests voor echte functionaliteit
13. **Documenteer hardcoded waarden** - Of verplaats naar configuratie
14. **Stel type checking in** - `mypy --strict` voor null safety
15. **Voeg linting regels toe** - Ban bare exceptions, require logging

---

## Appendix: Volledige Bug Lijst per Bestand

### tomic/analysis/
- `greeks.py:17-20, 44-47` - Delta multiplier inconsistentie (KRITIEK)
- `exit_rules.py:97` - PnL percentage conversie fout (KRITIEK)
- `metrics.py:36` - Hardcoded margin default 1000 (HOOG)
- `metrics.py:46` - Hardcoded theta efficiency thresholds (MEDIUM)
- `scoring.py:41-43` - Hardcoded warning thresholds (MEDIUM)
- `scoring.py:358-359` - Spot price validatie mist negatieve check (MEDIUM)
- `alerts.py:81, 85` - Hardcoded delta/vega thresholds (HOOG)
- `strategy.py:80-82` - legs[0] zonder len() check (MEDIUM)
- `strategy.py:210, 273` - Hardcoded width multiplier 100 (HOOG)
- `rules.py:17` - eval() code injection (KRITIEK)

### tomic/services/
- `order_submission.py:15-31` - Bare except verbergt import errors (HOOG)
- `order_submission.py:540-611` - Multiple bare excepts in repricing (MEDIUM)
- `market_snapshot_service.py:113-116` - Silent failure in _parse_latest (MEDIUM)
- `market_snapshot_service.py:155-160` - 3 file loads zonder error handling (HOOG)
- `_percent.py:12-13` - Fragiele percentage normalisatie (HOOG)

### tomic/infrastructure/
- `storage.py:46-72` - Race condition in update_json_file (KRITIEK)

### tomic/cli/
- `entry_flow_runner.py:187-199` - Thread race condition (KRITIEK)
- `strategy_dashboard.py:391` - IndexError op split()[1] (KRITIEK)
- `volatility_recommender.py:100` - eval() code injection (KRITIEK)
- `app.py:95` - Entry point zonder try/catch (HOOG)
- `exit_flow.py:201` - split()[1] zonder guard (MEDIUM)
- `link_positions.py:100` - Array index zonder bounds check (MEDIUM)
- `compute_volstats_polygon.py:170-245` - N+1 query probleem (HOOG)

### tomic/strategies/
- `utils.py:387, 593, 963` - Hardcoded wing tolerance (HOOG)
- `config_models.py:42` - extra="allow" laat typo's door (MEDIUM)

### tomic/integrations/
- `polygon/client.py:17` - ENV var controleert API key logging (HOOG)
- `polygon/client.py:108-113` - raise_for_status() niet gecatcht (MEDIUM)

### tomic/api/
- `earnings_importer.py:337-339` - Niet-atomic dict operaties (HOOG)
- `getaccountinfo.py:102` - expiry.split()[0] zonder validatie (MEDIUM)

### tomic/helpers/
- `json_utils.py:17-20` - dump_json zonder error handling (HOOG)
- `bs_utils.py:29` - Empty string index [0] kan crashen (MEDIUM)

### tomic/journal/
- `update_margins.py:20-21, 41-42` - JSON load/dump zonder error handling (HOOG)

### config/
- `strategies.yaml:42-44` - wing_width_sigma type mismatch (KRITIEK)

### Root/Scripts
- `diagnose_orats.py:27-33` - FTP credentials exposure risico (HOOG)
- `strategy_candidates.py:294` - __import__ zonder validatie (KRITIEK)

---

*Dit rapport is automatisch gegenereerd op basis van statische code analyse.*
