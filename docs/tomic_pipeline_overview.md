# TOMIC strategy pipeline — architecture & pricing flow

This document summarises the current end-to-end implementation so that future
changes can be planned with a clear picture of the existing behaviour. It also
records how the pipeline differentiates between high- and lower-quality mid
prices (`true`, `parity_true`, `parity_close`, `model`, `close`) now that parity
can be reconstructed from the counterpart’s last close.

## 1. Architecture and data flow

```
User/CLI → select symbol & strategy
  └─ `tomic/cli/controlpanel.py` → `_get_strategy_pipeline()`
      └─ `StrategyPipeline.build_proposals()` orchestrates the scan
          1. Load strike rules via `load_strike_config()`
          2. Configure `StrikeSelector`
          3. Build `MidResolver` and enrich the option chain
          4. Filter strikes (`selector.select()`)
          5. Evaluate mids & metrics per leg (`_evaluate_leg`)
          6. Generate combos (`generate_strategy_candidates`)
          7. Score proposals & aggregate rejects
```

* **Symbol & strategy selection.** In interactive mode the CLI reads the CSV
  export and prompts for the symbol/strategy; see
  `tomic/cli/controlpanel.py::scan_market_csv()` where the context is built and
  handed to the pipeline.【F:tomic/cli/controlpanel.py†L1420-L1467】
* **Configuration sources.** Global config is loaded once in
  `tomic/config.py::load_config()` and exposed via `config.get()` (reads
  `config.yaml` by default, overrideable by `TOMIC_CONFIG`). Relevant keys:
  `MID_RESOLVER` (spread thresholds, `max_fallback_per_4_leg`),
  `MID_FALLBACK_MAX_PER_4`, spot/interest rate defaults, and strategy overrides
  under `STRATEGY_CONFIG`. Strike & strategy thresholds (delta bands, liquidity
  rules, min risk/reward, etc.) live in `criteria.yaml` parsed by
  `tomic/criteria.py::load_rules()`.
* **Option-chain ingest.** The CLI pulls option CSV data and spot snapshots, and
  applies an expiry range from strategy rules before invoking the pipeline.
  Counts before/after the DTE filter are logged for traceability.【F:tomic/cli/controlpanel.py†L1435-L1453】
* **Strike selection.** `StrategyPipeline` creates a `FilterConfig` from the
  loaded rules and passes the enriched chain to `StrikeSelector.select()`.
* **Mid resolution.** `build_mid_resolver()` instantiates `MidResolver`, which
  enriches every quote with pricing metadata (`mid`, `mid_source`, etc.) before
  filtering or scoring occurs.【F:tomic/services/strategy_pipeline.py†L44-L111】【F:tomic/mid_resolver.py†L50-L118】
* **Policy/gating.** After strike filtering, strategy candidate generation runs
  and legs are evaluated (adding `edge`, `rom`, `ev`, etc.). Pricing fallbacks,
  liquidity limits, margin checks and risk/reward gates are enforced inside
  `tomic/analysis/scoring.py::calculate_score()` and helpers.【F:tomic/services/strategy_pipeline.py†L112-L199】【F:tomic/analysis/scoring.py†L320-L420】
* **Reject aggregation.** `StrategyPipeline` keeps `last_selected`/`last_evaluated`
  plus rejection counts so the CLI can display `n strikes selected out of m`
  alongside grouped reject reasons. The `ReasonAggregator` in the CLI maps raw
  strings to `ReasonCategory` enums from `tomic/strategy/reasons.py` for
  reporting.

## 2. Strike selection specifics

* **Location.** `tomic/strike_selector.py::StrikeSelector.select()` is the entry
  point; it is constructed with a `FilterConfig` derived from `criteria` or
  strategy rules.
* **Inputs.** Each option dict is expected to carry spot reference data (`spot`
  / `underlying_price`), greeks, `rom`, `edge`, `ev`, and `delta`. Expiries are
  filtered via `filter_by_expiry()` which wraps `helpers.dateutils.filter_by_dte`.
* **Filters.** The selector evaluates eight filters in order: delta, ROM, edge,
  PoS, EV, skew, term structure and greek caps (`gamma`, `vega`, `theta`). The
  numeric thresholds come from the `FilterConfig` (ultimately `criteria.yaml`).
  Example snippets:

  ```python
  for name, func in self._filters:
      ok, reason = func(option)
      if not ok:
          return False, f"{name}: {reason}"
  ```
  【F:tomic/strike_selector.py†L82-L117】

  ```python
  if delta < self.config.delta_min or delta > self.config.delta_max:
      return False, f"delta {delta:+.2f} outside {self.config.delta_min}..{self.config.delta_max}"
  ```
  【F:tomic/strike_selector.py†L123-L140】

* **Logging.** The selector logs the starting option count, expiries kept after
  the DTE filter and the number of contracts rejected per filter bucket; if no
  contracts survive it emits a `[FILTER]` summary with the active thresholds.【F:tomic/strike_selector.py†L98-L157】

## 3. MidResolver — pricing resolution order & metadata

* **Location.** `tomic/mid_resolver.py::MidResolver` with helper dataclass
  `MidResolution`.
* **Processing order.** `MidResolver._resolve_all()` walks the chain multiple
  times, short-circuiting once a `mid` is set:

  ```python
  for idx, option in enumerate(self._raw_chain):
      self._try_true_mid(idx, option)
  for idx, option in enumerate(self._raw_chain):
      if self._resolutions[idx].mid is None:
          self._try_parity(idx, option)
  # → model → close → mark unresolved legs as missing
  ```
  【F:tomic/mid_resolver.py†L128-L148】

* **True quotes.** `_try_true_mid` requires positive bid/ask and rejects zero or
  negative spreads. Spread quality is validated against a relative (`MID_SPREAD_RELATIVE`)
  and bucketed absolute threshold (`MID_SPREAD_ABSOLUTE`) sourced from global
  config or `MID_RESOLVER.spread_thresholds`. Legs marked `too_wide`, `invalid`,
  `missing`, or `one_sided` carry that in `spread_flag` & `mid_reason` metadata.【F:tomic/mid_resolver.py†L150-L194】【F:tomic/config.py†L25-L87】
* **Parity fallback.** `_try_parity` looks up the opposing leg via strike/expiry
  key, reuses the counterpart’s resolved mid when available, and otherwise falls
  back to its last close before applying discounted put–call parity using the
  pipeline’s `spot_price` and `interest_rate`. Metadata distinguishes between
  `mid_source="parity_true"` (counterpart backed by true data) and
  `mid_source="parity_close"` (counterpart inferred from a close/model source).
  Counterpart lookup and DTE extraction are handled by `_find_counterpart()` and
  `_extract_dte()` respectively.【F:tomic/mid_resolver.py†L200-L247】【F:tomic/mid_resolver.py†L286-L332】
* **Model fallback.** `_try_model` first consumes any provider-supplied
  `modelprice`; otherwise it calls `_black_scholes()` with the leg’s IV and the
  same `spot`/`rate` inputs. Missing IV or spot prevents this stage.【F:tomic/mid_resolver.py†L249-L276】【F:tomic/mid_resolver.py†L306-L332】
* **Close fallback.** `_try_close` copies the last traded close from the quote if
  no other source succeeded, marking `mid_source="close"` and `mid_fallback="close"`.
* **Metadata surface.** Each leg is enriched with the following keys (all
  optional): `mid`, `mid_source`, `mid_reason`, `spread_flag`, `quote_age_sec`,
  `one_sided`, and `mid_fallback`. The resolver now surfaces the provenance of
  parity legs explicitly (`parity_true` vs `parity_close`) so downstream reports
  can flag preview-quality pricing. Legs reconstructed via parity also receive
  `mid_from_parity=True` when the enriched chain is consumed later.【F:tomic/mid_resolver.py†L20-L117】
* **Integration point.** `StrategyPipeline._evaluate_leg()` merges
  `resolution.as_dict()` into each leg before normalising, ensuring downstream
  scoring sees the pricing provenance.【F:tomic/services/strategy_pipeline.py†L148-L189】
* **True-pricing classification.** Downstream logic differentiates between
  `parity_true` (counted alongside real quotes) and preview sources
  (`parity_close`, `model`, `close`). Proposal summaries keep separate counters
  for each category so the CLI, logs and exports can surface where lower-quality
  data was used. Fallback limits only consider `parity_close`, `model` and
  `close` as fallbacks.【F:tomic/services/strategy_pipeline.py†L190-L223】【F:tomic/analysis/scoring.py†L27-L113】

## 4. Gating, policies & rejection handling

* **Short-leg requirements & fallback limits.** `_fallback_limit_ok()` in
  `tomic/analysis/scoring.py` still enforces per-strategy limits, but short legs
  may now proceed with preview mids (`parity_close`, `model`, `close`) as long as
  the total number of fallbacks stays within `MID_FALLBACK_MAX_PER_4` (capped per
  strategy: 2 for condors, 1 for short spreads/calendars). The scorer logs the
  degraded sources and attaches warnings such as "model-mid gebruikt" or
  "parity via close gebruikt" so preview-quality proposals are instantly
  recognisable.【F:tomic/analysis/scoring.py†L27-L121】【F:tomic/analysis/scoring.py†L256-L317】

* **Spread limits & quote quality.** Mid spread validation happens at resolution
  time (`_spread_ok`), tagging legs with `spread_flag="too_wide"` when the
  relative/absolute limits are breached so later stages can reject or display
  them.【F:tomic/mid_resolver.py†L266-L305】
* **Liquidity & metrics gating.** `validate_leg_metrics()` requires `mid`,
  `model` and `delta` for every leg unless strategy config enables
  `allow_unpriced_wings`. `check_liquidity()` enforces minimum volume/OI from
  `criteria.yaml`. Both feed into `calculate_score()` before any scoring occurs.【F:tomic/analysis/scoring.py†L180-L233】
* **Risk/reward checks.** `calculate_score()` also verifies credit-positive
  strategies, computes margin, ROM, EV and compares risk/reward against strategy
  thresholds. `passes_risk()` re-checks `max_profit / |max_loss|` against
  strategy-specific minimums before the CLI presents a proposal.【F:tomic/analysis/scoring.py†L320-L420】
* **Rejection reasons.** When a combination is rejected, reasons are collected at
  each stage:
  * Strike filtering logs per-filter reasons via `StrikeSelector`.
  * Strategy generation returns textual reasons per candidate.
  * Scoring functions append descriptive strings (e.g. "negatieve EV of score",
    "onvoldoende volume/open interest").

  These strings are normalised to categories using
  `tomic/strategy/reasons.py::normalize_reason()`, letting the CLI summarise
  counts per filter (`by_filter`), per raw reason (`by_reason`) and per strategy
  (`by_strategy`).【F:tomic/cli/controlpanel.py†L56-L115】【F:tomic/strategy/reasons.py†L1-L105】

---

With this overview you can rely on the resolver’s richer provenance data to
interpret strategy scores. Short legs priced from `parity_close`, `model` or
`close` remain eligible for scoring, but the CLI, logs and exports now surface
preview-quality warnings and per-source counters so users can judge the
reliability of proposed strategies when markets are closed or illiquid.
