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
from datetime import date, datetime, timedelta
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

# Strategy type constants
STRATEGY_IRON_CONDOR = "iron_condor"
STRATEGY_CALENDAR = "calendar"
STRATEGY_COMBINED = "combined"

STRATEGY_DISPLAY_NAMES = {
    STRATEGY_IRON_CONDOR: "Iron Condor",
    STRATEGY_CALENDAR: "Calendar Spread",
    STRATEGY_COMBINED: "Iron Condor + Calendar",
}


@dataclass
class DailyEvaluation:
    """Daily evaluation record for a symbol."""

    date: str
    symbol: str
    strategy_type: str  # iron_condor, calendar, or combined
    atm_iv: Optional[float]
    iv_percentile: Optional[float]
    iv_rank: Optional[float]
    hv30: Optional[float]
    skew: Optional[float]
    term_m1_m2: Optional[float]
    spot_price: Optional[float]
    # Criteria evaluation - Iron Condor (high IV entry)
    iv_percentile_min_required: Optional[float]
    iv_percentile_min_passed: bool
    # Criteria evaluation - Calendar (low IV entry)
    iv_percentile_max_required: Optional[float]
    iv_percentile_max_passed: bool
    # Combined criteria result
    entry_criteria_passed: bool
    has_open_position: bool
    entry_signal_generated: bool
    reason_no_entry: Optional[str]


@dataclass
class TradeDailySnapshot:
    """Daily snapshot of a trade's state."""

    trade_id: int
    date: str
    strategy_type: str  # iron_condor or calendar
    days_in_trade: int
    iv_current: Optional[float]
    iv_change_from_entry: Optional[float]
    spot_current: Optional[float]
    estimated_pnl: float
    pnl_pct_of_max_risk: float
    # Exit criteria evaluation - common
    profit_target_level: float
    stop_loss_level: float
    profit_target_triggered: bool
    stop_loss_triggered: bool
    dte_remaining: int
    min_dte_triggered: bool
    # Calendar-specific: near leg DTE
    near_leg_dte_remaining: Optional[int]
    near_leg_dte_triggered: bool
    # Final exit status
    exit_triggered: bool
    exit_reason: Optional[str]


class ExternalValidationExporter:
    """Handles export of all data needed for external validation."""

    def __init__(
        self,
        symbol: str,
        output_dir: Path,
        strategy_type: str = STRATEGY_IRON_CONDOR,
    ):
        """Initialize exporter.

        Args:
            symbol: Symbol to export data for
            output_dir: Directory to write export files to
            strategy_type: Strategy type (iron_condor, calendar, or combined)
        """
        self.symbol = symbol
        self.output_dir = output_dir
        self.strategy_type = strategy_type
        self.config: Optional[BacktestConfig] = None
        self.config_calendar: Optional[BacktestConfig] = None  # For combined mode
        self.live_config: Dict[str, Any] = {}
        self.data_loader: Optional[DataLoader] = None
        self.backtest_result: Optional[BacktestResult] = None
        self.backtest_result_calendar: Optional[BacktestResult] = None  # For combined mode
        self.daily_evaluations: List[DailyEvaluation] = []
        self.trade_snapshots: List[TradeDailySnapshot] = []

    def run_export(self, include_all_data: bool = True) -> Path:
        """Run the complete export process.

        Args:
            include_all_data: If True, exports everything. If False, only essentials.

        Returns:
            Path to the export directory.
        """
        # Create export directory with strategy type in name
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        strategy_suffix = self.strategy_type.replace("_", "-")
        export_path = self.output_dir / f"external_validation_{self.symbol}_{strategy_suffix}_{timestamp}"
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
        """Load all configuration from YAML files based on strategy type."""
        # Import here to avoid circular import
        from tomic.cli.strategy_testing_ui import load_live_config

        if self.strategy_type == STRATEGY_COMBINED:
            # Load both iron condor and calendar configs
            self.live_config = load_live_config(STRATEGY_IRON_CONDOR)

            # Load iron condor config
            backtest_yaml = _BASE_DIR / "config" / "backtest.yaml"
            if backtest_yaml.exists():
                config_data = _load_yaml(backtest_yaml)
                config_data["symbols"] = [self.symbol]
                config_data["strategy_type"] = STRATEGY_IRON_CONDOR
                self.config = BacktestConfig.model_validate(config_data)

            # Load calendar config
            calendar_yaml = _BASE_DIR / "config" / "backtest_calendar.yaml"
            if calendar_yaml.exists():
                config_data_cal = _load_yaml(calendar_yaml)
                config_data_cal["symbols"] = [self.symbol]
                config_data_cal["strategy_type"] = STRATEGY_CALENDAR
                self.config_calendar = BacktestConfig.model_validate(config_data_cal)
            else:
                # Fallback to backtest.yaml with calendar strategy type
                if backtest_yaml.exists():
                    config_data_cal = _load_yaml(backtest_yaml)
                    config_data_cal["symbols"] = [self.symbol]
                    config_data_cal["strategy_type"] = STRATEGY_CALENDAR
                    self.config_calendar = BacktestConfig.model_validate(config_data_cal)

        elif self.strategy_type == STRATEGY_CALENDAR:
            self.live_config = load_live_config(STRATEGY_CALENDAR)

            # Load calendar config
            calendar_yaml = _BASE_DIR / "config" / "backtest_calendar.yaml"
            if calendar_yaml.exists():
                config_data = _load_yaml(calendar_yaml)
            else:
                # Fallback to backtest.yaml
                backtest_yaml = _BASE_DIR / "config" / "backtest.yaml"
                config_data = _load_yaml(backtest_yaml) if backtest_yaml.exists() else {}

            config_data["symbols"] = [self.symbol]
            config_data["strategy_type"] = STRATEGY_CALENDAR
            self.config = BacktestConfig.model_validate(config_data)

        else:
            # Default: iron condor
            self.live_config = load_live_config(STRATEGY_IRON_CONDOR)

            backtest_yaml = _BASE_DIR / "config" / "backtest.yaml"
            if backtest_yaml.exists():
                config_data = _load_yaml(backtest_yaml)
                config_data["symbols"] = [self.symbol]
                config_data["strategy_type"] = STRATEGY_IRON_CONDOR
                self.config = BacktestConfig.model_validate(config_data)

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

        # For combined mode, also run calendar backtest
        if self.strategy_type == STRATEGY_COMBINED and self.config_calendar:
            engine_calendar = BacktestEngine(self.config_calendar)
            self.backtest_result_calendar = engine_calendar.run()

        # Now collect daily evaluations with knowledge of actual trades
        self._collect_daily_evaluations(iv_ts)

        # Collect trade snapshots from result
        self._collect_trade_snapshots()

    def _collect_daily_evaluations(self, iv_ts) -> None:
        """Collect daily entry evaluation data for all strategy types."""
        # Get entry criteria based on strategy type
        # Iron Condor: HIGH IV entry (iv_percentile >= min)
        # Calendar: LOW IV entry (iv_percentile <= max)
        iv_pct_min = self.config.entry_rules.iv_percentile_min
        iv_pct_max = self.config.entry_rules.iv_percentile_max

        # For combined mode, get calendar criteria from calendar config
        if self.strategy_type == STRATEGY_COMBINED and self.config_calendar:
            iv_pct_max = self.config_calendar.entry_rules.iv_percentile_max

        # Build sets of dates when positions were open and entries were made
        open_dates: set = set()
        entry_dates: set = set()
        entry_dates_calendar: set = set()

        # Collect from primary backtest result
        if self.backtest_result:
            for trade in self.backtest_result.trades:
                if trade.symbol != self.symbol:
                    continue
                entry_dates.add(trade.entry_date)
                if trade.exit_date:
                    current = trade.entry_date
                    while current < trade.exit_date:
                        open_dates.add(current)
                        current += timedelta(days=1)

        # Collect from calendar backtest result (combined mode)
        if self.strategy_type == STRATEGY_COMBINED and self.backtest_result_calendar:
            for trade in self.backtest_result_calendar.trades:
                if trade.symbol != self.symbol:
                    continue
                entry_dates_calendar.add(trade.entry_date)
                if trade.exit_date:
                    current = trade.entry_date
                    while current < trade.exit_date:
                        open_dates.add(current)
                        current += timedelta(days=1)

        # Get spot prices once
        spot_prices = self.data_loader.load_spot_prices(self.symbol)

        for dp in iv_ts:
            has_open = dp.date in open_dates

            # Determine if entry criteria passed for each strategy type
            # Iron Condor: HIGH IV entry
            iv_min_passed = False
            if iv_pct_min is not None and dp.iv_percentile is not None:
                iv_min_passed = dp.iv_percentile >= iv_pct_min

            # Calendar: LOW IV entry
            iv_max_passed = False
            if iv_pct_max is not None and dp.iv_percentile is not None:
                iv_max_passed = dp.iv_percentile <= iv_pct_max

            # Determine overall entry criteria based on strategy type
            if self.strategy_type == STRATEGY_IRON_CONDOR:
                entry_criteria_passed = iv_min_passed
                was_entry_date = dp.date in entry_dates
            elif self.strategy_type == STRATEGY_CALENDAR:
                entry_criteria_passed = iv_max_passed
                was_entry_date = dp.date in entry_dates
            else:  # STRATEGY_COMBINED
                entry_criteria_passed = iv_min_passed or iv_max_passed
                was_entry_date = dp.date in entry_dates or dp.date in entry_dates_calendar

            # Determine reason for no entry
            reason = None
            entry_generated = was_entry_date

            if was_entry_date:
                reason = None
            elif has_open:
                reason = "position_already_open"
            elif dp.iv_percentile is None:
                reason = "iv_percentile_not_available"
            elif not entry_criteria_passed:
                if self.strategy_type == STRATEGY_IRON_CONDOR:
                    reason = f"iv_percentile_{dp.iv_percentile:.1f}_below_min_{iv_pct_min}"
                elif self.strategy_type == STRATEGY_CALENDAR:
                    reason = f"iv_percentile_{dp.iv_percentile:.1f}_above_max_{iv_pct_max}"
                else:
                    reason = f"iv_percentile_{dp.iv_percentile:.1f}_not_in_range"
            else:
                reason = "criteria_passed_but_no_entry_other_constraint"

            spot = spot_prices.get(dp.date)

            eval_record = DailyEvaluation(
                date=str(dp.date),
                symbol=self.symbol,
                strategy_type=self.strategy_type,
                atm_iv=dp.atm_iv,
                iv_percentile=dp.iv_percentile,
                iv_rank=dp.iv_rank,
                hv30=dp.hv30,
                skew=dp.skew,
                term_m1_m2=dp.term_m1_m2,
                spot_price=spot,
                iv_percentile_min_required=iv_pct_min,
                iv_percentile_min_passed=iv_min_passed,
                iv_percentile_max_required=iv_pct_max,
                iv_percentile_max_passed=iv_max_passed,
                entry_criteria_passed=entry_criteria_passed,
                has_open_position=has_open,
                entry_signal_generated=entry_generated,
                reason_no_entry=reason,
            )
            self.daily_evaluations.append(eval_record)

    def _collect_trade_snapshots(self) -> None:
        """Collect daily snapshots for each trade.

        Exit triggers are checked in the same priority order as exit_evaluator.py:
        1. Profit target (50% of credit for IC, or profit % of max_risk for calendar)
        2. Stop loss (100% of credit for IC, or loss % of max_risk for calendar)
        3. Time decay (min DTE) - for calendars: near leg DTE
        4. Delta breach (IV spike >= 8 vol points)
        5. IV collapse (IV drop >= threshold vol points)
        6. Max days in trade
        """
        # Collect trades from primary backtest
        trades_to_process: List[Tuple[SimulatedTrade, int, BacktestConfig]] = []

        if self.backtest_result:
            for idx, trade in enumerate(self.backtest_result.trades):
                if trade.symbol == self.symbol:
                    trades_to_process.append((trade, idx, self.config))

        # For combined mode, also collect calendar trades
        if self.strategy_type == STRATEGY_COMBINED and self.backtest_result_calendar:
            base_idx = len(trades_to_process)
            for idx, trade in enumerate(self.backtest_result_calendar.trades):
                if trade.symbol == self.symbol:
                    trades_to_process.append((trade, base_idx + idx, self.config_calendar))

        if not trades_to_process:
            return

        for trade, idx, config in trades_to_process:
            profit_target_pct = config.exit_rules.profit_target_pct
            stop_loss_pct = config.exit_rules.stop_loss_pct
            min_dte = config.exit_rules.min_dte
            max_dit = config.exit_rules.max_days_in_trade
            iv_collapse_threshold = config.exit_rules.iv_collapse_threshold
            delta_breach_iv_spike = 8.0

            is_calendar = trade.is_calendar()

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
                # Use actual date from date_history if available
                if day_idx < len(trade.date_history):
                    trade_date = trade.date_history[day_idx]
                else:
                    trade_date = trade.entry_date + timedelta(days=day_idx)

                iv_change = None
                iv_change_vol_points = None
                if iv_current is not None:
                    iv_change = iv_current - trade.iv_at_entry
                    iv_entry_norm = trade.iv_at_entry if trade.iv_at_entry < 1 else trade.iv_at_entry / 100
                    iv_current_norm = iv_current if iv_current < 1 else iv_current / 100
                    iv_change_vol_points = (iv_current_norm - iv_entry_norm) * 100

                pnl_pct = (pnl / trade.max_risk) * 100 if trade.max_risk else 0

                # Calculate DTE remaining
                dte_remaining = max(0, (trade.target_expiry - trade_date).days)
                days_in_trade_actual = (trade_date - trade.entry_date).days

                # Calendar-specific: near leg DTE
                near_leg_dte = None
                near_leg_dte_triggered = False
                if is_calendar and trade.short_expiry:
                    near_leg_dte = max(0, (trade.short_expiry - trade_date).days)
                    near_leg_dte_triggered = near_leg_dte <= min_dte

                # Exit triggers differ for iron condor vs calendar
                if is_calendar:
                    # Calendar: P&L target/stop based on max_risk (debit paid)
                    profit_target_amount = trade.max_risk * (profit_target_pct / 100)
                    stop_loss_amount = trade.max_risk * (stop_loss_pct / 100)
                else:
                    # Iron Condor: P&L target/stop based on credit received
                    profit_target_amount = trade.estimated_credit * (profit_target_pct / 100)
                    stop_loss_amount = trade.estimated_credit * (stop_loss_pct / 100)

                profit_target_triggered = pnl >= profit_target_amount
                stop_loss_triggered = pnl <= -stop_loss_amount

                # Time decay (min DTE) - use near leg for calendars
                if is_calendar and near_leg_dte is not None:
                    min_dte_triggered = near_leg_dte_triggered
                else:
                    min_dte_triggered = dte_remaining <= min_dte

                # Delta breach: IV spike >= threshold
                delta_breach_triggered = (
                    iv_change_vol_points is not None
                    and iv_change_vol_points >= delta_breach_iv_spike
                )

                # IV collapse: IV dropped >= threshold below entry
                iv_collapse_triggered = (
                    iv_collapse_threshold is not None
                    and iv_change_vol_points is not None
                    and iv_change_vol_points <= -iv_collapse_threshold
                )

                # Max days in trade
                max_dit_triggered = days_in_trade_actual >= max_dit

                # Determine exit in priority order
                exit_triggered = (
                    profit_target_triggered
                    or stop_loss_triggered
                    or min_dte_triggered
                    or delta_breach_triggered
                    or iv_collapse_triggered
                    or max_dit_triggered
                )
                exit_reason = None
                if profit_target_triggered:
                    exit_reason = "profit_target"
                elif stop_loss_triggered:
                    exit_reason = "stop_loss"
                elif min_dte_triggered:
                    exit_reason = "near_leg_dte" if is_calendar else "time_decay_dte"
                elif delta_breach_triggered:
                    exit_reason = "delta_breach"
                elif iv_collapse_triggered:
                    exit_reason = "iv_collapse"
                elif max_dit_triggered:
                    exit_reason = "max_days_in_trade"

                snapshot = TradeDailySnapshot(
                    trade_id=idx,
                    date=str(trade_date),
                    strategy_type=trade.strategy_type,
                    days_in_trade=days_in_trade_actual,
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
                    near_leg_dte_remaining=near_leg_dte,
                    near_leg_dte_triggered=near_leg_dte_triggered,
                    exit_triggered=exit_triggered,
                    exit_reason=exit_reason,
                )
                self.trade_snapshots.append(snapshot)

    def _export_config(self, config_dir: Path) -> None:
        """Export all configuration to JSON."""
        config_dir.mkdir(parents=True, exist_ok=True)

        # Build strategy-specific config section
        strategy_display = STRATEGY_DISPLAY_NAMES.get(self.strategy_type, self.strategy_type)

        # Base backtest config
        backtest_config = {
            "strategy_type": self.strategy_type,
            "strategy_display_name": strategy_display,
            "target_dte": self.config.target_dte,
        }

        # Add iron condor specific params
        if self.strategy_type in (STRATEGY_IRON_CONDOR, STRATEGY_COMBINED):
            backtest_config["iron_condor"] = {
                "wing_width": self.config.iron_condor_wing_width,
                "short_delta": self.config.iron_condor_short_delta,
            }

        # Add calendar specific params
        if self.strategy_type in (STRATEGY_CALENDAR, STRATEGY_COMBINED):
            cal_config = self.config_calendar if self.config_calendar else self.config
            backtest_config["calendar"] = {
                "near_dte": cal_config.calendar_near_dte,
                "far_dte": cal_config.calendar_far_dte,
                "min_gap": cal_config.calendar_min_gap,
            }

        # Build entry rules - include both high IV and low IV criteria
        entry_rules = {
            "iv_percentile_min": self.config.entry_rules.iv_percentile_min,
            "iv_percentile_max": self.config.entry_rules.iv_percentile_max,
            "iv_rank_min": self.config.entry_rules.iv_rank_min,
            "iv_rank_max": self.config.entry_rules.iv_rank_max,
            "skew_min": self.config.entry_rules.skew_min,
            "skew_max": self.config.entry_rules.skew_max,
            "term_structure_min": self.config.entry_rules.term_structure_min,
            "term_structure_max": self.config.entry_rules.term_structure_max,
            "iv_hv_spread_min": self.config.entry_rules.iv_hv_spread_min,
        }

        # For combined mode, also include calendar entry rules
        if self.strategy_type == STRATEGY_COMBINED and self.config_calendar:
            entry_rules["calendar_iv_percentile_max"] = self.config_calendar.entry_rules.iv_percentile_max
            entry_rules["calendar_iv_rank_max"] = self.config_calendar.entry_rules.iv_rank_max

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
            "backtest_config": backtest_config,
            "entry_rules": entry_rules,
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
                    "strategy_type",
                    "atm_iv",
                    "iv_percentile",
                    "iv_rank",
                    "hv30",
                    "skew",
                    "term_m1_m2",
                    "spot_price",
                    "iv_percentile_min_required",
                    "iv_percentile_min_passed",
                    "iv_percentile_max_required",
                    "iv_percentile_max_passed",
                    "entry_criteria_passed",
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
                        ev.strategy_type,
                        ev.atm_iv,
                        ev.iv_percentile,
                        ev.iv_rank,
                        ev.hv30,
                        ev.skew,
                        ev.term_m1_m2,
                        ev.spot_price,
                        ev.iv_percentile_min_required,
                        ev.iv_percentile_min_passed,
                        ev.iv_percentile_max_required,
                        ev.iv_percentile_max_passed,
                        ev.entry_criteria_passed,
                        ev.has_open_position,
                        ev.entry_signal_generated,
                        ev.reason_no_entry,
                    ]
                )

        logger.info(f"Daily evaluations exported to {csv_path}")

    def _export_trade_details(self, trades_dir: Path) -> None:
        """Export trade details with daily P&L breakdown."""
        trades_dir.mkdir(parents=True, exist_ok=True)

        # Collect all trades to export
        all_trades: List[Tuple[SimulatedTrade, int]] = []

        if self.backtest_result:
            for idx, trade in enumerate(self.backtest_result.trades):
                if trade.symbol == self.symbol:
                    all_trades.append((trade, idx))

        # For combined mode, also include calendar trades
        if self.strategy_type == STRATEGY_COMBINED and self.backtest_result_calendar:
            base_idx = len(all_trades)
            for idx, trade in enumerate(self.backtest_result_calendar.trades):
                if trade.symbol == self.symbol:
                    all_trades.append((trade, base_idx + idx))

        if not all_trades:
            return

        # Export trade summary with calendar-specific fields
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
                    "entry_debit",
                    "short_expiry",
                    "long_expiry",
                    "final_pnl",
                    "pnl_pct",
                    "days_in_trade",
                    "exit_reason",
                    "status",
                ]
            )

            for trade, idx in all_trades:
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
                        trade.entry_debit,
                        trade.short_expiry,
                        trade.long_expiry,
                        trade.final_pnl,
                        pnl_pct,
                        trade.days_in_trade,
                        trade.exit_reason.value if trade.exit_reason else None,
                        trade.status.value,
                    ]
                )

        # Export daily snapshots with calendar-specific fields
        if self.trade_snapshots:
            snapshots_path = trades_dir / f"{self.symbol}_trades_daily_snapshots.csv"
            with open(snapshots_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "trade_id",
                        "date",
                        "strategy_type",
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
                        "near_leg_dte_remaining",
                        "near_leg_dte_triggered",
                        "exit_triggered",
                        "exit_reason",
                    ]
                )

                for snap in self.trade_snapshots:
                    writer.writerow(
                        [
                            snap.trade_id,
                            snap.date,
                            snap.strategy_type,
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
                            snap.near_leg_dte_remaining,
                            snap.near_leg_dte_triggered,
                            snap.exit_triggered,
                            snap.exit_reason,
                        ]
                    )

        logger.info(f"Trade details exported to {trades_dir}")

    def _export_formulas(self, formulas_dir: Path) -> None:
        """Export calculation formulas documentation."""
        formulas_dir.mkdir(parents=True, exist_ok=True)

        strategy_display = STRATEGY_DISPLAY_NAMES.get(self.strategy_type, self.strategy_type)

        # Base formulas (common to all strategies)
        formulas_md = f"""# Calculation Formulas

## Strategy Type: {strategy_display}

## 1. IV Percentile Calculation

The IV percentile is calculated using a **252-day rolling window** (1 trading year).

```
iv_percentile = (count of days where IV < current_IV) / (total days in lookback) * 100
```

### Implementation Details:
- Lookback window: 252 **calendar** days (not trading days)
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

### Known Limitation: Data Gaps
The 252-day lookback window uses **calendar days**, not trading days.
When data gaps exist (e.g., missing March 2019), the percentile calculation
includes different historical data than expected, causing deviations of
10-25% around gap boundaries. This is expected behavior.

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

"""

        # Add strategy-specific P&L model documentation
        if self.strategy_type in (STRATEGY_IRON_CONDOR, STRATEGY_COMBINED):
            formulas_md += """## 3. Iron Condor P&L Estimation Model

Since we don't have historical bid/ask data, P&L is estimated using an IV-based model.

### Credit Estimation (pnl_model.py:78-138):
```python
# Base credit ratio at 20% IV, 45 DTE, 1.5 stddev
base_credit_ratio = 0.30  # 30% of wing width

# Adjustments for market conditions
iv_adjustment = iv_at_entry / 0.20  # Scale relative to 20% IV baseline
dte_adjustment = min(1.2, target_dte / 45)  # More DTE = higher credit
stddev_adjustment = (1.5 / stddev_range) ** 0.6  # Closer strikes = higher credit

# Final credit ratio (capped between 20-50% of wing width)
credit_ratio = base_credit_ratio * iv_adjustment * dte_adjustment * stddev_adjustment
credit_ratio = clamp(credit_ratio, 0.20, 0.50)

# Credit in dollars
credit = wing_width * credit_ratio
```

### Daily P&L Components:

#### Vega P&L (from IV change) - SHORT VEGA:
```python
VEGA_SENSITIVITY = 1.5  # $ per vol point per $100 max risk

# IV change in vol points (positive = IV dropped = profit for short vega)
iv_change = (iv_at_entry - iv_current) * 100  # Convert to vol points
vega_pnl = iv_change * VEGA_SENSITIVITY * (max_risk / 100)
```

#### Theta P&L (time decay):
```python
THETA_DECAY_FACTOR = 0.5

# Time fraction with sqrt acceleration (theta accelerates near expiry)
time_fraction = days_in_trade / target_dte
theta_progress = sqrt(time_fraction)  # At 50% time elapsed, ~71% theta captured

theta_pnl = estimated_credit * theta_progress * THETA_DECAY_FACTOR
```

#### Total Estimated P&L:
```python
total_pnl = vega_pnl + theta_pnl - costs
total_pnl = min(estimated_credit, total_pnl)  # Cap at max profit (credit)
total_pnl = max(-max_risk, total_pnl)  # Cap at max loss (wing width)
```

### Iron Condor Exit Triggers (checked in priority order):
1. **Profit Target**: P&L >= 50% of **estimated_credit** (NOT max_risk)
2. **Stop Loss**: P&L <= -100% of **estimated_credit**
3. **Time Decay (DTE)**: Days to expiration <= 5 (avoid gamma risk)
4. **Delta Breach**: IV spikes >= 8 vol points (proxy for large spot move)
5. **IV Collapse**: IV drops >= 10 vol points below entry (thesis validated)
6. **Max Days in Trade**: days_in_trade >= 45

"""

        if self.strategy_type in (STRATEGY_CALENDAR, STRATEGY_COMBINED):
            formulas_md += """## 3. Calendar Spread P&L Estimation Model

Calendar spreads are LONG VEGA positions that profit when IV increases.

### Debit Estimation:
```python
# Calendar spread max risk = debit paid
# Typical debit is 30-40% of the far-leg value
base_debit_ratio = 0.35

# Adjustments for IV level (lower IV = cheaper calendars)
iv_adjustment = iv_at_entry / 0.20  # Scale relative to 20% IV baseline

# Final debit (entry cost)
entry_debit = estimated_far_leg_value * base_debit_ratio * iv_adjustment
max_risk = entry_debit  # Calendar max risk = debit paid
```

### Daily P&L Components:

#### Vega P&L (from IV change) - LONG VEGA:
```python
VEGA_SENSITIVITY = 1.5  # $ per vol point per $100 max risk

# IV change in vol points (positive = IV increased = profit for long vega)
iv_change = (iv_current - iv_at_entry) * 100  # Note: opposite sign vs iron condor
vega_pnl = iv_change * VEGA_SENSITIVITY * (max_risk / 100)
```

#### Theta P&L (time decay):
Calendar spreads benefit from the near-leg decaying faster than the far-leg.

```python
# Theta differential between near and far leg
near_leg_theta = estimate_theta(near_dte)
far_leg_theta = estimate_theta(far_dte)

# Net theta = near_leg_theta - far_leg_theta (positive when near decays faster)
net_theta_pnl = (near_leg_theta - far_leg_theta) * days_in_trade
```

#### Total Estimated P&L:
```python
total_pnl = vega_pnl + net_theta_pnl - costs
total_pnl = max(-max_risk, total_pnl)  # Cap at max loss (debit paid)
```

### Calendar Exit Triggers (checked in priority order):
1. **Profit Target**: P&L >= 50% of **max_risk** (debit paid)
2. **Stop Loss**: P&L <= -100% of **max_risk**
3. **Near Leg DTE**: Near leg days to expiration <= 5 (avoid pin risk)
4. **Delta Breach**: IV spikes >= 8 vol points (but this benefits calendars!)
5. **IV Collapse**: IV drops >= 10 vol points (negative for long vega)
6. **Max Days in Trade**: days_in_trade >= 45

"""

        # Entry signal generation section (strategy-specific)
        formulas_md += """## 4. Entry Signal Generation

"""
        if self.strategy_type == STRATEGY_IRON_CONDOR:
            formulas_md += """Entry signals for **Iron Condor** are generated when ALL of the following are true:
1. **IV Percentile >= configured minimum** (default: 60%) - HIGH IV entry
2. No existing open position for the symbol
3. Total positions < max_total_positions limit
4. Additional optional filters (skew, term structure, IV-HV spread) if configured

**Rationale**: Enter iron condors when IV is HIGH (elevated IV percentile) to collect
maximum premium. Short vega position profits as IV mean-reverts downward.
"""
        elif self.strategy_type == STRATEGY_CALENDAR:
            formulas_md += """Entry signals for **Calendar Spread** are generated when ALL of the following are true:
1. **IV Percentile <= configured maximum** (default: 40%) - LOW IV entry
2. No existing open position for the symbol
3. Total positions < max_total_positions limit
4. Optional: Term structure filter (front IV >= back IV for mispricing opportunity)

**Rationale**: Enter calendars when IV is LOW (depressed IV percentile) to buy cheap
options. Long vega position profits as IV mean-reverts upward.
"""
        else:  # STRATEGY_COMBINED
            formulas_md += """Entry signals for **Combined Strategy** are generated when EITHER:

### Iron Condor Entry:
1. **IV Percentile >= configured minimum** (default: 60%) - HIGH IV entry
2. No existing open position for the symbol
3. Total positions < max_total_positions limit

### Calendar Spread Entry:
1. **IV Percentile <= configured maximum** (default: 40%) - LOW IV entry
2. No existing open position for the symbol
3. Total positions < max_total_positions limit

**Rationale**: The combined strategy trades both extremes of IV:
- When IV is HIGH: Enter short vega positions (iron condors) to profit from IV crush
- When IV is LOW: Enter long vega positions (calendars) to profit from IV expansion
"""

        formulas_md += """

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
        strategy_display = STRATEGY_DISPLAY_NAMES.get(self.strategy_type, self.strategy_type)

        # Build entry rules section based on strategy type
        if self.strategy_type == STRATEGY_IRON_CONDOR:
            entry_rules_section = f"""Entry Rules (Iron Condor - HIGH IV Entry):
- IV Percentile Minimum: {self.config.entry_rules.iv_percentile_min}"""
            entry_verification = """   - `iv_percentile_min_passed` = True if `iv_percentile >= iv_percentile_min_required`
   - `entry_signal_generated` = True only if criteria passed AND no open position"""

        elif self.strategy_type == STRATEGY_CALENDAR:
            entry_rules_section = f"""Entry Rules (Calendar - LOW IV Entry):
- IV Percentile Maximum: {self.config.entry_rules.iv_percentile_max}"""
            entry_verification = """   - `iv_percentile_max_passed` = True if `iv_percentile <= iv_percentile_max_required`
   - `entry_signal_generated` = True only if criteria passed AND no open position"""

        else:  # STRATEGY_COMBINED
            iv_pct_min = self.config.entry_rules.iv_percentile_min
            iv_pct_max = self.config_calendar.entry_rules.iv_percentile_max if self.config_calendar else "N/A"
            entry_rules_section = f"""Entry Rules (Combined Strategy):
- Iron Condor: IV Percentile >= {iv_pct_min} (HIGH IV)
- Calendar:    IV Percentile <= {iv_pct_max} (LOW IV)"""
            entry_verification = """   - `iv_percentile_min_passed` = True for Iron Condor entry when IV is high
   - `iv_percentile_max_passed` = True for Calendar entry when IV is low
   - `entry_criteria_passed` = True if either strategy criteria is met
   - `entry_signal_generated` = True only if criteria passed AND no open position"""

        # Build strategy-specific config section
        if self.strategy_type == STRATEGY_IRON_CONDOR:
            strategy_config = f"""
Iron Condor Parameters:
- Wing Width: {self.config.iron_condor_wing_width}
- Short Delta: {self.config.iron_condor_short_delta}
- Target DTE: {self.config.target_dte}"""

        elif self.strategy_type == STRATEGY_CALENDAR:
            strategy_config = f"""
Calendar Parameters:
- Near Leg DTE: {self.config.calendar_near_dte}
- Far Leg DTE: {self.config.calendar_far_dte}
- Minimum Gap: {self.config.calendar_min_gap}"""

        else:  # STRATEGY_COMBINED
            cal_config = self.config_calendar if self.config_calendar else self.config
            strategy_config = f"""
Iron Condor Parameters:
- Wing Width: {self.config.iron_condor_wing_width}
- Short Delta: {self.config.iron_condor_short_delta}
- Target DTE: {self.config.target_dte}

Calendar Parameters:
- Near Leg DTE: {cal_config.calendar_near_dte}
- Far Leg DTE: {cal_config.calendar_far_dte}
- Minimum Gap: {cal_config.calendar_min_gap}"""

        readme_content = f"""# External Validation Export Package

## Symbol: {self.symbol}
## Strategy: {strategy_display}
## Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
## Backtest Period: {self.config.start_date} to {self.config.end_date}

---

## Purpose

This package contains all data needed to independently validate and reproduce
the backtest results for the {self.symbol} {strategy_display} strategy.

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
{entry_verification}

### Step 3: Verify Trade P&L
1. Load `trades/{self.symbol}_trades_daily_snapshots.csv`
2. For each trade day, verify P&L calculation using formulas in `formulas/calculations.md`
3. Verify exit triggers are correctly identified
4. For calendar trades: also verify `near_leg_dte_remaining` and `near_leg_dte_triggered`

### Step 4: Verify Final Results
1. Load `trades/{self.symbol}_trades_summary.csv`
2. Sum `final_pnl` to get total P&L
3. Calculate win rate, profit factor, etc.

## Key Configuration Values

{entry_rules_section}

Exit Rules:
- Profit Target: {self.config.exit_rules.profit_target_pct}% of max risk
- Stop Loss: {self.config.exit_rules.stop_loss_pct}% of max risk
- Min DTE: {self.config.exit_rules.min_dte} days
- Max Days in Trade: {self.config.exit_rules.max_days_in_trade}
{strategy_config}

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


def _select_strategy_for_export() -> Optional[str]:
    """Prompt user to select a strategy type for export.

    Returns:
        Strategy type string, or None if cancelled.
    """
    print("\n" + "-" * 50)
    print("KIES STRATEGIE TYPE")
    print("-" * 50)
    print("1. Iron Condor       (credit, hoge IV entry)")
    print("2. Calendar Spread   (debit, lage IV entry)")
    print("3. Gecombineerd      (beide strategieën)")
    print("4. Terug")

    choice = input("\nMaak je keuze [1-4]: ").strip()

    if choice == "1":
        return STRATEGY_IRON_CONDOR
    elif choice == "2":
        return STRATEGY_CALENDAR
    elif choice == "3":
        return STRATEGY_COMBINED
    else:
        return None


def run_external_validation_export() -> None:
    """Run the external validation export menu."""
    print("\n" + "=" * 70)
    print("EXPORT VOOR EXTERNE VALIDATIE")
    print("=" * 70)
    print("\nGenereer een compleet exportpakket zodat een externe partij")
    print("de backtest logica kan valideren en reproduceren.")

    # Select strategy type
    strategy_type = _select_strategy_for_export()
    if strategy_type is None:
        print("Geannuleerd.")
        return

    strategy_display = STRATEGY_DISPLAY_NAMES.get(strategy_type, strategy_type)
    print(f"\nGeselecteerde strategie: {strategy_display}")

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
    print(f"Generating {strategy_display} export...")

    for symbol in selected_symbols:
        print(f"\nExporting {symbol} ({strategy_display})...")
        try:
            exporter = ExternalValidationExporter(
                symbol=symbol,
                output_dir=output_dir,
                strategy_type=strategy_type,
            )
            export_path = exporter.run_export(include_all_data=include_all)
            print(f"  ✓ Export klaar: {export_path}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            logger.exception(f"Export failed for {symbol}")

    print("\n" + "=" * 70)
    print("Export voltooid!")
    print("=" * 70)
