import { useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { ActivityLogsData } from '../types';

type LogLevel = 'all' | 'info' | 'warning' | 'error' | 'success';
type LogCategory = 'all' | 'exit_flow' | 'entry_flow';

export function ActivityLogs() {
  const [levelFilter, setLevelFilter] = useState<LogLevel>('all');
  const [categoryFilter, setCategoryFilter] = useState<LogCategory>('all');

  const { data, loading, error, refetch } = useApi<ActivityLogsData>(() =>
    api.getActivityLogs({
      category: categoryFilter !== 'all' ? categoryFilter : undefined,
      level: levelFilter !== 'all' ? levelFilter : undefined,
      limit: 200,
    }),
    [levelFilter, categoryFilter]
  );

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

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'error': return '✗';
      case 'warning': return '⚠';
      case 'success': return '✓';
      default: return 'ℹ';
    }
  };

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'error': return 'var(--status-error)';
      case 'warning': return 'var(--status-warning)';
      case 'success': return 'var(--status-healthy)';
      default: return 'var(--accent-info)';
    }
  };

  const getCategoryLabel = (category: string) => {
    switch (category) {
      case 'exit_flow': return 'Exit Check';
      case 'entry_flow': return 'Entry Flow';
      case 'portfolio': return 'Portfolio';
      default: return category;
    }
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleString();
  };

  // Group entries by source file for better readability
  const groupedEntries = data?.entries.reduce((acc, entry) => {
    const key = entry.source_file || 'unknown';
    if (!acc[key]) {
      acc[key] = [];
    }
    acc[key].push(entry);
    return acc;
  }, {} as Record<string, typeof data.entries>) || {};

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Activity Logs</h2>
        <button className="btn btn-primary" onClick={refetch}>
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div style={{ display: 'flex', gap: 'var(--space-lg)', flexWrap: 'wrap' }}>
          {/* Category Filter */}
          <div>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', color: 'var(--text-muted)', fontSize: '12px' }}>
              Category
            </label>
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value as LogCategory)}
              style={{
                padding: 'var(--space-sm) var(--space-md)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                fontSize: '14px',
              }}
            >
              <option value="all">All Categories</option>
              <option value="exit_flow">Exit Check</option>
              <option value="entry_flow">Entry Flow</option>
            </select>
          </div>

          {/* Level Filter */}
          <div>
            <label style={{ display: 'block', marginBottom: 'var(--space-xs)', color: 'var(--text-muted)', fontSize: '12px' }}>
              Level
            </label>
            <select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value as LogLevel)}
              style={{
                padding: 'var(--space-sm) var(--space-md)',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                fontSize: '14px',
              }}
            >
              <option value="all">All Levels</option>
              <option value="error">Errors Only</option>
              <option value="warning">Warnings Only</option>
              <option value="success">Success Only</option>
              <option value="info">Info Only</option>
            </select>
          </div>

          {/* Summary */}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 'var(--space-md)', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
              {data?.total_entries || 0} entries
            </span>
            {data && data.entries.filter(e => e.level === 'error').length > 0 && (
              <span style={{
                padding: '2px 8px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(220, 53, 69, 0.1)',
                color: 'var(--status-error)',
                fontSize: '12px',
              }}>
                {data.entries.filter(e => e.level === 'error').length} errors
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Log Entries by Source File */}
      {Object.entries(groupedEntries).length > 0 ? (
        Object.entries(groupedEntries).map(([sourceFile, entries]) => (
          <div key={sourceFile} className="card" style={{ marginBottom: 'var(--space-md)' }}>
            <div className="card-header">
              <span className="card-title" style={{ fontSize: '14px' }}>
                {sourceFile}
              </span>
              <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
                <span style={{
                  padding: '2px 8px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-secondary)',
                  fontSize: '11px',
                  color: 'var(--text-secondary)',
                }}>
                  {getCategoryLabel(entries[0]?.category || '')}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                  {formatTimestamp(entries[0]?.timestamp || '')}
                </span>
              </div>
            </div>
            <div style={{
              maxHeight: '300px',
              overflowY: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              lineHeight: '1.6',
            }}>
              {entries.map((entry, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    gap: 'var(--space-sm)',
                    padding: 'var(--space-xs) var(--space-sm)',
                    background: entry.level === 'error' ? 'rgba(220, 53, 69, 0.05)' :
                      entry.level === 'warning' ? 'rgba(255, 193, 7, 0.05)' :
                        entry.level === 'success' ? 'rgba(25, 135, 84, 0.05)' : 'transparent',
                    borderLeft: `2px solid ${getLevelColor(entry.level)}`,
                  }}
                >
                  <span style={{ color: getLevelColor(entry.level), width: '16px', textAlign: 'center' }}>
                    {getLevelIcon(entry.level)}
                  </span>
                  <span style={{
                    color: entry.level === 'error' ? 'var(--status-error)' :
                      entry.level === 'warning' ? 'var(--text-primary)' : 'var(--text-secondary)',
                    wordBreak: 'break-word',
                  }}>
                    {entry.message}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))
      ) : (
        <div className="card">
          <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-muted)' }}>
            <p>No log entries found</p>
            <p style={{ fontSize: '13px', marginTop: 'var(--space-sm)' }}>
              Log files are created when batch jobs run (Exit Check, Entry Flow)
            </p>
          </div>
        </div>
      )}

      {/* Quick Stats */}
      {data && data.entries.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-header">
            <span className="card-title">Log Summary</span>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-xl)' }}>
            <div>
              <span style={{ color: 'var(--status-error)', marginRight: 'var(--space-xs)' }}>✗</span>
              <span style={{ fontWeight: '600' }}>{data.entries.filter(e => e.level === 'error').length}</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>Errors</span>
            </div>
            <div>
              <span style={{ color: 'var(--status-warning)', marginRight: 'var(--space-xs)' }}>⚠</span>
              <span style={{ fontWeight: '600' }}>{data.entries.filter(e => e.level === 'warning').length}</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>Warnings</span>
            </div>
            <div>
              <span style={{ color: 'var(--status-healthy)', marginRight: 'var(--space-xs)' }}>✓</span>
              <span style={{ fontWeight: '600' }}>{data.entries.filter(e => e.level === 'success').length}</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>Success</span>
            </div>
            <div>
              <span style={{ color: 'var(--accent-info)', marginRight: 'var(--space-xs)' }}>ℹ</span>
              <span style={{ fontWeight: '600' }}>{data.entries.filter(e => e.level === 'info').length}</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>Info</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
