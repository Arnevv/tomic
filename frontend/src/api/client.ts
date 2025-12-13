// API client for TOMIC backend
import { logger } from '../utils/logger';

const API_BASE = '/api';
const apiLogger = logger.withContext('API');

// Custom error class with detailed information
export class ApiError extends Error {
  public readonly status: number;
  public readonly statusText: string;
  public readonly endpoint: string;
  public readonly method: string;
  public readonly responseBody?: unknown;
  public readonly timestamp: string;
  public readonly requestId?: string;

  constructor(params: {
    message: string;
    status: number;
    statusText: string;
    endpoint: string;
    method: string;
    responseBody?: unknown;
    requestId?: string;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.status = params.status;
    this.statusText = params.statusText;
    this.endpoint = params.endpoint;
    this.method = params.method;
    this.responseBody = params.responseBody;
    this.timestamp = new Date().toISOString();
    this.requestId = params.requestId;
  }

  toJSON() {
    return {
      name: this.name,
      message: this.message,
      status: this.status,
      statusText: this.statusText,
      endpoint: this.endpoint,
      method: this.method,
      responseBody: this.responseBody,
      timestamp: this.timestamp,
      requestId: this.requestId,
    };
  }
}

// Network error class for connection issues
export class NetworkError extends Error {
  public readonly endpoint: string;
  public readonly method: string;
  public readonly originalError: unknown;
  public readonly timestamp: string;

  constructor(params: {
    message: string;
    endpoint: string;
    method: string;
    originalError: unknown;
  }) {
    super(params.message);
    this.name = 'NetworkError';
    this.endpoint = params.endpoint;
    this.method = params.method;
    this.originalError = params.originalError;
    this.timestamp = new Date().toISOString();
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const method = options?.method || 'GET';
  const startTime = performance.now();

  apiLogger.debug(`Request: ${method} ${endpoint}`, options?.body ? { body: options.body } : undefined);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });
  } catch (err) {
    const networkError = new NetworkError({
      message: `Network error: Unable to connect to ${endpoint}`,
      endpoint,
      method,
      originalError: err,
    });
    apiLogger.error(`Network error: ${method} ${endpoint}`, networkError);
    throw networkError;
  }

  const duration = Math.round(performance.now() - startTime);

  if (!response.ok) {
    let responseBody: unknown;
    try {
      responseBody = await response.json();
    } catch {
      try {
        responseBody = await response.text();
      } catch {
        responseBody = undefined;
      }
    }

    const apiError = new ApiError({
      message: `API error: ${response.status} ${response.statusText} - ${endpoint}`,
      status: response.status,
      statusText: response.statusText,
      endpoint,
      method,
      responseBody,
      requestId: response.headers.get('x-request-id') || undefined,
    });

    apiLogger.error(`Response error: ${method} ${endpoint} [${response.status}] (${duration}ms)`, apiError, {
      responseBody,
    });

    throw apiError;
  }

  const data = await response.json();
  apiLogger.debug(`Response: ${method} ${endpoint} [${response.status}] (${duration}ms)`);

  return data;
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
  getCacheStatus: () => fetchApi<import('../types').CacheStatusData>('/system/cache-status'),
  clearCache: () => fetchApi<import('../types').ClearCacheData>('/system/clear-cache', { method: 'POST' }),
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
