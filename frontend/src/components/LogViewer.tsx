import { useState, useEffect } from 'react';
import { logger, LogEntry, LogLevel } from '../utils/logger';

const LEVEL_COLORS: Record<LogLevel, string> = {
  debug: 'var(--text-muted)',
  info: 'var(--accent-info)',
  warn: 'var(--status-warning)',
  error: 'var(--status-error)',
};

const LEVEL_ICONS: Record<LogLevel, string> = {
  debug: '○',
  info: 'ℹ',
  warn: '⚠',
  error: '✗',
};

export function LogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [levelFilter, setLevelFilter] = useState<LogLevel | 'all'>('all');
  const [contextFilter, setContextFilter] = useState<string>('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // Get unique contexts from logs
  const contexts = Array.from(new Set(logs.map(l => l.context).filter(Boolean))) as string[];

  const refreshLogs = () => {
    const allLogs = logger.getLogs();
    setLogs(allLogs);
  };

  useEffect(() => {
    refreshLogs();

    if (autoRefresh) {
      const interval = setInterval(refreshLogs, 2000);
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  const filteredLogs = logs.filter(log => {
    if (levelFilter !== 'all' && log.level !== levelFilter) return false;
    if (contextFilter !== 'all' && log.context !== contextFilter) return false;
    return true;
  }).slice(-100).reverse(); // Show most recent first

  const handleClear = () => {
    logger.clearLogs();
    setLogs([]);
  };

  const handleDownload = () => {
    logger.downloadLogs();
  };

  const toggleExpand = (index: number) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  const levelCounts = {
    error: logs.filter(l => l.level === 'error').length,
    warn: logs.filter(l => l.level === 'warn').length,
    info: logs.filter(l => l.level === 'info').length,
    debug: logs.filter(l => l.level === 'debug').length,
  };

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">Frontend Logs</span>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          {/* Level counts */}
          <div style={{ display: 'flex', gap: 'var(--space-sm)', marginRight: 'var(--space-md)' }}>
            {levelCounts.error > 0 && (
              <span style={{ color: LEVEL_COLORS.error, fontSize: '12px' }}>
                {levelCounts.error} errors
              </span>
            )}
            {levelCounts.warn > 0 && (
              <span style={{ color: LEVEL_COLORS.warn, fontSize: '12px' }}>
                {levelCounts.warn} warnings
              </span>
            )}
          </div>
          <button
            className={`btn ${autoRefresh ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setAutoRefresh(!autoRefresh)}
            style={{ padding: '4px 12px', fontSize: '12px' }}
          >
            {autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleDownload}
            style={{ padding: '4px 12px', fontSize: '12px' }}
          >
            Download
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleClear}
            style={{ padding: '4px 12px', fontSize: '12px' }}
          >
            Clear
          </button>
        </div>
      </div>

      {/* Filters */}
      <div style={{
        display: 'flex',
        gap: 'var(--space-md)',
        padding: 'var(--space-sm) 0',
        marginBottom: 'var(--space-sm)',
        borderBottom: '1px solid var(--border-color)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Level:</span>
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as LogLevel | 'all')}
            style={{
              padding: '4px 8px',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              fontSize: '12px',
            }}
          >
            <option value="all">All</option>
            <option value="error">Error</option>
            <option value="warn">Warning</option>
            <option value="info">Info</option>
            <option value="debug">Debug</option>
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Context:</span>
          <select
            value={contextFilter}
            onChange={(e) => setContextFilter(e.target.value)}
            style={{
              padding: '4px 8px',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              fontSize: '12px',
            }}
          >
            <option value="all">All</option>
            {contexts.map(ctx => (
              <option key={ctx} value={ctx}>{ctx}</option>
            ))}
          </select>
        </div>
        <span style={{ color: 'var(--text-muted)', fontSize: '12px', marginLeft: 'auto' }}>
          {filteredLogs.length} of {logs.length} logs
        </span>
      </div>

      {/* Log entries */}
      <div style={{
        maxHeight: '400px',
        overflow: 'auto',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
      }}>
        {filteredLogs.length === 0 ? (
          <div style={{
            padding: 'var(--space-xl)',
            textAlign: 'center',
            color: 'var(--text-muted)',
          }}>
            No logs to display
          </div>
        ) : (
          filteredLogs.map((log, index) => (
            <div
              key={index}
              style={{
                padding: 'var(--space-xs) var(--space-sm)',
                borderBottom: '1px solid var(--border-color)',
                background: log.level === 'error' ? 'rgba(220, 53, 69, 0.05)' :
                            log.level === 'warn' ? 'rgba(255, 193, 7, 0.05)' : 'transparent',
                cursor: (log.data !== undefined || log.error) ? 'pointer' : 'default',
              }}
              onClick={() => (log.data !== undefined || log.error) && toggleExpand(index)}
            >
              {/* Main log line */}
              <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}>
                <span style={{ color: 'var(--text-muted)', minWidth: '70px' }}>
                  {formatTime(log.timestamp)}
                </span>
                <span style={{
                  color: LEVEL_COLORS[log.level],
                  minWidth: '20px',
                }}>
                  {LEVEL_ICONS[log.level]}
                </span>
                {log.context && (
                  <span style={{
                    color: 'var(--accent-info)',
                    minWidth: '60px',
                  }}>
                    [{log.context}]
                  </span>
                )}
                <span style={{ flex: 1, wordBreak: 'break-word' }}>
                  {log.message}
                </span>
                {(log.data !== undefined || log.error) && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {expanded.has(index) ? '▼' : '▶'}
                  </span>
                )}
              </div>

              {/* Expanded details */}
              {expanded.has(index) && (log.data !== undefined || log.error) && (
                <div style={{
                  marginTop: 'var(--space-sm)',
                  marginLeft: '90px',
                  padding: 'var(--space-sm)',
                  background: 'var(--bg-secondary)',
                  borderRadius: 'var(--radius-sm)',
                  overflow: 'auto',
                }}>
                  {log.error && (
                    <div style={{ marginBottom: log.data !== undefined ? 'var(--space-sm)' : 0 }}>
                      <div style={{ color: LEVEL_COLORS.error, marginBottom: 'var(--space-xs)' }}>
                        {log.error.name}: {log.error.message}
                      </div>
                      {log.error.stack && (
                        <pre style={{
                          margin: 0,
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          whiteSpace: 'pre-wrap',
                        }}>
                          {log.error.stack.split('\n').slice(1, 5).join('\n')}
                        </pre>
                      )}
                    </div>
                  )}
                  {log.data !== undefined && (
                    <pre style={{
                      margin: 0,
                      fontSize: '11px',
                      color: 'var(--text-secondary)',
                      whiteSpace: 'pre-wrap',
                    }}>
                      {JSON.stringify(log.data, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
