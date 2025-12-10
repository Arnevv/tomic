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
