"""Export module for external validation of backtest logic.

This module generates a complete export package that allows an external party
to validate and reproduce the backtest logic, including:
- All configuration parameters
- IV data with calculated percentiles
- Spot price data
- Daily evaluation decisions
- Trade details with P&L breakdown
- Calculation formulas documentation
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.backtest.config import BacktestConfig
from tomic.backtest.data_loader import DataLoader
from tomic.backtest.engine import BacktestEngine
from tomic.backtest.results import (
    BacktestResult,
    ExitReason,
    IVDataPoint,
    SimulatedTrade,
)
from tomic.backtest.signal_generator import SignalGenerator
from tomic.config import _load_yaml, _BASE_DIR
from tomic.logutils import logger


@dataclass
class DailyEvaluation:
    """Daily evaluation record for a symbol."""

    date: str
    symbol: str
    atm_iv: Optional[float]
    iv_percentile: Optional[float]
    iv_rank: Optional[float]
    hv30: Optional[float]
    skew: Optional[float]
    term_m1_m2: Optional[float]
    spot_price: Optional[float]
    # Criteria evaluation
    iv_percentile_min_required: float
    iv_percentile_passed: bool
    has_open_position: bool
    entry_signal_generated: bool
    reason_no_entry: Optional[str]


@dataclass
class TradeDailySnapshot:
    """Daily snapshot of a trade's state."""

    trade_id: int
    date: str
    days_in_trade: int
    iv_current: Optional[float]
    iv_change_from_entry: Optional[float]
    spot_current: Optional[float]
    estimated_pnl: float
    pnl_pct_of_max_risk: float
    # Exit criteria evaluation
    profit_target_level: float
    stop_loss_level: float
    profit_target_triggered: bool
    stop_loss_triggered: bool
    dte_remaining: int
    min_dte_triggered: bool
    exit_triggered: bool
    exit_reason: Optional[str]


class ExternalValidationExporter:
    """Handles export of all data needed for external validation."""

    def __init__(self, symbol: str, output_dir: Path):
        self.symbol = symbol
        self.output_dir = output_dir
        self.config: Optional[BacktestConfig] = None
        self.live_config: Dict[str, Any] = {}
        self.data_loader: Optional[DataLoader] = None
        self.backtest_result: Optional[BacktestResult] = None
        self.daily_evaluations: List[DailyEvaluation] = []
        self.trade_snapshots: List[TradeDailySnapshot] = []

    def run_export(self, include_all_data: bool = True) -> Path:
        """Run the complete export process.

        Args:
            include_all_data: If True, exports everything. If False, only essentials.

        Returns:
            Path to the export directory.
        """
        # Create export directory
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        export_path = self.output_dir / f"external_validation_{self.symbol}_{timestamp}"
        export_path.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self._load_configuration()

        # Run backtest and collect detailed data
        self._run_backtest_with_logging()

        # Export all components
        self._export_config(export_path / "config")
        self._export_iv_data(export_path / "input_data")
        self._export_spot_data(export_path / "input_data")
        self._export_daily_evaluations(export_path / "evaluation")
        self._export_trade_details(export_path / "trades")
        self._export_formulas(export_path / "formulas")
        self._export_readme(export_path)

        return export_path

    def _load_configuration(self) -> None:
        """Load all configuration from YAML files."""
        # Import here to avoid circular import
        from tomic.cli.strategy_testing_ui import load_live_config
        self.live_config = load_live_config()

        # Load backtest config
        backtest_yaml = _BASE_DIR / "config" / "backtest.yaml"
        if backtest_yaml.exists():
            config_data = _load_yaml(backtest_yaml)
            # Filter to single symbol
            config_data["symbols"] = [self.symbol]
            self.config = BacktestConfig.from_dict(config_data)

    def _run_backtest_with_logging(self) -> None:
        """Run backtest while collecting detailed evaluation data."""
        if not self.config:
            raise ValueError("Configuration not loaded")

        # Initialize components
        self.data_loader = DataLoader(self.config)
        self.data_loader.load_all()

        # Get IV data for the symbol
        iv_ts = self.data_loader.get_iv_data(self.symbol)
        if not iv_ts:
            raise ValueError(f"No IV data available for {self.symbol}")

        # Run actual backtest FIRST so we know when trades are open/closed
        engine = BacktestEngine(self.config)
        self.backtest_result = engine.run()

        # Now collect daily evaluations with knowledge of actual trades
        self._collect_daily_evaluations(iv_ts)

        # Collect trade snapshots from result
        self._collect_trade_snapshots()

    def _collect_daily_evaluations(self, iv_ts) -> None:
        """Collect daily entry evaluation data."""
        iv_pct_min = self.config.entry_rules.iv_percentile_min or 0.0

        # Build a set of dates when position was open based on actual trades
        open_dates: set = set()
        entry_dates: set = set()
        if self.backtest_result:
            for trade in self.backtest_result.trades:
                if trade.symbol != self.symbol:
                    continue
                entry_dates.add(trade.entry_date)
                # Add all dates from entry to exit (exclusive of exit date)
                if trade.exit_date:
                    from datetime import timedelta
                    current = trade.entry_date
                    while current < trade.exit_date:
                        open_dates.add(current)
                        current += timedelta(days=1)

        # Get spot prices once
        spot_prices = self.data_loader.load_spot_prices(self.symbol)

        for dp in iv_ts:
            has_open = dp.date in open_dates
            was_entry_date = dp.date in entry_dates

            # Determine if entry criteria passed
            iv_pct_passed = (
                dp.iv_percentile is not None and dp.iv_percentile >= iv_pct_min
            )

            # Determine reason for no entry
            reason = None
            entry_generated = was_entry_date  # Use actual entry from backtest

            if was_entry_date:
                reason = None  # Entry was generated
            elif has_open:
                reason = "position_already_open"
            elif dp.iv_percentile is None:
                reason = "iv_percentile_not_available"
            elif not iv_pct_passed:
                reason = f"iv_percentile_{dp.iv_percentile:.1f}_below_min_{iv_pct_min}"
            else:
                # Criteria passed but no entry - could be max positions or other rule
                reason = "criteria_passed_but_no_entry_other_constraint"

            spot = spot_prices.get(dp.date)

            eval_record = DailyEvaluation(
                date=str(dp.date),
                symbol=self.symbol,
                atm_iv=dp.atm_iv,
                iv_percentile=dp.iv_percentile,
                iv_rank=dp.iv_rank,
                hv30=dp.hv30,
                skew=dp.skew,
                term_m1_m2=dp.term_m1_m2,
                spot_price=spot,
                iv_percentile_min_required=iv_pct_min,
                iv_percentile_passed=iv_pct_passed,
                has_open_position=has_open,
                entry_signal_generated=entry_generated,
                reason_no_entry=reason,
            )
            self.daily_evaluations.append(eval_record)

    def _collect_trade_snapshots(self) -> None:
        """Collect daily snapshots for each trade."""
        if not self.backtest_result:
            return

        profit_target_pct = self.config.exit_rules.profit_target_pct
        stop_loss_pct = self.config.exit_rules.stop_loss_pct
        min_dte = self.config.exit_rules.min_dte

        for idx, trade in enumerate(self.backtest_result.trades):
            if trade.symbol != self.symbol:
                continue

            # Create snapshots from trade history
            for day_idx, pnl in enumerate(trade.pnl_history):
                iv_current = (
                    trade.iv_history[day_idx]
                    if day_idx < len(trade.iv_history)
                    else None
                )
                spot_current = (
                    trade.spot_history[day_idx]
                    if day_idx < len(trade.spot_history)
                    else None
                )

                iv_change = None
                if iv_current is not None:
                    iv_change = iv_current - trade.iv_at_entry

                pnl_pct = (pnl / trade.max_risk) * 100 if trade.max_risk else 0

                # Calculate DTE remaining
                dte_at_entry = (trade.target_expiry - trade.entry_date).days
                dte_remaining = max(0, dte_at_entry - day_idx)

                # Check exit triggers
                profit_target_triggered = pnl_pct >= profit_target_pct
                stop_loss_triggered = pnl_pct <= -stop_loss_pct
                min_dte_triggered = dte_remaining <= min_dte

                exit_triggered = (
                    profit_target_triggered or stop_loss_triggered or min_dte_triggered
                )
                exit_reason = None
                if profit_target_triggered:
                    exit_reason = "profit_target"
                elif stop_loss_triggered:
                    exit_reason = "stop_loss"
                elif min_dte_triggered:
                    exit_reason = "min_dte"

                # Calculate trade date
                from datetime import timedelta

                trade_date = trade.entry_date + timedelta(days=day_idx)

                snapshot = TradeDailySnapshot(
                    trade_id=idx,
                    date=str(trade_date),
                    days_in_trade=day_idx,
                    iv_current=iv_current,
                    iv_change_from_entry=iv_change,
                    spot_current=spot_current,
                    estimated_pnl=pnl,
                    pnl_pct_of_max_risk=pnl_pct,
                    profit_target_level=profit_target_pct,
                    stop_loss_level=stop_loss_pct,
                    profit_target_triggered=profit_target_triggered,
                    stop_loss_triggered=stop_loss_triggered,
                    dte_remaining=dte_remaining,
                    min_dte_triggered=min_dte_triggered,
                    exit_triggered=exit_triggered,
                    exit_reason=exit_reason,
                )
                self.trade_snapshots.append(snapshot)

    def _export_config(self, config_dir: Path) -> None:
        """Export all configuration to JSON."""
        config_dir.mkdir(parents=True, exist_ok=True)

        # Bundle all config
        config_bundle = {
            "export_metadata": {
                "symbol": self.symbol,
                "export_date": datetime.now().isoformat(),
                "backtest_period": {
                    "start": self.config.start_date,
                    "end": self.config.end_date,
                },
            },
            "backtest_config": {
                "strategy_type": self.config.strategy_type,
                "target_dte": self.config.target_dte,
                "iron_condor_wing_width": self.config.iron_condor_wing_width,
                "iron_condor_short_delta": self.config.iron_condor_short_delta,
            },
            "entry_rules": {
                "iv_percentile_min": self.config.entry_rules.iv_percentile_min,
                "iv_rank_min": self.config.entry_rules.iv_rank_min,
                "skew_min": self.config.entry_rules.skew_min,
                "skew_max": self.config.entry_rules.skew_max,
                "term_structure_min": self.config.entry_rules.term_structure_min,
                "term_structure_max": self.config.entry_rules.term_structure_max,
                "iv_hv_spread_min": self.config.entry_rules.iv_hv_spread_min,
            },
            "exit_rules": {
                "profit_target_pct": self.config.exit_rules.profit_target_pct,
                "stop_loss_pct": self.config.exit_rules.stop_loss_pct,
                "min_dte": self.config.exit_rules.min_dte,
                "max_days_in_trade": self.config.exit_rules.max_days_in_trade,
                "iv_collapse_threshold": self.config.exit_rules.iv_collapse_threshold,
                "delta_breach_threshold": self.config.exit_rules.delta_breach_threshold,
            },
            "position_sizing": {
                "type": self.config.position_sizing.type,
                "max_risk_per_trade": self.config.position_sizing.max_risk_per_trade,
                "max_positions_per_symbol": self.config.position_sizing.max_positions_per_symbol,
                "max_total_positions": self.config.position_sizing.max_total_positions,
            },
            "costs": {
                "commission_per_contract": self.config.costs.commission_per_contract,
                "slippage_pct": self.config.costs.slippage_pct,
            },
            "sample_split": {
                "in_sample_ratio": self.config.sample_split.in_sample_ratio,
                "method": self.config.sample_split.method,
            },
            "live_config_snapshot": self.live_config,
        }

        with open(config_dir / "all_config.json", "w", encoding="utf-8") as f:
            json.dump(config_bundle, f, indent=2, default=str)

        logger.info(f"Config exported to {config_dir / 'all_config.json'}")

    def _export_iv_data(self, data_dir: Path) -> None:
        """Export IV data with calculated percentiles to CSV."""
        data_dir.mkdir(parents=True, exist_ok=True)

        iv_ts = self.data_loader.get_iv_data(self.symbol)
        if not iv_ts:
            return

        csv_path = data_dir / f"{self.symbol}_iv_with_percentile.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "date",
                    "symbol",
                    "atm_iv",
                    "iv_percentile_calculated",
                    "iv_rank_calculated",
                    "hv30",
                    "skew",
                    "term_m1_m2",
                    "term_m1_m3",
                ]
            )

            for dp in iv_ts:
                writer.writerow(
                    [
                        dp.date,
                        dp.symbol,
                        dp.atm_iv,
                        dp.iv_percentile,
                        dp.iv_rank,
                        dp.hv30,
                        dp.skew,
                        dp.term_m1_m2,
                        dp.term_m1_m3,
                    ]
                )

        logger.info(f"IV data exported to {csv_path}")

    def _export_spot_data(self, data_dir: Path) -> None:
        """Export spot price data to CSV."""
        data_dir.mkdir(parents=True, exist_ok=True)

        spot_prices = self.data_loader.load_spot_prices(self.symbol)
        if not spot_prices:
            return

        csv_path = data_dir / f"{self.symbol}_spot.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "symbol", "close_price"])

            for dt, price in sorted(spot_prices.items()):
                writer.writerow([dt, self.symbol, price])

        logger.info(f"Spot data exported to {csv_path}")

    def _export_daily_evaluations(self, eval_dir: Path) -> None:
        """Export daily evaluation log to CSV."""
        eval_dir.mkdir(parents=True, exist_ok=True)

        csv_path = eval_dir / f"{self.symbol}_daily_decisions.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "date",
                    "symbol",
                    "atm_iv",
                    "iv_percentile",
                    "iv_rank",
                    "hv30",
                    "skew",
                    "term_m1_m2",
                    "spot_price",
                    "iv_percentile_min_required",
                    "iv_percentile_passed",
                    "has_open_position",
                    "entry_signal_generated",
                    "reason_no_entry",
                ]
            )

            for ev in self.daily_evaluations:
                writer.writerow(
                    [
                        ev.date,
                        ev.symbol,
                        ev.atm_iv,
                        ev.iv_percentile,
                        ev.iv_rank,
                        ev.hv30,
                        ev.skew,
                        ev.term_m1_m2,
                        ev.spot_price,
                        ev.iv_percentile_min_required,
                        ev.iv_percentile_passed,
                        ev.has_open_position,
                        ev.entry_signal_generated,
                        ev.reason_no_entry,
                    ]
                )

        logger.info(f"Daily evaluations exported to {csv_path}")

    def _export_trade_details(self, trades_dir: Path) -> None:
        """Export trade details with daily P&L breakdown."""
        trades_dir.mkdir(parents=True, exist_ok=True)

        if not self.backtest_result:
            return

        # Export trade summary
        summary_path = trades_dir / f"{self.symbol}_trades_summary.csv"
        with open(summary_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "trade_id",
                    "entry_date",
                    "exit_date",
                    "symbol",
                    "strategy_type",
                    "iv_at_entry",
                    "iv_percentile_at_entry",
                    "iv_at_exit",
                    "spot_at_entry",
                    "spot_at_exit",
                    "max_risk",
                    "estimated_credit",
                    "final_pnl",
                    "pnl_pct",
                    "days_in_trade",
                    "exit_reason",
                    "status",
                ]
            )

            for idx, trade in enumerate(self.backtest_result.trades):
                if trade.symbol != self.symbol:
                    continue

                pnl_pct = (
                    (trade.final_pnl / trade.max_risk) * 100 if trade.max_risk else 0
                )
                writer.writerow(
                    [
                        idx,
                        trade.entry_date,
                        trade.exit_date,
                        trade.symbol,
                        trade.strategy_type,
                        trade.iv_at_entry,
                        trade.iv_percentile_at_entry,
                        trade.iv_at_exit,
                        trade.spot_at_entry,
                        trade.spot_at_exit,
                        trade.max_risk,
                        trade.estimated_credit,
                        trade.final_pnl,
                        pnl_pct,
                        trade.days_in_trade,
                        trade.exit_reason.value if trade.exit_reason else None,
                        trade.status.value,
                    ]
                )

        # Export daily snapshots
        if self.trade_snapshots:
            snapshots_path = trades_dir / f"{self.symbol}_trades_daily_snapshots.csv"
            with open(snapshots_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "trade_id",
                        "date",
                        "days_in_trade",
                        "iv_current",
                        "iv_change_from_entry",
                        "spot_current",
                        "estimated_pnl",
                        "pnl_pct_of_max_risk",
                        "profit_target_level",
                        "stop_loss_level",
                        "profit_target_triggered",
                        "stop_loss_triggered",
                        "dte_remaining",
                        "min_dte_triggered",
                        "exit_triggered",
                        "exit_reason",
                    ]
                )

                for snap in self.trade_snapshots:
                    writer.writerow(
                        [
                            snap.trade_id,
                            snap.date,
                            snap.days_in_trade,
                            snap.iv_current,
                            snap.iv_change_from_entry,
                            snap.spot_current,
                            snap.estimated_pnl,
                            snap.pnl_pct_of_max_risk,
                            snap.profit_target_level,
                            snap.stop_loss_level,
                            snap.profit_target_triggered,
                            snap.stop_loss_triggered,
                            snap.dte_remaining,
                            snap.min_dte_triggered,
                            snap.exit_triggered,
                            snap.exit_reason,
                        ]
                    )

        logger.info(f"Trade details exported to {trades_dir}")

    def _export_formulas(self, formulas_dir: Path) -> None:
        """Export calculation formulas documentation."""
        formulas_dir.mkdir(parents=True, exist_ok=True)

        formulas_md = """# Calculation Formulas

## 1. IV Percentile Calculation

The IV percentile is calculated using a **252-day rolling window** (1 trading year).

```
iv_percentile = (count of days where IV < current_IV) / (total days in lookback) * 100
```

### Implementation Details:
- Lookback window: 252 trading days
- Minimum data points required: 20 (for statistical significance)
- Formula: `percentile = (below_count / total_count) * 100`

### Python Code Reference (data_loader.py:222-243):
```python
LOOKBACK_DAYS = 252

lookback_ivs = [
    iv for d, iv in iv_history[:i+1]
    if (dt - d).days <= LOOKBACK_DAYS and (dt - d).days >= 0
]

if len(lookback_ivs) >= 20:
    current_iv = dp.atm_iv
    below_count = sum(1 for iv in lookback_ivs if iv < current_iv)
    iv_percentile = (below_count / len(lookback_ivs)) * 100
```

## 2. IV Rank Calculation

IV Rank shows where current IV sits relative to 252-day high/low.

```
iv_rank = (current_IV - min_IV) / (max_IV - min_IV) * 100
```

### Python Code Reference (data_loader.py:246-250):
```python
min_iv = min(lookback_ivs)
max_iv = max(lookback_ivs)
if max_iv > min_iv:
    iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100
```

## 3. P&L Estimation Model

Since we don't have historical bid/ask data, P&L is estimated using an IV-based model.

### Credit Estimation (pnl_model.py:78-140):
```
base_credit_pct = 0.25 + (iv_at_entry * 0.5)  # 25-45% of wing width
credit = wing_width * 100 * base_credit_pct
```

### Daily P&L Components:

#### Vega P&L (from IV change):
```
vega_sensitivity = 1.0  # $ per vol point per $100 max risk
vega_pnl = -iv_change * vega_sensitivity * (max_risk / 100)
```
Note: Negative because short vega (profits when IV drops)

#### Theta P&L (time decay):
```
theta_decay_factor = 0.4
days_elapsed_fraction = days_in_trade / target_dte
theta_pnl = estimated_credit * theta_decay_factor * days_elapsed_fraction
```

#### Total Estimated P&L:
```
total_pnl = vega_pnl + theta_pnl - costs
```

### Exit Triggers:
1. **Profit Target**: P&L >= 50% of max risk
2. **Stop Loss**: P&L <= -100% of max risk (full loss)
3. **Time Decay (DTE)**: Days to expiration <= 5
4. **Max Days in Trade**: days_in_trade >= 45
5. **IV Collapse**: IV drops 10+ vol points below entry
6. **Delta Breach**: IV spikes 8+ vol points (large move)

## 4. Entry Signal Generation

Entry signals are generated when ALL of the following are true:
1. IV Percentile >= configured minimum (default: 60)
2. No existing open position for the symbol
3. Additional optional filters (skew, term structure) if configured

## 5. Sample Split

Data is split into in-sample and out-of-sample periods:
- Default: 100% in-sample (no split for live config validation)
- Method: Chronological (first N% is in-sample)
"""

        with open(formulas_dir / "calculations.md", "w", encoding="utf-8") as f:
            f.write(formulas_md)

        logger.info(f"Formulas documentation exported to {formulas_dir}")

    def _export_readme(self, export_path: Path) -> None:
        """Export README with instructions for external validator."""
        readme_content = f"""# External Validation Export Package

## Symbol: {self.symbol}
## Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
## Backtest Period: {self.config.start_date} to {self.config.end_date}

---

## Purpose

This package contains all data needed to independently validate and reproduce
the backtest results for the {self.symbol} Iron Condor strategy.

## Package Contents

```
{export_path.name}/
├── README.md                           # This file
├── config/
│   └── all_config.json                 # Complete configuration used
├── input_data/
│   ├── {self.symbol}_iv_with_percentile.csv    # IV data with calculated percentiles
│   └── {self.symbol}_spot.csv                  # Historical spot prices
├── evaluation/
│   └── {self.symbol}_daily_decisions.csv       # Daily entry decision log
├── trades/
│   ├── {self.symbol}_trades_summary.csv        # Trade summary
│   └── {self.symbol}_trades_daily_snapshots.csv # Daily P&L breakdown per trade
└── formulas/
    └── calculations.md                 # All calculation formulas
```

## Validation Steps

### Step 1: Verify IV Percentile Calculation
1. Load `input_data/{self.symbol}_iv_with_percentile.csv`
2. For each date, verify `iv_percentile_calculated` using the 252-day rolling formula
3. Compare your calculated values with ours

### Step 2: Verify Entry Decisions
1. Load `evaluation/{self.symbol}_daily_decisions.csv`
2. For each date, verify:
   - `iv_percentile_passed` = True if `iv_percentile >= iv_percentile_min_required`
   - `entry_signal_generated` = True only if criteria passed AND no open position

### Step 3: Verify Trade P&L
1. Load `trades/{self.symbol}_trades_daily_snapshots.csv`
2. For each trade day, verify P&L calculation using formulas in `formulas/calculations.md`
3. Verify exit triggers are correctly identified

### Step 4: Verify Final Results
1. Load `trades/{self.symbol}_trades_summary.csv`
2. Sum `final_pnl` to get total P&L
3. Calculate win rate, profit factor, etc.

## Key Configuration Values

Entry Rules:
- IV Percentile Minimum: {self.config.entry_rules.iv_percentile_min}

Exit Rules:
- Profit Target: {self.config.exit_rules.profit_target_pct}% of max risk
- Stop Loss: {self.config.exit_rules.stop_loss_pct}% of max risk
- Min DTE: {self.config.exit_rules.min_dte} days
- Max Days in Trade: {self.config.exit_rules.max_days_in_trade}

Position Sizing:
- Max Risk per Trade: ${self.config.position_sizing.max_risk_per_trade}

## Questions?

If you find discrepancies or have questions about the calculations,
please document:
1. Which file/record shows the discrepancy
2. Your calculated value vs. our value
3. The formula you used

---
Generated by Tomic Backtest Export Tool
"""

        with open(export_path / "README.md", "w", encoding="utf-8") as f:
            f.write(readme_content)

        logger.info(f"README exported to {export_path / 'README.md'}")


def get_available_symbols() -> List[str]:
    """Get list of symbols from backtest.yaml."""
    backtest_yaml = _BASE_DIR / "config" / "backtest.yaml"
    if backtest_yaml.exists():
        config = _load_yaml(backtest_yaml)
        return config.get("symbols", [])
    return []


def run_external_validation_export() -> None:
    """Run the external validation export menu."""
    print("\n" + "=" * 70)
    print("EXPORT VOOR EXTERNE VALIDATIE")
    print("=" * 70)
    print("\nGenereer een compleet exportpakket zodat een externe partij")
    print("de backtest logica kan valideren en reproduceren.")

    # Get available symbols
    symbols = get_available_symbols()
    if not symbols:
        print("\nGeen symbolen geconfigureerd in config/backtest.yaml")
        return

    print("\nSelecteer symbool voor validatie:")
    for i, symbol in enumerate(symbols[:20], 1):  # Show max 20
        print(f"  [{i:2d}] {symbol}")
    if len(symbols) > 20:
        print(f"  ... en {len(symbols) - 20} meer")

    print(f"\n  [A] Alle symbolen ({len(symbols)} totaal)")

    choice = input("\nKeuze: ").strip().upper()

    selected_symbols = []
    if choice == "A":
        selected_symbols = symbols
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(symbols):
                selected_symbols = [symbols[idx]]
            else:
                print("Ongeldige keuze.")
                return
        except ValueError:
            print("Ongeldige keuze.")
            return

    # Export options
    print("\nExport opties:")
    print("  [1] Volledig pakket (aanbevolen voor validatie)")
    print("  [2] Alleen data (IV + spot)")

    export_choice = input("\nKeuze [1]: ").strip() or "1"
    include_all = export_choice == "1"

    # Run export
    output_dir = Path("exports")
    output_dir.mkdir(exist_ok=True)

    print("\n" + "-" * 70)
    print("Generating export...")

    for symbol in selected_symbols:
        print(f"\nExporting {symbol}...")
        try:
            exporter = ExternalValidationExporter(symbol, output_dir)
            export_path = exporter.run_export(include_all_data=include_all)
            print(f"  ✓ Export klaar: {export_path}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            logger.exception(f"Export failed for {symbol}")

    print("\n" + "=" * 70)
    print("Export voltooid!")
    print("=" * 70)
