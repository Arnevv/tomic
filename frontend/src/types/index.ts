// API Types matching backend models

export interface HealthStatus {
  component: string;
  status: 'healthy' | 'warning' | 'error';
  message: string | null;
  last_check: string | null;
}

export interface SystemHealth {
  ib_gateway: HealthStatus;
  data_sync: HealthStatus;
  overall: 'healthy' | 'warning' | 'error';
}

export interface PortfolioGreeks {
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
}

export interface PositionLeg {
  symbol: string;
  right: string | null;
  strike: number | null;
  expiry: string | null;
  position: number;
  avg_cost: number | null;
}

export interface Position {
  symbol: string;
  strategy: string | null;
  legs: PositionLeg[];
  entry_date: string | null;
  entry_credit: number | null;
  current_value: number | null;
  unrealized_pnl: number | null;
  pnl_percent: number | null;
  days_to_expiry: number | null;
  status: 'normal' | 'monitor' | 'tp_ready' | 'exit';
  alerts: string[];
  greeks: PortfolioGreeks | null;
}

export interface PortfolioSummary {
  positions: Position[];
  total_positions: number;
  greeks: PortfolioGreeks | null;
  margin_used_pct: number | null;
  total_unrealized_pnl: number | null;
  last_sync: string | null;
}

export interface BatchJob {
  name: string;
  last_run: string | null;
  status: 'success' | 'warning' | 'error' | 'running';
  next_run: string | null;
  message: string | null;
}

export interface Alert {
  id: string;
  level: 'info' | 'warning' | 'error';
  message: string;
  symbol: string | null;
  created_at: string;
  dismissed: boolean;
}

export interface RecentActivity {
  timestamp: string;
  message: string;
  category: string | null;
}

export interface DashboardData {
  health: SystemHealth;
  portfolio_summary: PortfolioSummary;
  batch_jobs: BatchJob[];
  alerts: Alert[];
  recent_activity: RecentActivity[];
}

export interface JournalTrade {
  trade_id: string;
  symbol: string;
  strategy: string | null;
  entry_date: string | null;
  exit_date: string | null;
  entry_credit: number | null;
  exit_debit: number | null;
  pnl: number | null;
  pnl_percent: number | null;
  status: string;
  notes: string | null;
}

export interface JournalData {
  trades: JournalTrade[];
  total_trades: number;
  open_trades: number;
  closed_trades: number;
}

export interface StrategyManagement {
  symbol: string | null;
  expiry: string | null;
  strategy: string | null;
  spot: number | null;
  unrealized_pnl: number | null;
  days_to_expiry: number | null;
  exit_trigger: string;
  status: string;
}

export interface ManagementData {
  strategies: StrategyManagement[];
  total_strategies: number;
  needs_attention: number;
}

export interface ScannerSymbol {
  symbol: string;
  spot: number | null;
  iv: number | null;
  iv_rank: number | null;
  hv30: number | null;
  iv_hv_ratio: number | null;
  days_to_earnings: number | null;
  score: number | null;
  score_label: string | null;
  recommended_strategies: string[];
  last_updated: string | null;
}

export interface ScannerData {
  symbols: ScannerSymbol[];
  total_symbols: number;
  scan_time: string | null;
  filters_applied: Record<string, unknown>;
}

// Phase 2C - System & Monitoring Types

export interface BatchJobsData {
  jobs: BatchJob[];
  total_jobs: number;
}

export interface SystemConfigData {
  ib_settings: {
    host: string;
    port: number;
    live_port: number;
    paper_mode: boolean;
    fetch_only: boolean;
    client_id: number;
    marketdata_client_id: number;
  };
  data_settings: {
    positions_file: string;
    journal_file: string;
    export_dir: string;
    data_provider: string;
    log_level: string;
  };
  symbols: string[];
  trading_settings: {
    default_order_type: string;
    default_time_in_force: string;
    strike_range: number;
    amount_regulars: number;
    amount_weeklies: number;
    first_expiry_min_dte: number;
    entry_flow_max_open_trades: number;
    entry_flow_dry_run: boolean;
  };
}

export interface ActivityLogEntry {
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'success';
  message: string;
  category: string;
  source_file: string | null;
}

export interface ActivityLogsData {
  entries: ActivityLogEntry[];
  total_entries: number;
  categories: string[];
}

export interface JobRunResponse {
  job_name: string;
  status: 'started' | 'running' | 'error';
  message: string;
}

export interface GitHubWorkflowRun {
  workflow_name: string;
  status: 'success' | 'failure' | 'running' | 'queued' | 'unknown';
  conclusion: string | null;
  started_at: string | null;
  completed_at: string | null;
  html_url: string | null;
}

// === Backtest Types ===

export interface BacktestEntryRules {
  iv_percentile_min: number | null;
  iv_percentile_max: number | null;
  iv_rank_min: number | null;
  iv_rank_max: number | null;
  dte_min: number | null;
  dte_max: number | null;
  min_days_until_earnings: number | null;
}

export interface BacktestExitRules {
  profit_target_pct: number;
  stop_loss_pct: number;
  min_dte: number;
  max_days_in_trade: number;
  iv_collapse_threshold: number | null;
  delta_breach_threshold: number | null;
}

export interface BacktestPositionSizing {
  max_risk_per_trade: number;
  max_positions_per_symbol: number;
  max_total_positions: number;
}

export interface BacktestCosts {
  commission_per_contract: number;
  slippage_pct: number;
}

export interface BacktestConfig {
  strategy_type: 'iron_condor' | 'calendar';
  symbols: string[];
  start_date: string;
  end_date: string;
  target_dte: number;
  entry_rules: BacktestEntryRules;
  exit_rules: BacktestExitRules;
  position_sizing: BacktestPositionSizing;
  costs: BacktestCosts;
  iron_condor_wing_width: number;
  iron_condor_short_delta: number;
  calendar_near_dte: number;
  calendar_far_dte: number;
}

export interface BacktestConfigRequest {
  strategy_type?: 'iron_condor' | 'calendar';
  symbols?: string[];
  start_date?: string;
  end_date?: string;
  target_dte?: number;
  entry_rules?: Partial<BacktestEntryRules>;
  exit_rules?: Partial<BacktestExitRules>;
  position_sizing?: Partial<BacktestPositionSizing>;
  costs?: Partial<BacktestCosts>;
  iron_condor_wing_width?: number;
  iron_condor_short_delta?: number;
  calendar_near_dte?: number;
  calendar_far_dte?: number;
}

export interface BacktestMetrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  average_pnl: number;
  average_winner: number;
  average_loser: number;
  profit_factor: number;
  expectancy: number;
  total_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  calmar_ratio: number | null;
  sqn: number;
  avg_days_in_trade: number;
  exits_by_reason: Record<string, number>;
}

export interface BacktestTrade {
  entry_date: string;
  exit_date: string | null;
  symbol: string;
  strategy_type: string;
  iv_at_entry: number;
  iv_at_exit: number | null;
  spot_at_entry: number | null;
  spot_at_exit: number | null;
  max_risk: number;
  estimated_credit: number;
  final_pnl: number;
  exit_reason: string | null;
  days_in_trade: number;
}

export interface EquityCurvePoint {
  date: string;
  equity: number;
  cumulative_pnl: number;
  trade_pnl: number | null;
  symbol: string | null;
}

export interface BacktestJobStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  progress_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface BacktestResult {
  job_id: string;
  status: string;
  config_summary: Record<string, unknown>;
  start_date: string | null;
  end_date: string | null;
  in_sample_metrics: BacktestMetrics | null;
  out_sample_metrics: BacktestMetrics | null;
  combined_metrics: BacktestMetrics | null;
  equity_curve: EquityCurvePoint[];
  trades: BacktestTrade[];
  degradation_score: number | null;
  is_valid: boolean;
  validation_messages: string[];
}

export interface WhatIfComparison {
  live_job_id: string;
  whatif_job_id: string;
  live_status: string;
  whatif_status: string;
}
