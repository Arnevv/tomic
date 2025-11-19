# CLI Code Analysis: Mixed Concerns & Architectural Issues

## Executive Summary

The TOMIC CLI modules contain **significant mixing of business logic with presentation code**, making them difficult to test independently. Key issues:

- **5 files exceed 500 lines** with mixed responsibilities
- **Business calculations embedded in display functions** (Greeks, metrics, percentage calculations)
- **Data fetching mixed with formatting** (API calls in presentation code)
- **Complex algorithms in CLI** (data merging, gap analysis, filtering logic)
- **Strategy orchestration in presentation layer** (chain evaluation, proposal building)

---

## Critical Issues by File

### 1. `/home/user/tomic/tomic/cli/strategy_dashboard.py` (547 lines)

**WORST OFFENDER** - Massive business logic embedded in print functions

#### Issue 1.1: ROM Calculation in Presentation (Line 253)
```python
# Line 250-254: Embedded financial calculation
pnl_val = strategy.get("unrealizedPnL")
if pnl_val is not None:
    margin_ref = strategy.get("init_margin") or strategy.get("margin_used") or 1000
    rom_now = (pnl_val / margin_ref) * 100  # ← Business logic in CLI
    mgmt_lines.append(f"📍 PnL: {pnl_val:+.2f} (ROM: {rom_now:+.1f}%)")
```
- **What should be extracted:** `calculate_rom_percentage(pnl, margin)` 
- **Where it should go:** `tomic/metrics.py` or new service module
- **Why it matters:** Cannot unit test ROM calculation independently

#### Issue 1.2: Average Price Calculation (Lines 240-248)
```python
# Lines 240-248: Contract quantity and average price calculation
cost_basis = strategy.get("cost_basis")
if cost_basis is not None:
    total_contracts = sum(
        abs(leg.get("position", 0)) * float(leg.get("multiplier") or 1)
        for leg in strategy.get("legs", [])
    )
    if total_contracts:
        avg_price = cost_basis / total_contracts  # ← Business calculation
        mgmt_lines.append(f"📍 Gem. prijs: {avg_price:+.2f}")
```
- **What should be extracted:** `calculate_average_contract_price(cost_basis, legs)`
- **Where it should go:** `tomic/analysis/position_analysis.py` (new module)
- **Why it matters:** Price calculations are business logic, not formatting

#### Issue 1.3: Theta Efficiency Rating (Lines 265-278)
```python
# Lines 265-278: Complex business logic with thresholds in display code
margin = strategy.get("init_margin") or strategy.get("margin_used") or 1000
if theta is not None and margin:
    theta_efficiency = abs(theta / margin) * 100  # ← Calculation
    if theta_efficiency < 0.5:
        rating = "⚠️ oninteressant"
    elif theta_efficiency < 1.5:
        rating = "🟡 acceptabel"
    elif theta_efficiency < 2.5:
        rating = "✅ goed"
    else:
        rating = "🟢 ideaal"
```
- **What should be extracted:** 
  - `calculate_theta_efficiency(theta, margin) -> float`
  - `rate_theta_efficiency(efficiency) -> Tuple[str, str]` (rating + emoji)
- **Where it should go:** `tomic/analysis/greeks_analysis.py`
- **Why it matters:** Threshold-based business logic should not be in presentation

#### Issue 1.4: Spot Price Difference Calculation (Lines 177-188)
```python
# Lines 177-188: Percentage change calculation in display code
diff_pct = None
if spot_open not in (None, 0, "0"):
    try:
        diff_pct = (
            (float(spot_now) - float(spot_open)) / float(spot_open)
        ) * 100  # ← Business calculation
    except (TypeError, ValueError, ZeroDivisionError):
        diff_pct = None
```
- **What should be extracted:** `calculate_spot_change_percent(current, open)`
- **Where it should go:** `tomic/metrics.py`

#### Issue 1.5: Data Loading in Main Logic (Lines 432-435)
```python
# Lines 432-435: Direct data loading in CLI main function
positions = load_positions(positions_file)
account_info = load_account_info(account_file)
journal = load_journal(journal_file)
exit_rules = extract_exit_rules(journal_file)  # ← Data fetching mixed with display
```
- **What should be extracted:** Create a `PortfolioDataLoader` service
- **Where it should go:** `tomic/services/portfolio_data_loader.py`
- **Why it matters:** Cannot mock or test data loading without touching files

#### Issue 1.6: Portfolio Greeks Calculation in Display (Line 448)
```python
# Line 448: Greeks calculation in main display function
portfolio = compute_portfolio_greeks(positions)
```
- **Problem:** No abstraction - directly calling computation in presentation
- **Should use:** Service layer that encapsulates `compute_portfolio_greeks`

#### Issue 1.7: Aggregation Logic in Display (Lines 458-478)
```python
# Lines 458-478: Multiple business calculations mixed in display
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
```
- **What should be extracted:** `PortfolioAggregator` class or service
- **Where it should go:** `tomic/services/portfolio_aggregation.py`
- **Why it matters:** Cannot calculate portfolio metrics without full CLI execution

---

### 2. `/home/user/tomic/tomic/cli/controlpanel/portfolio_ui.py` (888 lines)

**SECOND WORST** - Largest CLI file with extensive mixed concerns

#### Issue 2.1: Proposal Data Fetching in Display (Lines 334-412)
```python
# Lines 334-412: _show_proposal_details - Data fetching mixed with presentation
def _show_proposal_details(
    session: ControlPanelSession, proposal: StrategyProposal
) -> None:
    # ... setup code ...
    
    def _attempt_ib_refresh() -> bool:
        nonlocal proposal, refresh_result, fetch_attempted
        try:
            refresh_result = portfolio_services.refresh_proposal_from_ib(  # ← API call
                proposal,
                symbol=symbol,
                spot_price=session.spot_price,
            )
        except Exception as exc:
            print(f"❌ Marktdata ophalen mislukt: {exc}")
            return False
        proposal = refresh_result.proposal
        fetch_attempted = True
        return True

    if fetch_only_mode or prompt_yes_no("Haal orderinformatie van IB op?", True):
        _attempt_ib_refresh()

    # ... then presentation logic (building tables, printing) ...
    presentation = portfolio_services.build_proposal_presentation(
        session, proposal, refresh_result=refresh_result,
    )
    vm = presentation.viewmodel
    
    leg_headers, leg_rows = proposal_legs_table(vm)
    if leg_rows:
        print(tabulate(leg_rows, headers=leg_headers, tablefmt="github"))
```
- **Problems:**
  - API calls (`refresh_proposal_from_ib`) directly in display function
  - Nested closure with complex state management
  - Mixed error handling (business logic vs UI presentation)
- **What should be extracted:**
  - `ProposalRefreshService` class with `refresh_from_ib()` method
  - `ProposalPresenter` class for formatting
- **Where it should go:** 
  - `tomic/services/proposal_refresh_service.py`
  - `tomic/formatting/proposal_presenter.py`

#### Issue 2.2: Market Snapshot Loading in Display (Lines 540-673)
```python
# Lines 540-673: show_market_info - Data loading + transformation + display
def show_market_info(session: ControlPanelSession, services: ControlPanelServices) -> None:
    symbols = _default_symbols()
    
    vix_value = _fetch_vix_value(symbols)  # ← API call for data
    if vix_value is not None:
        print(f"VIX {vix_value:.2f}")
    
    snapshot = _load_snapshot(services, symbols)  # ← Data loading
    rows = _overview_input(snapshot.rows)  # ← Data transformation
    
    recs, table_rows, meta = _build_overview(rows)  # ← More transformation
    
    # ... complex filtering logic ...
    earnings_filtered: dict[str, Sequence[str]] = {}
    if isinstance(meta, dict):
        earnings_filtered = meta.get("earnings_filtered", {}) or {}
    if earnings_filtered:
        total_hidden = sum(len(strategies) for strategies in earnings_filtered.values())  # ← Calculation
        detail_parts = []
        for symbol in sorted(earnings_filtered):
            strategies = ", ".join(earnings_filtered[symbol])
            detail_parts.append(f"{symbol}: {strategies}")
        detail_msg = "; ".join(detail_parts)
        print(f"ℹ️ {total_hidden} aanbevelingen verborgen...")
```
- **Problems:**
  - Lines 550: Multiple data transformation calls without service abstraction
  - Line 556: Calculation logic (`sum(len(strategies)...)`) for display
  - Line 558-560: String formatting logic mixed with data processing
- **What should be extracted:**
  - `MarketInfoLoader` service for data fetching
  - `MarketInfoFormatter` for presentation transformation
  - `EarningsFilterAnalyzer` for earnings filter logic
- **Where it should go:** `tomic/services/market_info_service.py`

#### Issue 2.3: Evaluation Overview Formatting (Lines 279-293)
```python
# Lines 279-293: _print_evaluation_overview - Mixed calculation and display
def _print_evaluation_overview(symbol: str, spot: float | None, summary: EvaluationSummary | None) -> None:
    if summary is None or summary.total <= 0:
        return
    sym = symbol.upper() if symbol else "—"
    if isinstance(spot, (int, float)) and spot > 0:
        header = f"Evaluatieoverzicht: {sym} @ {spot:.2f}"
    else:
        header = f"Evaluatieoverzicht: {sym}"
    print(header)
    print(f"Totaal combinaties: {summary.total}")
    if summary.expiries:
        print("Expiry breakdown:")
        for breakdown in summary.sorted_expiries():
            print(f"• {breakdown.label}: {breakdown.format_counts()}")
    print(f"Top reason for reject: {format_reject_reasons(summary)}")
```
- **Problems:**
  - Conditional formatting logic (spot > 0) in display
  - Calls to `format_reject_reasons()` for business data
- **Should be:** Just formatting-only function; all aggregations should be pre-computed

#### Issue 2.4: Proposal Export and Order Submission (Lines 414-451)
```python
# Lines 414-451: Mixed concerns - export + order submission + formatting
if prompt_yes_no("Voorstel opslaan naar CSV?", False):
    path = portfolio_services.export_proposal_to_csv(session, presentation.proposal)
    print(f"✅ Voorstel opgeslagen in: {path.resolve()}")
if prompt_yes_no("Voorstel opslaan naar JSON?", False):
    path = portfolio_services.export_proposal_to_json(session, presentation.proposal)
    print(f"✅ Voorstel opgeslagen in: {path.resolve()}")

can_send_order = not presentation.acceptance_failed and not presentation.fetch_only_mode
order_symbol = presentation.symbol or symbol or str(session.symbol or "")
if can_send_order and prompt_yes_no("Order naar IB sturen?", False):
    _submit_ib_order(session, presentation.proposal, symbol=order_symbol)
```
- **Problems:**
  - Multiple service calls in sequential display flow
  - Complex conditional logic for order submission decisions
  - Export operations interleaved with interactive prompts
- **Should be:** Separate service for proposal export/execution coordination

---

### 3. `/home/user/tomic/tomic/cli/iv_backfill_flow.py` (390 lines)

**EXTENSIVE DATA PROCESSING IN CLI**

#### Issue 3.1: Date Parsing Logic (Lines 74-97)
```python
# Lines 74-97: _parse_csv_date - Business date parsing logic in CLI
def _parse_csv_date(raw: str) -> str | None:
    """Parse ``raw`` naar ``YYYY-MM-DD`` indien mogelijk."""
    value = str(raw).strip()
    if not value:
        return None
    
    candidates = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%Y%m%d",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
```
- **What should be extracted:** `DateParser` class
- **Where it should go:** `tomic/helpers/date_parsing.py`
- **Why it matters:** Date parsing is reusable business logic, not CLI-specific

#### Issue 3.2: IV Percentage Parsing (Lines 100-104)
```python
# Lines 100-104: Data transformation embedded in CLI
def _parse_atm_iv(raw: Any) -> float | None:
    value = parse_euro_float(raw if isinstance(raw, str) else str(raw))
    if value is None:
        return None
    return value / 100.0  # ← Percentage conversion
```
- **What should be extracted:** `IVValueParser` class
- **Where it should go:** `tomic/helpers/iv_parsing.py`

#### Issue 3.3: CSV Parsing with Validation (Lines 107-145)
```python
# Lines 107-145: read_iv_csv - Complex parsing with validation
def read_iv_csv(path: Path) -> CsvParseResult:
    """Lees een CSV-bestand en geef ATM IV records terug."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = sorted(REQUIRED_COLUMNS - set(fieldnames))
        if missing:
            raise ValueError(f"Ontbrekende kolommen in CSV: {', '.join(missing)}")
        
        records_map: dict[str, dict[str, Any]] = {}
        duplicates: list[str] = []
        invalid_dates: list[str] = []
        empty_rows = 0
        
        for row in reader:
            date_raw = row.get("Date")
            iv_raw = row.get("IV30")
            if not (date_raw and str(iv_raw).strip()):
                empty_rows += 1
                continue
            
            parsed_date = _parse_csv_date(date_raw)
            if not parsed_date:
                invalid_dates.append(str(date_raw).strip())
                continue
            
            atm_iv = _parse_atm_iv(iv_raw)
            if atm_iv is None:
                empty_rows += 1
                continue
            
            record = {"date": parsed_date, "atm_iv": atm_iv}
            if parsed_date in records_map:
                duplicates.append(parsed_date)
            records_map[parsed_date] = record
    
    sorted_records = sorted(records_map.values(), key=lambda r: r["date"])
    return CsvParseResult(sorted_records, duplicates, invalid_dates, empty_rows)
```
- **What should be extracted:** `IVCsvParser` service class
- **Where it should go:** `tomic/services/iv_data_service.py`
- **Why it matters:** Cannot test CSV parsing without CLI invocation

#### Issue 3.4: Data Comparison/Gap Detection (Lines 148-194)
```python
# Lines 148-194: Multiple data analysis functions in CLI
def _build_preview_rows(symbol: str, csv_records: Sequence[dict[str, Any]], existing_map: dict[str, dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in csv_records:
        date = record["date"]
        new_iv = record.get("atm_iv")
        old_iv = existing_map.get(date, {}).get("atm_iv")
        status = "Nieuw" if date not in existing_map else "Update"
        diff = None
        if old_iv is not None and new_iv is not None:
            diff = new_iv - old_iv  # ← Calculation embedded
        
        rows.append([
            date,
            status,
            f"{old_iv:.4f}" if old_iv is not None else "-",
            f"{new_iv:.4f}" if new_iv is not None else "-",
            f"{diff:+.4f}" if diff is not None else "-",
        ])
    # ...
    return rows

def _collect_gaps(dates: Iterable[str]) -> list[tuple[str, str, int]]:
    """Gap analysis algorithm in CLI"""
    ordered = sorted({d for d in dates if d})
    if len(ordered) < 2:
        return []
    
    result: list[tuple[str, str, int]] = []
    previous = datetime.strptime(ordered[0], "%Y-%m-%d")
    for raw in ordered[1:]:
        current = datetime.strptime(raw, "%Y-%m-%d")
        delta = (current - previous).days - 1
        if delta > 0:
            result.append((previous.strftime("%Y-%m-%d"), raw, delta))
        previous = current
    return result
```
- **What should be extracted:**
  - `IVChangeAnalyzer` for preview building
  - `DateGapAnalyzer` for gap detection
- **Where it should go:** `tomic/analysis/iv_analysis.py`

#### Issue 3.5: Data Merging Logic (Lines 208-239)
```python
# Lines 208-239: _merge_records - Data merging algorithm in CLI
def _merge_records(target: Path, csv_records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], Path | None]:
    existing = load_json(target)
    if not isinstance(existing, list):
        existing = []
    
    merged: dict[str, dict[str, Any]] = {}
    for record in existing:
        if isinstance(record, dict) and "date" in record:
            merged[str(record["date"])] = dict(record)
    
    for record in csv_records:
        date = record["date"]
        base = merged.get(date, {})
        base.update(record)
        base["date"] = date
        merged[date] = base
    
    merged_list = sorted(merged.values(), key=lambda r: r.get("date", ""))
    
    backup_path: Path | None = None
    if target.exists():
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)
    
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"temp_{target.name}")
    dump_json(merged_list, tmp)
    tmp.replace(target)
    
    return merged_list, backup_path
```
- **What should be extracted:** `DataMergeService` with atomic write guarantees
- **Where it should go:** `tomic/services/data_merge_service.py`
- **Why it matters:** File operations and merging logic cannot be unit tested

#### Issue 3.6: Orchestration Mixing Multiple Concerns (Lines 242-380)
```python
# Lines 242-380: run_iv_backfill_flow - Master function mixing everything
def run_iv_backfill_flow() -> None:
    """Interactieve flow voor het backfillen van IV-data."""
    
    # User input
    symbol = prompt("Ticker symbool: ").strip().upper()
    if not symbol:
        print("❌ Geen symbool opgegeven")
        return
    
    csv_input = prompt("Pad naar CSV-bestand: ").strip()
    # ... more input validation ...
    
    # Data loading
    csv_path = Path(csv_input).expanduser()
    if not csv_path.exists():
        print(f"❌ CSV niet gevonden: {csv_path}")
        return
    
    # Parsing
    try:
        parsed = read_iv_csv(csv_path)
    except Exception as exc:
        logger.error(f"IV CSV parse-fout: {exc}")
        print(f"❌ CSV inlezen mislukt: {exc}")
        return
    
    # Data loading (supporting files)
    summary_file = summary_dir / f"{symbol}.json"
    existing_data = load_json(summary_file)
    existing_map: dict[str, dict[str, Any]] = {}
    if isinstance(existing_data, list):
        for record in existing_data:
            if isinstance(record, dict) and "date" in record:
                existing_map[str(record["date"])] = record
    
    # Data analysis
    csv_map = {record["date"]: record for record in parsed.records}
    csv_dates = set(csv_map)
    existing_dates = set(existing_map)
    new_dates = sorted(csv_dates - existing_dates)
    overlap_dates = sorted(csv_dates & existing_dates)
    
    updates: list[dict[str, Any]] = []
    unchanged = 0
    for date in overlap_dates:
        new_iv = csv_map[date]["atm_iv"]
        old_iv = existing_map.get(date, {}).get("atm_iv")
        if old_iv is None:
            updates.append({"date": date, "old": old_iv, "new": new_iv})
        else:
            if abs(new_iv - old_iv) > IV_THRESHOLD:  # ← Business threshold
                updates.append({"date": date, "old": old_iv, "new": new_iv})
            else:
                unchanged += 1
    
    # More data analysis
    hv_dir = Path(cfg.get("HV_DIR", "tomic/data/historical_volatility")).expanduser()
    hv_file = hv_dir / f"{symbol}.json"
    hv_map = _load_supporting(hv_file)
    
    spot_dir = Path(cfg.get("SPOT_DIR", "tomic/data/spot_prices")).expanduser()
    spot_file = spot_dir / f"{symbol}.json"
    spot_map = _load_supporting(spot_file)
    
    missing_hv = sorted(csv_dates - set(hv_map))
    missing_spot = sorted(csv_dates - set(spot_map))
    
    gaps = _collect_gaps(csv_dates)
    
    # Presentation
    preview_rows = _build_preview_rows(symbol, parsed.records, existing_map)
    headers = ["Datum", "Status", "ATM IV (oud)", "ATM IV (nieuw)", "Δ"]
    print("\nVoorbeeld wijzigingen:")
    print(tabulate(preview_rows, headers=headers, tablefmt="github"))
    
    # More presentation + business logic
    summary_rows = [
        ["Nieuwe dagen", len(new_dates)],
        ["Updates (>3%)", len(updates)],
        ["Overlap <=3%", unchanged],
        ["Dubbele rijen in CSV", len(parsed.duplicates)],
        ["Lege/ongeldige rijen", parsed.empty_rows + len(parsed.invalid_dates)],
        ["CSV-hiaten", len(gaps)],
        ["Ontbrekende HV-dagen", len(missing_hv)],
        ["Ontbrekende spot-dagen", len(missing_spot)],
    ]
    print("\nSamenvatting:")
    print(tabulate(summary_rows, headers=["Metriek", "Aantal"], tablefmt="github"))
    
    # Validation and user confirmation
    if parsed.duplicates:
        logger.warning(f"Dubbele datums gevonden in CSV voor {symbol}: {parsed.duplicates[:5]}")
    # ... more warnings ...
    
    if not (new_dates or updates):
        print("ℹ️ Geen nieuwe of gewijzigde dagen gevonden.")
        return
    
    if not prompt_yes_no("Wijzigingen toepassen? (nee = dry-run)"):
        print("Dry-run voltooid. Geen wijzigingen geschreven.")
        logger.info(f"Dry-run voor IV backfill {symbol} zonder wijzigingen")
        return
    
    # Data persistence
    merged_records, backup_path = _merge_records(summary_file, parsed.records)
    logger.success(f"IV backfill voltooid voor {symbol}: {len(parsed.records)} records verwerkt")
    print(f"✅ IV backfill opgeslagen naar {summary_file}...")
```
- **This function does EVERYTHING:**
  - User input collection
  - File I/O
  - Data parsing
  - Data validation
  - Data analysis
  - Aggregations
  - Comparison logic
  - Presentation
  - Persistence
- **Should be split into:**
  - `IVBackfillOrchestrator` service class
  - `IVBackfillInteractiveFlow` CLI wrapper
  - Multiple support services for data operations

---

### 4. `/home/user/tomic/tomic/cli/exit_flow.py` (351 lines)

**Mixing Display Logic with Business Decisions**

#### Issue 4.1: Complex Output Formatting with Business Logic (Lines 77-150)
```python
# Lines 77-150: _describe_ladder and _describe_fallback - Mix formatting with decisions
def _describe_ladder(intent: StrategyExitIntent, result: ExitFlowResult) -> list[str]:
    attempts = [attempt for attempt in result.attempts if attempt.stage == "primary" or attempt.stage.startswith("ladder:")]
    if not attempts:
        return []
    
    label = _intent_label(intent)
    prices = [attempt.limit_price for attempt in attempts if attempt.limit_price is not None]
    # ... complex formatting logic ...
    
    filled_attempt = next((attempt for attempt in attempts if attempt.order_ids), None)
    if filled_attempt is not None:
        status = "FILLED"
        final_price = _format_price(filled_attempt.limit_price)
        if final_price:
            status += f" @ {final_price}"
        status += _format_order_suffix(filled_attempt.order_ids)
    else:
        status = result.reason or "failed"
    
    steps_count = len(prices) if prices else len(attempts)
    sequence_part = f" @ {price_sequence}" if price_sequence else ""
    return [f"{label} | Ladder {steps_count} steps{sequence_part} {status}"]
```
- **Problem:** Output formatting directly depends on business state decisions
- **Should extract:** `ExitFlowResultFormatter` service
- **Why:** Cannot test display decisions without full exit flow execution

---

### 5. `/home/user/tomic/tomic/cli/portfolio/menu_flow.py` (695 lines)

**LARGEST ORCHESTRATION FILE - Mixed Business & Presentation**

#### Issue 5.1: Chain Processing Orchestration (Lines 113-252)
```python
# Lines 113-252: process_chain - Massive function mixing responsibilities
def process_chain(
    session: ControlPanelSession,
    services: ControlPanelServices,
    path: Path,
    show_reasons: bool,
    *,
    tabulate_fn: Callable[..., str],
    prompt_fn: PromptFn,
    prompt_yes_no_fn: PromptYesNoFn,
    show_proposal_details: ShowProposalDetailsFn,
    build_rejection_summary_fn: BuildRejectionSummaryFn,
    save_trades_fn: SaveTradesFn,
    refresh_spot_price_fn: RefreshSpotFn,
    load_spot_from_metrics_fn: LoadSpotFromMetricsFn,
    load_latest_close_fn: LoadLatestCloseFn,
    spot_from_chain_fn: SpotFromChainFn,
    print_evaluation_overview_fn: PrintEvaluationOverviewFn | None = None,
) -> bool:
    """Load, evaluate and interact with an option chain CSV."""
    
    # 1. Chain preparation
    prep_config = ChainPreparationConfig.from_app_config()
    try:
        prepared = load_and_prepare_chain(path, prep_config)
    except ChainPreparationError as exc:
        print(f"⚠️ {exc}")
        return show_reasons
    
    # 2. Quality checking
    if prepared.quality < prep_config.min_quality:
        print(f"⚠️ CSV kwaliteit {prepared.quality:.1f}%...")
    else:
        print(f"CSV kwaliteit {prepared.quality:.1f}%")
    
    # 3. User interaction
    if not prompt_yes_no_fn("Doorgaan?", False):
        return show_reasons
    
    # 4. Interpolation
    if prompt_yes_no_fn("Wil je delta/iv interpoleren?", False):
        try:
            prepared = load_and_prepare_chain(path, prep_config, apply_interpolation=True)
        except ChainPreparationError as exc:
            print(f"⚠️ {exc}")
            return show_reasons
        print("✅ Interpolatie toegepast op ontbrekende delta/iv.")
        print(f"Nieuwe CSV kwaliteit {prepared.quality:.1f}%")
    
    # 5. Spot price resolution (complex logic)
    symbol = str(session.symbol or "")
    spot_resolution = resolve_chain_spot_price(
        symbol,
        prepared,
        refresh_quote=refresh_spot_price_fn,
        load_metrics_spot=load_spot_from_metrics_fn,
        load_latest_close=load_latest_close_fn,
        chain_spot_fallback=spot_from_chain_fn,
    )
    if isinstance(spot_resolution, SpotResolution):
        spot_price = spot_resolution.price
    else:
        spot_price = spot_resolution
    
    if not isinstance(spot_price, (int, float)) or spot_price <= 0:
        spot_price = spot_from_chain_fn(prepared.records) or 0.0
    session.spot_price = spot_price
    
    # 6. Chain evaluation
    strategy_name = str(session.strategy or "").lower().replace(" ", "_")
    pipeline = services.get_pipeline()
    atr_val = latest_atr(symbol) or 0.0
    eval_config = ChainEvaluationConfig.from_app_config(
        symbol=symbol,
        strategy=strategy_name,
        spot_price=float(spot_price or 0.0),
        atr=atr_val,
    )
    
    evaluation = evaluate_chain(prepared, pipeline, eval_config)
    evaluation_summary = session.combo_evaluation_summary
    
    # 7. Presentation of evaluation
    if isinstance(evaluation_summary, EvaluationSummary) or evaluation_summary is None:
        if print_evaluation_overview_fn is None:
            _print_evaluation_overview(session, evaluation_summary)
        else:
            print_evaluation_overview_fn(...)
    
    # 8. Rejection summary (mixed presentation/logic)
    build_rejection_summary_fn(
        session,
        evaluation.filter_preview,
        services=services,
        config=cfg,
        show_reasons=show_reasons,
        tabulate_fn=tabulate_fn,
        prompt_fn=prompt_fn,
        prompt_yes_no_fn=prompt_yes_no_fn,
        show_proposal_details=show_proposal_details,
    )
    
    # 9. Evaluated trades
    evaluated = evaluation.evaluated_trades
    session.evaluated_trades = list(evaluated)
    session.spot_price = evaluation.context.spot_price
    
    # 10. Conditional flow
    if evaluated:
        show_reasons = show_evaluations(...)
    else:
        # ... more complex logic ...
    
    return show_reasons
```
- **This function has 8+ distinct responsibilities:**
  1. Chain preparation
  2. Quality validation
  3. User input handling
  4. Data interpolation
  5. Spot price resolution (with fallback logic)
  6. ATR loading
  7. Chain evaluation (core business logic)
  8. Presentation/rejection summary
- **Should be split into:**
  - `ChainProcessor` service (steps 1-4)
  - `SpotPriceResolver` service (step 5)
  - `ChainEvaluationOrchestrator` service (steps 6-8)
  - `ChainProcessingFlow` CLI wrapper

#### Issue 5.2: Evaluation Presentation (Lines 255-300+)
```python
# Lines 255+: show_evaluations - More mixed concerns
def show_evaluations(
    session: ControlPanelSession,
    evaluation: ChainEvaluationResult,
    services: ControlPanelServices,
    evaluated: Sequence[dict],
    atr_val: float,
    show_reasons: bool,
    *,
    tabulate_fn: Callable[..., str],
    prompt_fn: PromptFn,
    prompt_yes_no_fn: PromptYesNoFn,
    show_proposal_details: ShowProposalDetailsFn,
    build_rejection_summary_fn: BuildRejectionSummaryFn,
    save_trades_fn: SaveTradesFn,
    refresh_spot_price_fn: RefreshSpotFn,
    load_latest_close_fn: LoadLatestCloseFn,
) -> bool:
    """Present evaluated trades and optionally drill into proposals."""
    
    symbol = session.symbol or ""
    close_price, close_date = load_latest_close_fn(symbol)  # ← Data fetching in display
    if close_price is not None and close_date:
        print(f"Close {close_date}: {close_price}")
    if atr_val:
        print(f"ATR: {atr_val:.2f}")
    else:
        print("ATR: n.v.t.")
    
    trades_table = build_evaluated_trades_table(evaluated)
    _print_table(tabulate_fn, trades_table)
    
    if prompt_yes_no_fn("Opslaan naar CSV?", False):
        save_trades_fn(session, evaluated)  # ← Service call in display
    
    if prompt_yes_no_fn("Doorgaan naar strategie voorstellen?", False):
        show_reasons = True
        
        latest_spot = refresh_spot_price_fn(str(symbol))  # ← Data fetching
        if isinstance(latest_spot, (int, float)) and latest_spot > 0:
            session.spot_price = float(latest_spot)
            evaluation.context.spot_price = float(latest_spot)
        
        # ... rest of evaluation logic ...
```
- **Problem:** Data loading (`load_latest_close_fn`, `refresh_spot_price_fn`) mixed with user prompts

---

### 6. `/home/user/tomic/tomic/cli/rejections/handlers.py` (608 lines)

**Complex Mixed Concerns in Rejection Handling**

#### Issue 6.1: Rejection Detail Display with Data Extraction (Lines 112-200+)
```python
# Lines 112+: show_rejection_detail - Data loading + formatting
def show_rejection_detail(
    session: ControlPanelSession,
    entry: Mapping[str, Any],
    *,
    tabulate_fn: _Tabulate | None = None,
    prompt_fn: PromptFn = prompt,
    show_proposal_details: ShowProposalDetailsFn | None = None,
) -> None:
    """Pretty-print details for a single rejection entry."""
    
    tabulate_fn = _ensure_tabulate(tabulate_fn)
    
    # Data extraction from entry
    strategy = entry.get("strategy") or "—"
    status = entry.get("status") or "—"
    anchor = entry.get("description") or "—"
    reason_value = entry.get("reason")
    raw_reason = entry.get("raw_reason")
    detail = normalize_reason(reason_value or raw_reason)  # ← Business logic
    reason_label_text = detail.message or ReasonAggregator.label_for(detail.category)
    # ... more complex extraction ...
    
    metrics = entry.get("metrics") or {}
    if metrics:
        metric_rows = [[key, metrics[key]] for key in sorted(metrics)]
        print("Metrics:")
        print(tabulate_fn(metric_rows, headers=["Metric", "Waarde"], tablefmt="github"))
```
- **Problem:** Complex data normalization logic mixed with formatting

#### Issue 6.2: Rejection Refresh with Service Calls (Lines 266+)
```python
# Lines 266+: refresh_rejections - Multiple service interactions
def refresh_rejections(
    session: ControlPanelSession,
    services: ControlPanelServices,
    entries: Sequence[Mapping[str, Any]],
    **kwargs
) -> None:
    # ... complex logic with refresh_pipeline calls ...
```
- **Problem:** Orchestrates multiple services while managing CLI state

#### Issue 6.3: Build Rejection Summary (Lines 480+)
```python
# Lines 480+: build_rejection_summary - Aggregation + Presentation
def build_rejection_summary(
    session: ControlPanelSession,
    summary: RejectionSummary | None,
    *,
    services: ControlPanelServices | None = None,
    config: Any | None = None,
    show_reasons: bool = False,
    **kwargs
) -> None:
    # ... builds table, manages session state, handles user interaction ...
```
- **Problem:** Mixes aggregation logic with session management

---

## Summary Table

| File | Size | Issues | Severity |
|------|------|--------|----------|
| `controlpanel/portfolio_ui.py` | 888 | 4 major | CRITICAL |
| `portfolio/menu_flow.py` | 695 | 3 major | CRITICAL |
| `rejections/handlers.py` | 608 | 3 major | HIGH |
| `strategy_dashboard.py` | 547 | 7 major | CRITICAL |
| `controlpanel/__init__.py` | 535 | Multiple proxy concerns | HIGH |
| `iv_backfill_flow.py` | 390 | 6 major | CRITICAL |
| `exit_flow.py` | 351 | 2 major | HIGH |

**TOTAL: 40+ instances of mixed concerns across 7 critical files**

---

## Refactoring Recommendations

### Phase 1: Extract High-Impact Services (Highest ROI)

1. **Create `tomic/services/metrics_calculation.py`**
   - `calculate_rom(pnl, margin) -> float`
   - `calculate_theta_efficiency(theta, margin) -> float`
   - `calculate_spot_change_percent(current, open) -> float`
   - `calculate_avg_contract_price(cost_basis, legs) -> float`

2. **Create `tomic/services/portfolio_aggregation.py`**
   - `PortfolioAggregator` class
   - Methods: aggregate_deltas, aggregate_vega, aggregate_dte, etc.

3. **Create `tomic/services/proposal_service.py`**
   - `ProposalRefreshService` for IB data fetching
   - `ProposalExportService` for CSV/JSON export
   - `ProposalOrderService` for order submission

### Phase 2: Extract Data Processing Services

4. **Create `tomic/services/iv_data_service.py`**
   - `IVCsvParser` for CSV parsing
   - `IVDataMerger` for merging logic
   - `IVChangeAnalyzer` for comparison

5. **Create `tomic/services/date_service.py`**
   - `DateParser` for flexible date parsing
   - `DateGapAnalyzer` for gap detection

### Phase 3: Refactor Large CLI Files

6. **Refactor `strategy_dashboard.py`**
   - Extract all calculations to services
   - Keep only printing logic

7. **Refactor `controlpanel/portfolio_ui.py`**
   - Move data fetching to services
   - Split presentation functions

8. **Refactor `portfolio/menu_flow.py`**
   - Create `ChainProcessingOrchestrator` service
   - Split chain processing from presentation

---

## Testing Impact

**Current state:** Business logic cannot be unit tested independently because it's embedded in CLI/presentation code.

**After refactoring:** All business logic can be tested without CLI invocation:

```python
# Example: Test metrics calculation
from tomic.services.metrics_calculation import calculate_rom

def test_calculate_rom():
    result = calculate_rom(pnl=100, margin=1000)
    assert result == 10.0  # 10% ROM
```

---
