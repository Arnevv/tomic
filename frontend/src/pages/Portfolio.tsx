import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { PortfolioSummary, Position } from '../types';

export function Portfolio() {
  const { data, loading, error, refetch } = useApi<PortfolioSummary>(() => api.getPortfolio(), []);

  if (loading) {
    return <div className="loading">Loading portfolio...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: 'var(--status-error)' }}>Error loading portfolio: {error.message}</p>
        <button className="btn btn-primary" onClick={refetch} style={{ marginTop: 'var(--space-md)' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const getStatusBadge = (status: Position['status']) => {
    switch (status) {
      case 'tp_ready':
        return <span className="badge badge-warning">TP Ready</span>;
      case 'monitor':
        return <span className="badge" style={{ background: 'var(--accent-info)', color: 'white' }}>Monitor</span>;
      case 'exit':
        return <span className="badge badge-error">Exit</span>;
      default:
        return <span style={{ color: 'var(--status-healthy)' }}>● Normal</span>;
    }
  };

  const formatPnl = (value: number | null) => {
    if (value === null) return '-';
    const formatted = value >= 0 ? `+$${value.toFixed(2)}` : `-$${Math.abs(value).toFixed(2)}`;
    return <span className={value >= 0 ? 'pnl-positive' : 'pnl-negative'}>{formatted}</span>;
  };

  const formatPnlPercent = (value: number | null) => {
    if (value === null) return '-';
    const formatted = value >= 0 ? `+${value.toFixed(1)}%` : `${value.toFixed(1)}%`;
    return <span className={value >= 0 ? 'pnl-positive' : 'pnl-negative'}>{formatted}</span>;
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Portfolio</h2>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            Synced: {data.last_sync ? new Date(data.last_sync).toLocaleTimeString() : 'Never'}
          </span>
          <button className="btn btn-primary" onClick={refetch}>
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid-2" style={{ marginBottom: 'var(--space-lg)' }}>
        {/* Greeks Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Portfolio Greeks</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-md)' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Delta</div>
              <div className="mono" style={{ fontSize: '18px' }}>
                {data.greeks?.delta?.toFixed(1) ?? '-'}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Gamma</div>
              <div className="mono" style={{ fontSize: '18px' }}>
                {data.greeks?.gamma?.toFixed(3) ?? '-'}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Theta</div>
              <div className="mono" style={{ fontSize: '18px' }}>
                {data.greeks?.theta !== null ? `$${data.greeks.theta.toFixed(0)}/day` : '-'}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Vega</div>
              <div className="mono" style={{ fontSize: '18px' }}>
                {data.greeks?.vega?.toFixed(0) ?? '-'}
              </div>
            </div>
          </div>
        </div>

        {/* Risk Summary */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Risk Summary</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-muted)' }}>Positions</span>
              <span className="mono">{data.total_positions}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-muted)' }}>Margin Used</span>
              <span className="mono">{data.margin_used_pct ? `${data.margin_used_pct.toFixed(0)}%` : '-'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: 'var(--text-muted)' }}>Total P&L</span>
              <span className="mono">{formatPnl(data.total_unrealized_pnl)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Positions Table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Positions</span>
          <button className="btn btn-secondary">
            Export CSV
          </button>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Entry</th>
              <th>DTE</th>
              <th>P&L</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((pos, i) => (
              <tr key={i} style={{ cursor: 'pointer' }}>
                <td style={{ fontWeight: '600' }}>{pos.symbol}</td>
                <td>{pos.strategy || '-'}</td>
                <td className="mono" style={{ fontSize: '12px' }}>
                  {pos.entry_date || '-'}
                </td>
                <td className="mono">
                  {pos.days_to_expiry !== null ? pos.days_to_expiry : '-'}
                </td>
                <td className="mono">
                  {formatPnlPercent(pos.pnl_percent)}
                </td>
                <td>{getStatusBadge(pos.status)}</td>
              </tr>
            ))}
            {data.positions.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 'var(--space-xl)' }}>
                  No open positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Alerts Section */}
      {data.positions.some(p => p.alerts.length > 0) && (
        <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-header">
            <span className="card-title">Position Alerts</span>
          </div>
          {data.positions
            .filter(p => p.alerts.length > 0)
            .map((pos, i) => (
              <div key={i} style={{ marginBottom: 'var(--space-sm)' }}>
                {pos.alerts.map((alert, j) => (
                  <div
                    key={j}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-sm)',
                      padding: 'var(--space-sm)',
                      background: 'var(--bg-secondary)',
                      borderRadius: 'var(--radius-sm)',
                      borderLeft: '3px solid var(--status-warning)',
                      marginBottom: 'var(--space-xs)',
                    }}
                  >
                    <span>⚠</span>
                    <strong>{pos.symbol}:</strong> {alert}
                  </div>
                ))}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
