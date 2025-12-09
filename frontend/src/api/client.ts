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
  getSymbols: () => fetchApi<{ symbols: string[] }>('/symbols'),
  refreshPortfolio: () => fetchApi<{ status: string }>('/portfolio/refresh', { method: 'POST' }),
};
