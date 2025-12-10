// API client for TOMIC backend

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export const api = {
  getDashboard: () => fetchApi<import('../types').DashboardData>('/dashboard'),
  getHealth: () => fetchApi<import('../types').SystemHealth>('/health'),
  getPortfolio: () => fetchApi<import('../types').PortfolioSummary>('/portfolio'),
  getJournal: () => fetchApi<import('../types').JournalData>('/journal'),
  getManagement: () => fetchApi<import('../types').ManagementData>('/management'),
  getScanner: (params?: {
    min_iv_rank?: number;
    max_iv_rank?: number;
    min_score?: number;
    strategy?: string;
    sort_by?: string;
    limit?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.min_iv_rank !== undefined) searchParams.set('min_iv_rank', String(params.min_iv_rank));
    if (params?.max_iv_rank !== undefined) searchParams.set('max_iv_rank', String(params.max_iv_rank));
    if (params?.min_score !== undefined) searchParams.set('min_score', String(params.min_score));
    if (params?.strategy) searchParams.set('strategy', params.strategy);
    if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
    if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
    const query = searchParams.toString();
    return fetchApi<import('../types').ScannerData>(`/scanner${query ? `?${query}` : ''}`);
  },
  getSymbols: () => fetchApi<{ symbols: string[] }>('/symbols'),
  refreshPortfolio: () => fetchApi<{ status: string }>('/portfolio/refresh', { method: 'POST' }),

  // Phase 2C - System & Monitoring
  getBatchJobs: () => fetchApi<import('../types').BatchJobsData>('/batch-jobs'),
  getSystemConfig: () => fetchApi<import('../types').SystemConfigData>('/system/config'),
  getActivityLogs: (params?: {
    category?: string;
    level?: string;
    limit?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.category) searchParams.set('category', params.category);
    if (params?.level) searchParams.set('level', params.level);
    if (params?.limit !== undefined) searchParams.set('limit', String(params.limit));
    const query = searchParams.toString();
    return fetchApi<import('../types').ActivityLogsData>(`/activity-logs${query ? `?${query}` : ''}`);
  },

  // Batch job controls
  runBatchJob: (jobName: string) =>
    fetchApi<import('../types').JobRunResponse>(`/batch-jobs/${jobName}/run`, { method: 'POST' }),
  getGitHubWorkflowStatus: () =>
    fetchApi<import('../types').GitHubWorkflowRun>('/github/workflow-status'),

  // Backtest API
  getBacktestLiveConfig: (strategyType: 'iron_condor' | 'calendar' = 'iron_condor') =>
    fetchApi<import('../types').BacktestConfig>(`/backtest/live-config/${strategyType}`),

  startBacktest: (config: import('../types').BacktestConfigRequest) =>
    fetchApi<import('../types').BacktestJobStatus>('/backtest/run', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  getBacktestStatus: (jobId: string) =>
    fetchApi<import('../types').BacktestJobStatus>(`/backtest/status/${jobId}`),

  getBacktestResult: (jobId: string) =>
    fetchApi<import('../types').BacktestResult>(`/backtest/result/${jobId}`),

  startWhatIfComparison: (whatifConfig: import('../types').BacktestConfigRequest) =>
    fetchApi<import('../types').WhatIfComparison>('/backtest/whatif', {
      method: 'POST',
      body: JSON.stringify(whatifConfig),
    }),

  listBacktestJobs: () =>
    fetchApi<import('../types').BacktestJobStatus[]>('/backtest/jobs'),

  deleteBacktestJob: (jobId: string) =>
    fetchApi<{ status: string }>(`/backtest/jobs/${jobId}`, { method: 'DELETE' }),
};
