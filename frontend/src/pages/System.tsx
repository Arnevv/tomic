import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { SystemHealth, BatchJobsData, SystemConfigData } from '../types';

export function System() {
  const { data: health, loading: healthLoading, refetch: refetchHealth } = useApi<SystemHealth>(() => api.getHealth());
  const { data: batchJobs, loading: jobsLoading, refetch: refetchJobs } = useApi<BatchJobsData>(() => api.getBatchJobs());
  const { data: config, loading: configLoading } = useApi<SystemConfigData>(() => api.getSystemConfig());

  const loading = healthLoading || jobsLoading || configLoading;

  const handleRefreshAll = () => {
    refetchHealth();
    refetchJobs();
  };

  if (loading) {
    return <div className="loading">Loading system status...</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>System</h2>
        <button className="btn btn-primary" onClick={handleRefreshAll}>
          Refresh All
        </button>
      </div>

      {/* Service Status Cards */}
      <div className="grid-2" style={{ marginBottom: 'var(--space-lg)' }}>
        {/* IB Gateway Status */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">IB Gateway</span>
            <span className={`status-dot ${health?.ib_gateway.status || 'warning'}`} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            <div style={{
              padding: 'var(--space-md)',
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-sm)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Status</span>
                <span style={{
                  color: health?.ib_gateway.status === 'healthy' ? 'var(--status-healthy)' :
                    health?.ib_gateway.status === 'warning' ? 'var(--status-warning)' : 'var(--status-error)',
                  fontWeight: '500'
                }}>
                  {health?.ib_gateway.status === 'healthy' ? 'Connected' :
                    health?.ib_gateway.status === 'warning' ? 'Warning' : 'Disconnected'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Message</span>
                <span>{health?.ib_gateway.message || '-'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>Last Check</span>
                <span className="mono" style={{ fontSize: '12px' }}>
                  {health?.ib_gateway.last_check
                    ? new Date(health.ib_gateway.last_check).toLocaleString()
                    : '-'}
                </span>
              </div>
            </div>
            {config && (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                <div>Host: {config.ib_settings.host}:{config.ib_settings.port}</div>
                <div>Mode: {config.ib_settings.paper_mode ? 'Paper Trading' : 'Live Trading'}</div>
              </div>
            )}
          </div>
        </div>

        {/* Data Sync Status */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Data Sync</span>
            <span className={`status-dot ${health?.data_sync.status || 'warning'}`} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            <div style={{
              padding: 'var(--space-md)',
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-sm)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Status</span>
                <span style={{
                  color: health?.data_sync.status === 'healthy' ? 'var(--status-healthy)' :
                    health?.data_sync.status === 'warning' ? 'var(--status-warning)' : 'var(--status-error)',
                  fontWeight: '500'
                }}>
                  {health?.data_sync.status === 'healthy' ? 'Synced' :
                    health?.data_sync.status === 'warning' ? 'Stale' : 'Error'}
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-sm)' }}>
                <span style={{ color: 'var(--text-muted)' }}>Message</span>
                <span>{health?.data_sync.message || '-'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: 'var(--text-muted)' }}>Last Check</span>
                <span className="mono" style={{ fontSize: '12px' }}>
                  {health?.data_sync.last_check
                    ? new Date(health.data_sync.last_check).toLocaleString()
                    : '-'}
                </span>
              </div>
            </div>
            {config && (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                <div>Provider: {config.data_settings.data_provider.toUpperCase()}</div>
                <div>Log Level: {config.data_settings.log_level}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Batch Jobs Table */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Batch Jobs</span>
          <button className="btn btn-secondary" onClick={refetchJobs}>
            Refresh
          </button>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Job</th>
              <th>Status</th>
              <th>Last Run</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {batchJobs?.jobs.map((job, i) => (
              <tr key={i}>
                <td style={{ fontWeight: '500' }}>{job.name}</td>
                <td>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 'var(--space-xs)',
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    background: job.status === 'success' ? 'rgba(25, 135, 84, 0.1)' :
                      job.status === 'warning' ? 'rgba(255, 193, 7, 0.1)' :
                        job.status === 'error' ? 'rgba(220, 53, 69, 0.1)' : 'rgba(108, 117, 125, 0.1)',
                    color: job.status === 'success' ? 'var(--status-healthy)' :
                      job.status === 'warning' ? 'var(--status-warning)' :
                        job.status === 'error' ? 'var(--status-error)' : 'var(--text-secondary)',
                  }}>
                    <span className={`status-dot ${job.status === 'success' ? 'healthy' : job.status}`} />
                    {job.status}
                  </span>
                </td>
                <td className="mono" style={{ fontSize: '12px' }}>
                  {job.last_run ? new Date(job.last_run).toLocaleString() : '-'}
                </td>
                <td style={{ color: 'var(--text-secondary)' }}>{job.message || '-'}</td>
              </tr>
            ))}
            {(!batchJobs || batchJobs.jobs.length === 0) && (
              <tr>
                <td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                  No batch jobs found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Configuration Section */}
      {config && (
        <div className="grid-2">
          {/* IB Configuration */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">IB Configuration</span>
              <span className="badge badge-info" style={{ fontSize: '10px' }}>Read-only</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
              <ConfigRow label="Host" value={config.ib_settings.host} />
              <ConfigRow label="Port" value={config.ib_settings.port} />
              <ConfigRow label="Live Port" value={config.ib_settings.live_port} />
              <ConfigRow label="Client ID" value={config.ib_settings.client_id} />
              <ConfigRow label="Market Data ID" value={config.ib_settings.marketdata_client_id} />
              <ConfigRow label="Paper Mode" value={config.ib_settings.paper_mode ? 'Yes' : 'No'} />
              <ConfigRow label="Fetch Only" value={config.ib_settings.fetch_only ? 'Yes' : 'No'} />
            </div>
          </div>

          {/* Trading Configuration */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Trading Configuration</span>
              <span className="badge badge-info" style={{ fontSize: '10px' }}>Read-only</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
              <ConfigRow label="Order Type" value={config.trading_settings.default_order_type} />
              <ConfigRow label="Time in Force" value={config.trading_settings.default_time_in_force} />
              <ConfigRow label="Strike Range" value={config.trading_settings.strike_range} />
              <ConfigRow label="Regular Expiries" value={config.trading_settings.amount_regulars} />
              <ConfigRow label="Weekly Expiries" value={config.trading_settings.amount_weeklies} />
              <ConfigRow label="Min DTE" value={config.trading_settings.first_expiry_min_dte} />
              <ConfigRow label="Max Open Trades" value={config.trading_settings.entry_flow_max_open_trades} />
              <ConfigRow label="Dry Run" value={config.trading_settings.entry_flow_dry_run ? 'Yes' : 'No'} />
            </div>
          </div>
        </div>
      )}

      {/* Symbols List */}
      {config && config.symbols.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-header">
            <span className="card-title">Monitored Symbols</span>
            <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>{config.symbols.length} symbols</span>
          </div>
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 'var(--space-sm)',
          }}>
            {config.symbols.map((symbol) => (
              <span
                key={symbol}
                style={{
                  padding: '4px 12px',
                  background: 'var(--bg-secondary)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '13px',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {symbol}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string | number | boolean }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      padding: 'var(--space-xs) 0',
      borderBottom: '1px solid var(--border-color)',
    }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="mono" style={{ fontSize: '13px' }}>{String(value)}</span>
    </div>
  );
}
