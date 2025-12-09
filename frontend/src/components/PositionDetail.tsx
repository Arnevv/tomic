import type { Position } from '../types';

interface PositionDetailProps {
  position: Position;
  onClose: () => void;
}

export function PositionDetail({ position, onClose }: PositionDetailProps) {
  const formatExpiry = (expiry: string | null) => {
    if (!expiry) return '-';
    const year = expiry.slice(0, 4);
    const month = expiry.slice(4, 6);
    const day = expiry.slice(6, 8);
    return `${day}/${month}/${year}`;
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

  // Calculate max profit and max loss for vertical spreads
  const calculateRiskReward = () => {
    if (position.legs.length !== 2) return null;

    const strikes = position.legs.map(l => l.strike).filter(s => s !== null) as number[];
    if (strikes.length !== 2) return null;

    const width = Math.abs(strikes[1] - strikes[0]) * 100; // Contract multiplier
    const credit = position.entry_credit || 0;

    return {
      maxProfit: credit,
      maxLoss: width - credit,
      breakeven: Math.min(...strikes) + (credit / 100),
    };
  };

  const riskReward = calculateRiskReward();

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: '600px',
          maxHeight: '80vh',
          overflow: 'auto',
          margin: 'var(--space-lg)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
          <div>
            <h2 style={{ margin: 0 }}>{position.symbol}</h2>
            <span style={{ color: 'var(--text-muted)' }}>{position.strategy || 'Unknown Strategy'}</span>
          </div>
          <button
            className="btn btn-secondary"
            onClick={onClose}
            style={{ padding: '8px 16px' }}
          >
            Close
          </button>
        </div>

        {/* Summary Row */}
        <div className="grid-2" style={{ marginBottom: 'var(--space-lg)' }}>
          <div style={{ background: 'var(--bg-secondary)', padding: 'var(--space-md)', borderRadius: 'var(--radius-sm)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Entry Credit</div>
            <div className="mono" style={{ fontSize: '20px' }}>
              ${position.entry_credit?.toFixed(2) ?? '-'}
            </div>
          </div>
          <div style={{ background: 'var(--bg-secondary)', padding: 'var(--space-md)', borderRadius: 'var(--radius-sm)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Current P&L</div>
            <div className="mono" style={{ fontSize: '20px' }}>
              {formatPnl(position.unrealized_pnl)} ({formatPnlPercent(position.pnl_percent)})
            </div>
          </div>
        </div>

        {/* Position Info */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Entry Date</div>
            <div className="mono">{position.entry_date || '-'}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Days to Expiry</div>
            <div className="mono">{position.days_to_expiry ?? '-'}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Delta</div>
            <div className="mono" style={{ color: position.greeks?.delta && position.greeks.delta > 0 ? 'var(--status-healthy)' : 'inherit' }}>
              {position.greeks?.delta?.toFixed(1) ?? '-'}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Theta</div>
            <div className="mono" style={{ color: position.greeks?.theta && position.greeks.theta > 0 ? 'var(--status-healthy)' : 'inherit' }}>
              {position.greeks?.theta ? `$${position.greeks.theta.toFixed(0)}/day` : '-'}
            </div>
          </div>
        </div>

        {/* Risk/Reward for Verticals */}
        {riskReward && (
          <div style={{ background: 'var(--bg-secondary)', padding: 'var(--space-md)', borderRadius: 'var(--radius-sm)', marginBottom: 'var(--space-lg)' }}>
            <div style={{ fontWeight: '600', marginBottom: 'var(--space-sm)' }}>Risk/Reward</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-md)' }}>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Max Profit</div>
                <div className="mono pnl-positive">${riskReward.maxProfit.toFixed(2)}</div>
              </div>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Max Loss</div>
                <div className="mono pnl-negative">-${riskReward.maxLoss.toFixed(2)}</div>
              </div>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Breakeven</div>
                <div className="mono">${riskReward.breakeven.toFixed(2)}</div>
              </div>
            </div>
          </div>
        )}

        {/* Legs Table */}
        <div>
          <div style={{ fontWeight: '600', marginBottom: 'var(--space-sm)' }}>Legs</div>
          <table className="table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Strike</th>
                <th>Expiry</th>
                <th>Qty</th>
              </tr>
            </thead>
            <tbody>
              {position.legs.map((leg, i) => (
                <tr key={i}>
                  <td>
                    <span style={{
                      background: leg.right === 'P' ? 'var(--accent-warning)' : 'var(--accent-info)',
                      color: 'white',
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                    }}>
                      {leg.right === 'P' ? 'PUT' : leg.right === 'C' ? 'CALL' : leg.right || '-'}
                    </span>
                  </td>
                  <td className="mono">${leg.strike?.toFixed(2) ?? '-'}</td>
                  <td className="mono" style={{ fontSize: '12px' }}>{formatExpiry(leg.expiry)}</td>
                  <td className="mono" style={{ color: leg.position < 0 ? 'var(--status-error)' : 'var(--status-healthy)' }}>
                    {leg.position > 0 ? '+' : ''}{leg.position}
                  </td>
                </tr>
              ))}
              {position.legs.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                    No legs data available
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Alerts */}
        {position.alerts.length > 0 && (
          <div style={{ marginTop: 'var(--space-lg)' }}>
            <div style={{ fontWeight: '600', marginBottom: 'var(--space-sm)' }}>Alerts</div>
            {position.alerts.map((alert, i) => (
              <div
                key={i}
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
                {alert}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
