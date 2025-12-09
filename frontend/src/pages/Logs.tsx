import { useState, useCallback } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { LogsData } from '../types';

export function Logs() {
  const [levelFilter, setLevelFilter] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('');

  const fetchLogs = useCallback(() => {
    return api.getLogs({
      level: levelFilter || undefined,
      category: categoryFilter || undefined,
      limit: 50,
    });
  }, [levelFilter, categoryFilter]);

  const { data, loading, error, refetch } = useApi<LogsData>(fetchLogs);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'error':
        return 'var(--status-error)';
      case 'warning':
        return 'var(--status-warning)';
      case 'info':
      default:
        return 'var(--accent-info)';
    }
  };

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'error':
        return '!';
      case 'warning':
        return '?';
      case 'info':
      default:
        return 'i';
    }
  };

  const applyFilters = () => {
    refetch();
  };

  const clearFilters = () => {
    setLevelFilter('');
    setCategoryFilter('');
  };

  if (loading) {
    return <div className="loading">Loading activity logs...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: 'var(--status-error)' }}>Error loading logs: {error.message}</p>
        <button className="btn btn-primary" onClick={refetch} style={{ marginTop: 'var(--space-md)' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Activity Logs</h2>
        <button className="btn btn-primary" onClick={refetch}>
          Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
        <div className="card" style={{ textAlign: 'center', padding: 'var(--space-md)' }}>
          <div style={{ fontSize: '28px', fontWeight: '700' }}>{data.total_entries}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Total Entries</div>
        </div>
        <div className="card" style={{ textAlign: 'center', padding: 'var(--space-md)' }}>
          <div style={{ fontSize: '28px', fontWeight: '700', color: 'var(--status-warning)' }}>{data.warning_count}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Warnings</div>
        </div>
        <div className="card" style={{ textAlign: 'center', padding: 'var(--space-md)' }}>
          <div style={{ fontSize: '28px', fontWeight: '700', color: 'var(--status-error)' }}>{data.error_count}</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Errors</div>
        </div>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Filters</span>
          <button className="btn btn-secondary" onClick={clearFilters} style={{ fontSize: '12px', padding: '4px 12px' }}>
            Clear
          </button>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Level
            </label>
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              style={{
                padding: '8px 12px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                minWidth: '120px',
              }}
            >
              <option value="">All Levels</option>
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="error">Error</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Category
            </label>
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              style={{
                padding: '8px 12px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                minWidth: '120px',
              }}
            >
              <option value="">All Categories</option>
              <option value="system">System</option>
              <option value="data">Data</option>
              <option value="analysis">Analysis</option>
              <option value="connection">Connection</option>
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary" onClick={applyFilters}>
              Apply
            </button>
          </div>
        </div>
      </div>

      {/* Log Entries */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Recent Activity</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            Showing {data.entries.length} of {data.total_entries}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', background: 'var(--border-color)' }}>
          {data.entries.map((entry, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 'var(--space-md)',
                padding: 'var(--space-md)',
                background: 'var(--bg-primary)',
              }}
            >
              <div
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  background: getLevelColor(entry.level),
                  color: 'white',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '12px',
                  fontWeight: '700',
                  flexShrink: 0,
                }}
              >
                {getLevelIcon(entry.level)}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-sm)' }}>
                  <span style={{ fontWeight: '500' }}>{entry.message}</span>
                  <span className="mono" style={{ color: 'var(--text-muted)', fontSize: '11px', flexShrink: 0 }}>
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                {entry.category && (
                  <span
                    style={{
                      display: 'inline-block',
                      marginTop: '4px',
                      padding: '2px 8px',
                      background: 'var(--bg-secondary)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '11px',
                      color: 'var(--text-muted)',
                    }}
                  >
                    {entry.category}
                  </span>
                )}
              </div>
            </div>
          ))}
          {data.entries.length === 0 && (
            <div style={{ padding: 'var(--space-xl)', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-primary)' }}>
              No log entries found
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
