"""Result models and data structures for backtesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional


class TradeStatus(Enum):
    """Status of a simulated trade."""

    OPEN = "open"
    CLOSED = "closed"


class ExitReason(Enum):
    """Reason for trade exit."""

    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TIME_DECAY = "time_decay_dte"
    MAX_DIT = "max_days_in_trade"
    IV_COLLAPSE = "iv_collapse"
    DELTA_BREACH = "delta_breach"
    EXPIRATION = "expiration"
    MANUAL = "manual"


@dataclass
class IVDataPoint:
    """Single data point from historical IV time series."""

    date: date
    symbol: str
    atm_iv: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    hv30: Optional[float] = None
    skew: Optional[float] = None
    term_m1_m2: Optional[float] = None
    term_m1_m3: Optional[float] = None
    spot_price: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], symbol: str) -> "IVDataPoint":
        """Create IVDataPoint from dictionary (IV daily summary format)."""
        date_str = data.get("date", "")
        try:
            dt = date.fromisoformat(date_str) if date_str else None
        except ValueError:
            dt = None

        # Support both new (IV) and legacy (HV) field names for backward compatibility
        iv_rank_raw = data.get("iv_rank (IV)") or data.get("iv_rank (HV)")
        iv_percentile_raw = data.get("iv_percentile (IV)") or data.get("iv_percentile (HV)")

        return cls(
            date=dt,
            symbol=symbol,
            atm_iv=data.get("atm_iv"),
            iv_rank=iv_rank_raw,
            iv_percentile=iv_percentile_raw,
            hv30=data.get("hv30"),
            skew=data.get("skew"),
            term_m1_m2=data.get("term_m1_m2"),
            term_m1_m3=data.get("term_m1_m3"),
            spot_price=data.get("spot_price"),
        )

    def is_valid(self) -> bool:
        """Check if this data point has minimum required data."""
        return (
            self.date is not None
            and self.atm_iv is not None
            and self.iv_percentile is not None
        )


@dataclass
class EntrySignal:
    """Entry signal detected by the SignalGenerator."""

    date: date
    symbol: str
    iv_at_entry: float
    iv_rank_at_entry: Optional[float]
    iv_percentile_at_entry: float
    hv_at_entry: Optional[float]
    skew_at_entry: Optional[float]
    term_at_entry: Optional[float]
    spot_at_entry: Optional[float]
    signal_strength: float = 0.0  # Composite score 0-100


@dataclass
class SimulatedTrade:
    """A simulated trade through its lifecycle."""

    # Entry information
    entry_date: date
    symbol: str
    strategy_type: str
    iv_at_entry: float
    iv_percentile_at_entry: float
    iv_rank_at_entry: Optional[float]
    spot_at_entry: Optional[float]
    target_expiry: date  # Based on target DTE at entry

    # Position sizing
    max_risk: float  # Always $200 in MVP
    estimated_credit: float  # Estimated credit received
    num_contracts: int = 1  # Number of contracts

    # Current state
    status: TradeStatus = TradeStatus.OPEN
    current_pnl: float = 0.0
    days_in_trade: int = 0

    # Exit information (filled when closed)
    exit_date: Optional[date] = None
    exit_reason: Optional[ExitReason] = None
    iv_at_exit: Optional[float] = None
    spot_at_exit: Optional[float] = None
    final_pnl: float = 0.0

    # Tracking
    pnl_history: List[float] = field(default_factory=list)
    iv_history: List[float] = field(default_factory=list)
    spot_history: List[float] = field(default_factory=list)  # For Greeks-based model
    date_history: List[date] = field(default_factory=list)  # Actual dates for each history entry

    # Greeks tracking (for GreeksBasedPnLModel)
    greeks_at_entry: Optional[Any] = None  # GreeksSnapshot at entry
    greeks_history: List[Any] = field(default_factory=list)  # Daily Greeks updates

    def close(
        self,
        exit_date: date,
        exit_reason: ExitReason,
        final_pnl: float,
        iv_at_exit: Optional[float] = None,
        spot_at_exit: Optional[float] = None,
    ) -> None:
        """Close the trade with final values."""
        self.status = TradeStatus.CLOSED
        self.exit_date = exit_date
        self.exit_reason = exit_reason
        self.final_pnl = final_pnl
        self.iv_at_exit = iv_at_exit
        self.spot_at_exit = spot_at_exit

    def is_winner(self) -> bool:
        """Check if trade was profitable."""
        return self.final_pnl > 0

    def return_on_risk(self) -> float:
        """Calculate return on risk (P&L / max risk)."""
        if self.max_risk == 0:
            return 0.0
        return self.final_pnl / self.max_risk


@dataclass
class PerformanceMetrics:
    """Performance metrics for a backtest period."""

    # Basic metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    # P&L metrics
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    average_pnl: float = 0.0
    average_winner: float = 0.0
    average_loser: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # Return metrics
    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    volatility: float = 0.0
    calmar_ratio: Optional[float] = None
    ret_dd: Optional[float] = None  # Return to Drawdown ratio (Total Return % / Max Drawdown %)

    # System quality metrics
    sqn: float = 0.0  # System Quality Number (Van Tharp)

    # Trade metrics
    avg_days_in_trade: float = 0.0
    avg_days_winner: float = 0.0
    avg_days_loser: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Exit reason breakdown
    exits_by_reason: Dict[str, int] = field(default_factory=dict)

    # Per-symbol breakdown
    metrics_by_symbol: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """Complete results from a backtest run."""

    # Configuration used
    config_summary: Dict[str, Any] = field(default_factory=dict)

    # Date ranges
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    in_sample_end_date: Optional[date] = None

    # All trades
    trades: List[SimulatedTrade] = field(default_factory=list)

    # Metrics for different periods
    in_sample_metrics: Optional[PerformanceMetrics] = None
    out_sample_metrics: Optional[PerformanceMetrics] = None
    combined_metrics: Optional[PerformanceMetrics] = None

    # Equity curve data
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)

    # Validation metrics
    degradation_score: Optional[float] = None  # How much performance degraded out-of-sample (None if no OOS data)
    is_valid: bool = True  # Whether backtest passed validation checks
    validation_messages: List[str] = field(default_factory=list)

    def get_in_sample_trades(self) -> List[SimulatedTrade]:
        """Get trades from in-sample period."""
        if self.in_sample_end_date is None:
            return []
        return [
            t
            for t in self.trades
            if t.entry_date <= self.in_sample_end_date
        ]

    def get_out_sample_trades(self) -> List[SimulatedTrade]:
        """Get trades from out-of-sample period."""
        if self.in_sample_end_date is None:
            return self.trades
        return [
            t
            for t in self.trades
            if t.entry_date > self.in_sample_end_date
        ]

    def summary(self) -> Dict[str, Any]:
        """Generate a summary dict for reporting."""
        return {
            "total_trades": len(self.trades),
            "date_range": f"{self.start_date} to {self.end_date}",
            "in_sample_trades": len(self.get_in_sample_trades()),
            "out_sample_trades": len(self.get_out_sample_trades()),
            "degradation_score": self.degradation_score,
            "is_valid": self.is_valid,
            "combined_metrics": {
                "total_pnl": self.combined_metrics.total_pnl if self.combined_metrics else 0,
                "win_rate": self.combined_metrics.win_rate if self.combined_metrics else 0,
                "sharpe_ratio": self.combined_metrics.sharpe_ratio if self.combined_metrics else 0,
                "max_drawdown": self.combined_metrics.max_drawdown if self.combined_metrics else 0,
            } if self.combined_metrics else {},
        }


__all__ = [
    "TradeStatus",
    "ExitReason",
    "IVDataPoint",
    "EntrySignal",
    "SimulatedTrade",
    "PerformanceMetrics",
    "BacktestResult",
]
