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
