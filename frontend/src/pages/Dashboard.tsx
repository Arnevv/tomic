import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { DashboardData } from '../types';

export function Dashboard() {
  const { data, loading, error, refetch } = useApi<DashboardData>(() => api.getDashboard(), []);

  if (loading) {
    return <div className="loading">Loading dashboard...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: 'var(--status-error)' }}>Error loading dashboard: {error.message}</p>
        <button className="btn btn-primary" onClick={refetch} style={{ marginTop: 'var(--space-md)' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { health, portfolio_summary, batch_jobs, alerts } = data;

  const getHealthIcon = (status: string) => {
    switch (status) {
      case 'healthy': return '✓';
      case 'warning': return '⚠';
      case 'error': return '✗';
      default: return '?';
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Dashboard</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
          Last refresh: just now
        </span>
      </div>

      {/* Health Cards Row */}
      <div className="grid-3" style={{ marginBottom: 'var(--space-lg)' }}>
        {/* System Health Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">System Health</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <span className={`status-dot ${health.ib_gateway.status}`} />
              IB Gateway
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <span className={`status-dot ${health.data_sync.status}`} />
              Data Sync
            </div>
            <div style={{
              marginTop: 'var(--space-sm)',
              padding: 'var(--space-sm)',
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '13px'
            }}>
              {health.overall === 'healthy' ? 'All Systems ✓' : 'Issues Detected'}
            </div>
          </div>
        </div>

        {/* Portfolio Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Portfolio</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            <div>
              <span style={{ fontSize: '24px', fontWeight: '600' }}>{portfolio_summary.total_positions}</span>
              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>Positions</span>
            </div>
            {portfolio_summary.greeks && (
              <div style={{ display: 'flex', gap: 'var(--space-md)', fontSize: '13px' }}>
                <span>Δ {portfolio_summary.greeks.delta?.toFixed(1) ?? '-'}</span>
                <span>θ ${portfolio_summary.greeks.theta?.toFixed(0) ?? '-'}/day</span>
              </div>
            )}
            {portfolio_summary.total_unrealized_pnl !== null && (
              <div className={portfolio_summary.total_unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                P&L: ${portfolio_summary.total_unrealized_pnl.toFixed(2)}
              </div>
            )}
          </div>
        </div>

        {/* Alerts Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Today's Alerts</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <span style={{ color: 'var(--status-warning)' }}>⚠</span>
              {alerts.filter(a => a.level === 'warning').length} Warnings
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <span style={{ color: 'var(--status-error)' }}>✗</span>
              {alerts.filter(a => a.level === 'error').length} Errors
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <span style={{ color: 'var(--accent-info)' }}>ℹ</span>
              {alerts.filter(a => a.level === 'info').length} Info
            </div>
          </div>
        </div>
      </div>

      {/* Batch Status Table */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Batch Status</span>
          <button className="btn btn-secondary" onClick={refetch}>
            Refresh
          </button>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Last Run</th>
              <th>Status</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {batch_jobs.map((job, i) => (
              <tr key={i}>
                <td>{job.name}</td>
                <td className="mono" style={{ fontSize: '12px' }}>
                  {job.last_run ? new Date(job.last_run).toLocaleTimeString() : '-'}
                </td>
                <td>
                  <span className={`status-dot ${job.status === 'success' ? 'healthy' : job.status}`} />
                  {job.status}
                </td>
                <td style={{ color: 'var(--text-secondary)' }}>{job.message || '-'}</td>
              </tr>
            ))}
            {batch_jobs.length === 0 && (
              <tr>
                <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                  No batch jobs found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Alerts List */}
      {alerts.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Active Alerts</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {alerts.map((alert) => (
              <div
                key={alert.id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 'var(--space-sm)',
                  padding: 'var(--space-sm)',
                  background: 'var(--bg-secondary)',
                  borderRadius: 'var(--radius-sm)',
                  borderLeft: `3px solid var(--status-${alert.level === 'warning' ? 'warning' : alert.level === 'error' ? 'error' : 'neutral'})`,
                }}
              >
                <span>
                  {alert.level === 'warning' ? '⚠' : alert.level === 'error' ? '✗' : 'ℹ'}
                </span>
                <div>
                  {alert.symbol && <strong>{alert.symbol}: </strong>}
                  {alert.message}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
