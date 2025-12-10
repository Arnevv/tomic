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
