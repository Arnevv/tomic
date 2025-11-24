"""Backtesting module for delta-neutral options strategies.

This module provides tools to backtest options strategies using historical IV data.
The primary focus is on validating the core hypothesis that systematically selling
premium when IV is elevated relative to HV delivers consistent positive returns.

Key components:
- BacktestConfig: Configuration for backtest parameters
- DataLoader: Load and normalize historical IV data
- SignalGenerator: Detect entry signals based on IV metrics
- TradeSimulator: Manage trade lifecycle from entry to exit
- ExitEvaluator: Evaluate exit conditions
- PnLModel: Estimate P&L based on IV changes
- BacktestEngine: Orchestrate the entire backtest flow
- BacktestMetrics: Calculate performance statistics
"""

from tomic.backtest.config import BacktestConfig, load_backtest_config
from tomic.backtest.engine import BacktestEngine
from tomic.backtest.results import BacktestResult

__all__ = [
    "BacktestConfig",
    "load_backtest_config",
    "BacktestEngine",
    "BacktestResult",
]
