"""Pydantic models for TOMIC Web API responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel


class HealthStatus(BaseModel):
    """System health status."""

    component: str
    status: str  # "healthy", "warning", "error"
    message: str | None = None
    last_check: datetime | None = None


class SystemHealth(BaseModel):
    """Overall system health response."""

    ib_gateway: HealthStatus
    data_sync: HealthStatus
    overall: str  # "healthy", "warning", "error"


class PortfolioGreeks(BaseModel):
    """Aggregated portfolio Greeks."""

    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


class PositionLeg(BaseModel):
    """Single leg of a position."""

    symbol: str
    right: str | None = None  # "call" or "put"
    strike: float | None = None
    expiry: str | None = None
    position: int = 0
    avg_cost: float | None = None


class Position(BaseModel):
    """Portfolio position."""

    symbol: str
    strategy: str | None = None
    legs: list[PositionLeg] = []
    entry_date: str | None = None
    entry_credit: float | None = None
    current_value: float | None = None
    unrealized_pnl: float | None = None
    pnl_percent: float | None = None
    days_to_expiry: int | None = None
    status: str = "normal"  # "normal", "monitor", "tp_ready", "exit"
    alerts: list[str] = []
    greeks: PortfolioGreeks | None = None  # Position-level Greeks


class PortfolioSummary(BaseModel):
    """Portfolio overview."""

    positions: list[Position] = []
    total_positions: int = 0
    greeks: PortfolioGreeks | None = None
    margin_used_pct: float | None = None
    total_unrealized_pnl: float | None = None
    last_sync: datetime | None = None


class BatchJob(BaseModel):
    """Background job status."""

    name: str
    last_run: datetime | None = None
    status: str  # "success", "warning", "error", "running"
    next_run: datetime | None = None
    message: str | None = None


class Alert(BaseModel):
    """System or position alert."""

    id: str
    level: str  # "info", "warning", "error"
    message: str
    symbol: str | None = None
    created_at: datetime
    dismissed: bool = False


class RecentActivity(BaseModel):
    """Recent activity log entry."""

    timestamp: datetime
    message: str
    category: str | None = None


class DashboardResponse(BaseModel):
    """Complete dashboard data."""

    health: SystemHealth
    portfolio_summary: PortfolioSummary
    batch_jobs: list[BatchJob] = []
    alerts: list[Alert] = []
    recent_activity: list[RecentActivity] = []


class JournalTrade(BaseModel):
    """Journal trade entry."""

    trade_id: str
    symbol: str
    strategy: str | None = None
    entry_date: str | None = None
    exit_date: str | None = None
    entry_credit: float | None = None
    exit_debit: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    status: str = "Open"  # "Open", "Gesloten"
    notes: str | None = None
    legs: list[dict[str, Any]] = []


class JournalResponse(BaseModel):
    """Journal data response."""

    trades: list[JournalTrade] = []
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0


class StrategyManagement(BaseModel):
    """Exit management status for a strategy."""

    symbol: str | None = None
    expiry: str | None = None
    strategy: str | None = None
    spot: float | None = None
    unrealized_pnl: float | None = None
    days_to_expiry: int | None = None
    exit_trigger: str = "geen trigger"
    status: str = "✅ Houden"  # "✅ Houden" or "⚠️ Beheer nodig"


class ManagementResponse(BaseModel):
    """Trade management overview response."""

    strategies: list[StrategyManagement] = []
    total_strategies: int = 0
    needs_attention: int = 0


class ScannerSymbol(BaseModel):
    """Symbol data for scanner view."""

    symbol: str
    spot: float | None = None
    iv: float | None = None
    iv_rank: float | None = None
    hv30: float | None = None
    iv_hv_ratio: float | None = None
    days_to_earnings: int | None = None
    score: float | None = None
    score_label: str | None = None
    recommended_strategies: list[str] = []
    last_updated: str | None = None


class ScannerResponse(BaseModel):
    """Scanner results response."""

    symbols: list[ScannerSymbol] = []
    total_symbols: int = 0
    scan_time: datetime | None = None
    filters_applied: dict[str, Any] = {}


class BatchJobsResponse(BaseModel):
    """Batch jobs overview response."""

    jobs: list[BatchJob] = []
    total_jobs: int = 0


class ConfigValue(BaseModel):
    """Single configuration value."""

    key: str
    value: Any
    category: str = "general"


class SystemConfigResponse(BaseModel):
    """System configuration response (read-only)."""

    ib_settings: dict[str, Any] = {}
    data_settings: dict[str, Any] = {}
    symbols: list[str] = []
    trading_settings: dict[str, Any] = {}


class ActivityLogEntry(BaseModel):
    """Single activity log entry."""

    timestamp: datetime
    level: str = "info"  # "info", "warning", "error", "success"
    message: str
    category: str  # "exit_flow", "entry_flow", "portfolio", "system"
    source_file: str | None = None


class ActivityLogsResponse(BaseModel):
    """Activity logs response."""

    entries: list[ActivityLogEntry] = []
    total_entries: int = 0
    categories: list[str] = []


class JobRunResponse(BaseModel):
    """Response for job run request."""

    job_name: str
    status: str  # "started", "error"
    message: str


class GitHubWorkflowRun(BaseModel):
    """GitHub Actions workflow run status."""

    workflow_name: str
    status: str  # "success", "failure", "in_progress", "queued", "unknown"
    conclusion: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    html_url: str | None = None


# === Backtest Models ===


class BacktestEntryRules(BaseModel):
    """Entry rules for backtest configuration."""

    iv_percentile_min: float | None = None
    iv_percentile_max: float | None = None
    iv_rank_min: float | None = None
    iv_rank_max: float | None = None
    dte_min: int | None = None
    dte_max: int | None = None
    min_days_until_earnings: int | None = None


class BacktestExitRules(BaseModel):
    """Exit rules for backtest configuration."""

    profit_target_pct: float = 50.0
    stop_loss_pct: float = 100.0
    min_dte: int = 5
    max_days_in_trade: int = 45
    iv_collapse_threshold: float | None = None
    delta_breach_threshold: float | None = None


class BacktestPositionSizing(BaseModel):
    """Position sizing configuration."""

    max_risk_per_trade: float = 200.0
    max_positions_per_symbol: int = 1
    max_total_positions: int = 10


class BacktestCosts(BaseModel):
    """Transaction cost configuration."""

    commission_per_contract: float = 1.0
    slippage_pct: float = 5.0


class BacktestConfigRequest(BaseModel):
    """Request model for backtest configuration (what-if parameters)."""

    strategy_type: str = "iron_condor"
    symbols: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    target_dte: int | None = None
    entry_rules: BacktestEntryRules | None = None
    exit_rules: BacktestExitRules | None = None
    position_sizing: BacktestPositionSizing | None = None
    costs: BacktestCosts | None = None
    # Iron condor specific
    iron_condor_wing_width: int | None = None
    iron_condor_short_delta: float | None = None
    # Calendar specific
    calendar_near_dte: int | None = None
    calendar_far_dte: int | None = None


class BacktestMetrics(BaseModel):
    """Performance metrics from a backtest."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    average_pnl: float = 0.0
    average_winner: float = 0.0
    average_loser: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    calmar_ratio: float | None = None
    sqn: float = 0.0
    avg_days_in_trade: float = 0.0
    exits_by_reason: dict[str, int] = {}


class BacktestTrade(BaseModel):
    """Single trade from backtest results."""

    entry_date: str
    exit_date: str | None = None
    symbol: str
    strategy_type: str
    iv_at_entry: float
    iv_at_exit: float | None = None
    spot_at_entry: float | None = None
    spot_at_exit: float | None = None
    max_risk: float
    estimated_credit: float
    final_pnl: float
    exit_reason: str | None = None
    days_in_trade: int


class EquityCurvePoint(BaseModel):
    """Single point on equity curve."""

    date: str
    equity: float
    cumulative_pnl: float
    trade_pnl: float | None = None
    symbol: str | None = None


class BacktestJobStatus(BaseModel):
    """Status of a running or completed backtest job."""

    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: float = 0.0  # 0-100
    progress_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class BacktestResultResponse(BaseModel):
    """Complete backtest result response."""

    job_id: str
    status: str
    config_summary: dict[str, Any] = {}
    start_date: str | None = None
    end_date: str | None = None
    in_sample_metrics: BacktestMetrics | None = None
    out_sample_metrics: BacktestMetrics | None = None
    combined_metrics: BacktestMetrics | None = None
    equity_curve: list[EquityCurvePoint] = []
    trades: list[BacktestTrade] = []
    degradation_score: float | None = None
    is_valid: bool = True
    validation_messages: list[str] = []


class LiveConfigResponse(BaseModel):
    """Current live configuration for what-if baseline."""

    strategy_type: str
    symbols: list[str]
    start_date: str
    end_date: str
    target_dte: int
    entry_rules: BacktestEntryRules
    exit_rules: BacktestExitRules
    position_sizing: BacktestPositionSizing
    costs: BacktestCosts
    iron_condor_wing_width: int
    iron_condor_short_delta: float
    calendar_near_dte: int
    calendar_far_dte: int


class WhatIfComparisonResponse(BaseModel):
    """Response for what-if comparison between live and modified config."""

    live_job_id: str
    whatif_job_id: str
    live_status: str
    whatif_status: str


class CacheFileInfo(BaseModel):
    """Information about a single cache file."""

    name: str
    path: str
    size_bytes: int
    size_human: str
    exists: bool
    last_modified: datetime | None = None


class CacheStatusResponse(BaseModel):
    """Cache status information."""

    files: list[CacheFileInfo]
    total_size_bytes: int
    total_size_human: str


class ClearCacheResponse(BaseModel):
    """Response after clearing cache."""

    success: bool
    message: str
    cleared_files: list[str]
    errors: list[str] = []
