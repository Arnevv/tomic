import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { ManagementData } from '../types';

export function Management() {
  const { data, loading, error, refetch } = useApi<ManagementData>(() => api.getManagement());

  if (loading) {
    return <div className="loading">Loading exit management...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: 'var(--status-error)' }}>Error loading management data: {error.message}</p>
        <button className="btn btn-primary" onClick={refetch} style={{ marginTop: 'var(--space-md)' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const getStatusStyle = (status: string) => {
    if (status.includes('Beheer')) {
      return {
        background: 'var(--status-warning)',
        color: 'var(--bg-primary)',
        padding: '4px 8px',
        borderRadius: 'var(--radius-sm)',
        fontWeight: '600',
      };
    }
    return {
      color: 'var(--status-healthy)',
    };
  };

  const formatExpiry = (expiry: string | null) => {
    if (!expiry) return '-';
    // Format YYYYMMDD to readable date
    const year = expiry.slice(0, 4);
    const month = expiry.slice(4, 6);
    const day = expiry.slice(6, 8);
    return `${day}/${month}/${year}`;
  };

  const formatPnl = (value: number | null) => {
    if (value === null) return '-';
    const formatted = value >= 0 ? `+$${value.toFixed(0)}` : `-$${Math.abs(value).toFixed(0)}`;
    return <span className={value >= 0 ? 'pnl-positive' : 'pnl-negative'}>{formatted}</span>;
  };

  const needsAttention = data.strategies.filter(s => s.status.includes('Beheer'));
  const holding = data.strategies.filter(s => !s.status.includes('Beheer'));

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Exit Management</h2>
        <button className="btn btn-primary" onClick={refetch}>
          Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid-2" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card" style={{ borderLeft: needsAttention.length > 0 ? '4px solid var(--status-warning)' : '4px solid var(--status-healthy)' }}>
          <div className="card-header">
            <span className="card-title">Needs Attention</span>
            <span className="badge badge-warning">{needsAttention.length}</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: '700', color: needsAttention.length > 0 ? 'var(--status-warning)' : 'var(--status-healthy)' }}>
            {needsAttention.length > 0 ? 'Action Required' : 'All Clear'}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Portfolio Status</span>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-xl)' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Total Strategies</div>
              <div className="mono" style={{ fontSize: '24px' }}>{data.total_strategies}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Holding</div>
              <div className="mono" style={{ fontSize: '24px', color: 'var(--status-healthy)' }}>{holding.length}</div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Exit Alerts</div>
              <div className="mono" style={{ fontSize: '24px', color: needsAttention.length > 0 ? 'var(--status-warning)' : 'var(--text-muted)' }}>{needsAttention.length}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Strategies Needing Attention */}
      {needsAttention.length > 0 && (
        <div className="card" style={{ marginBottom: 'var(--space-lg)', borderLeft: '4px solid var(--status-warning)' }}>
          <div className="card-header">
            <span className="card-title">Strategies Needing Attention</span>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Expiry</th>
                <th>DTE</th>
                <th>P&L</th>
                <th>Exit Trigger</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {needsAttention.map((strategy, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: '600' }}>{strategy.symbol || '-'}</td>
                  <td className="mono" style={{ fontSize: '12px' }}>{formatExpiry(strategy.expiry)}</td>
                  <td className="mono">{strategy.days_to_expiry ?? '-'}</td>
                  <td className="mono">{formatPnl(strategy.unrealized_pnl)}</td>
                  <td>
                    <span style={{
                      background: 'var(--bg-secondary)',
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px'
                    }}>
                      {strategy.exit_trigger}
                    </span>
                  </td>
                  <td>
                    <button className="btn btn-secondary" style={{ padding: '4px 12px', fontSize: '12px' }}>
                      Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* All Strategies */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">All Strategies</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Expiry</th>
              <th>DTE</th>
              <th>P&L</th>
              <th>Status</th>
              <th>Exit Trigger</th>
            </tr>
          </thead>
          <tbody>
            {data.strategies.map((strategy, i) => (
              <tr key={i}>
                <td style={{ fontWeight: '600' }}>{strategy.symbol || '-'}</td>
                <td className="mono" style={{ fontSize: '12px' }}>{formatExpiry(strategy.expiry)}</td>
                <td className="mono">{strategy.days_to_expiry ?? '-'}</td>
                <td className="mono">{formatPnl(strategy.unrealized_pnl)}</td>
                <td>
                  <span style={getStatusStyle(strategy.status)}>
                    {strategy.status}
                  </span>
                </td>
                <td style={{ color: strategy.exit_trigger === 'geen trigger' ? 'var(--text-muted)' : 'inherit' }}>
                  {strategy.exit_trigger}
                </td>
              </tr>
            ))}
            {data.strategies.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 'var(--space-xl)' }}>
                  No strategies found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
