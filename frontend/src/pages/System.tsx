import { useState } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { LogViewer } from '../components/LogViewer';
import type { SystemHealth, BatchJobsData, SystemConfigData, GitHubWorkflowRun, CacheStatusData, CacheFileInfo } from '../types';

type JobKey = 'exit_check' | 'entry_flow' | 'portfolio_sync';

const JOB_KEYS: Record<string, JobKey> = {
  'Exit Check': 'exit_check',
  'Entry Flow': 'entry_flow',
  'Portfolio Sync': 'portfolio_sync',
};

export function System() {
  const { data: health, loading: healthLoading, refetch: refetchHealth } = useApi<SystemHealth>(() => api.getHealth());
  const { data: batchJobs, loading: jobsLoading, refetch: refetchJobs } = useApi<BatchJobsData>(() => api.getBatchJobs());
  const { data: config, loading: configLoading } = useApi<SystemConfigData>(() => api.getSystemConfig());
  const { data: githubWorkflow, refetch: refetchGithub } = useApi<GitHubWorkflowRun>(() => api.getGitHubWorkflowStatus());
  const { data: cacheStatus, loading: cacheLoading, refetch: refetchCache } = useApi<CacheStatusData>(() => api.getCacheStatus());

  const [runningJobs, setRunningJobs] = useState<Set<string>>(new Set());
  const [clearingCache, setClearingCache] = useState(false);

  const loading = healthLoading || jobsLoading || configLoading;

  const handleRefreshAll = () => {
    refetchHealth();
    refetchJobs();
    refetchGithub();
    refetchCache();
  };

  const handleClearCache = async () => {
    if (!confirm('Are you sure you want to clear all cache files? This will delete liquidity_cache.json, sector_mapping.json, and symbol_metadata.json. They will be rebuilt on next use.')) {
      return;
    }

    setClearingCache(true);
    try {
      const response = await api.clearCache();
      if (response.success) {
        alert(`Success: ${response.message}\n\nCleared files:\n${response.cleared_files.join('\n')}`);
      } else {
        alert(`Warning: ${response.message}\n\nErrors:\n${response.errors.join('\n')}`);
      }
      refetchCache();
    } catch (error) {
      alert(`Error clearing cache: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      setClearingCache(false);
    }
  };

  const handleRunJob = async (jobName: string) => {
    const jobKey = JOB_KEYS[jobName];
    if (!jobKey) return;

    setRunningJobs(prev => new Set(prev).add(jobName));

    try {
      const response = await api.runBatchJob(jobKey);

      // If already running, just start polling
      if (response.status === 'running' || response.status === 'started') {
        // Poll until job completes (max 10 minutes with 3 second intervals)
        const maxAttempts = 200; // 10 minutes / 3 seconds
        let attempts = 0;

        const pollInterval = setInterval(async () => {
          attempts++;
          const jobs = await api.getBatchJobs();
          const job = jobs.jobs.find(j => j.name === jobName);

          // Stop polling if job is no longer running or max attempts reached
          if (!job || job.status !== 'running' || attempts >= maxAttempts) {
            clearInterval(pollInterval);
            setRunningJobs(prev => {
              const next = new Set(prev);
              next.delete(jobName);
              return next;
            });
            refetchJobs();
          }
        }, 3000); // Poll every 3 seconds
      } else {
        // Job failed to start
        setRunningJobs(prev => {
          const next = new Set(prev);
          next.delete(jobName);
          return next;
        });
        refetchJobs();
      }
    } catch (error) {
      setRunningJobs(prev => {
        const next = new Set(prev);
        next.delete(jobName);
        return next;
      });
      refetchJobs();
    }
  };

  if (loading) {
    return <div className="loading">Loading system status...</div>;
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'success':
      case 'healthy':
        return 'var(--status-healthy)';
      case 'warning':
      case 'queued':
        return 'var(--status-warning)';
      case 'error':
      case 'failure':
        return 'var(--status-error)';
      case 'running':
        return 'var(--accent-info)';
      default:
        return 'var(--text-secondary)';
    }
  };

  const getStatusBg = (status: string) => {
    switch (status) {
      case 'success':
        return 'rgba(25, 135, 84, 0.1)';
      case 'warning':
      case 'queued':
        return 'rgba(255, 193, 7, 0.1)';
      case 'error':
      case 'failure':
        return 'rgba(220, 53, 69, 0.1)';
      case 'running':
        return 'rgba(13, 110, 253, 0.1)';
      default:
        return 'rgba(108, 117, 125, 0.1)';
    }
  };

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
              <th style={{ width: '100px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {batchJobs?.jobs.map((job, i) => {
              const isRunning = runningJobs.has(job.name);
              const canRun = JOB_KEYS[job.name] !== undefined;

              return (
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
                      background: isRunning ? getStatusBg('running') : getStatusBg(job.status),
                      color: isRunning ? getStatusColor('running') : getStatusColor(job.status),
                    }}>
                      <span className={`status-dot ${isRunning ? 'running' : (job.status === 'success' ? 'healthy' : job.status)}`} />
                      {isRunning ? 'running' : job.status}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: '12px' }}>
                    {job.last_run ? new Date(job.last_run).toLocaleString() : '-'}
                  </td>
                  <td style={{ color: 'var(--text-secondary)' }}>{job.message || '-'}</td>
                  <td>
                    {canRun && (
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '4px 12px', fontSize: '12px' }}
                        onClick={() => handleRunJob(job.name)}
                        disabled={isRunning}
                      >
                        {isRunning ? 'Running...' : 'Run'}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}

            {/* GitHub Actions Row */}
            {githubWorkflow && (
              <tr>
                <td style={{ fontWeight: '500' }}>
                  {githubWorkflow.workflow_name}
                  <span style={{
                    marginLeft: 'var(--space-sm)',
                    padding: '2px 6px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '10px',
                    background: 'var(--bg-secondary)',
                    color: 'var(--text-muted)',
                  }}>
                    GitHub Actions
                  </span>
                </td>
                <td>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 'var(--space-xs)',
                    padding: '2px 8px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '12px',
                    background: getStatusBg(githubWorkflow.status),
                    color: getStatusColor(githubWorkflow.status),
                  }}>
                    <span className={`status-dot ${githubWorkflow.status === 'success' ? 'healthy' : githubWorkflow.status === 'failure' ? 'error' : 'warning'}`} />
                    {githubWorkflow.status}
                  </span>
                </td>
                <td className="mono" style={{ fontSize: '12px' }}>
                  {githubWorkflow.completed_at
                    ? new Date(githubWorkflow.completed_at).toLocaleString()
                    : githubWorkflow.started_at
                      ? new Date(githubWorkflow.started_at).toLocaleString()
                      : '-'}
                </td>
                <td style={{ color: 'var(--text-secondary)' }}>
                  {githubWorkflow.conclusion || 'Scheduled: 4:00, 6:00, 8:00 UTC'}
                </td>
                <td>
                  {githubWorkflow.html_url && (
                    <a
                      href={githubWorkflow.html_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary"
                      style={{ padding: '4px 12px', fontSize: '12px', textDecoration: 'none' }}
                    >
                      View
                    </a>
                  )}
                </td>
              </tr>
            )}

            {(!batchJobs || batchJobs.jobs.length === 0) && !githubWorkflow && (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                  No batch jobs found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Cache Management Section */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Cache Management</span>
          <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
            <button className="btn btn-secondary" onClick={refetchCache} disabled={cacheLoading}>
              {cacheLoading ? 'Loading...' : 'Refresh'}
            </button>
            <button
              className="btn btn-danger"
              onClick={handleClearCache}
              disabled={clearingCache}
            >
              {clearingCache ? 'Clearing...' : 'Clear Cache'}
            </button>
          </div>
        </div>
        {cacheStatus && (
          <div>
            <div style={{
              padding: 'var(--space-md)',
              background: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 'var(--space-md)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: '500' }}>Total Cache Size</span>
                <span style={{
                  fontSize: '18px',
                  fontWeight: '600',
                  color: 'var(--accent-info)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {cacheStatus.total_size_human}
                </span>
              </div>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Cache File</th>
                  <th>Size</th>
                  <th>Last Modified</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {cacheStatus.files.map((file: CacheFileInfo) => (
                  <tr key={file.name}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>{file.name}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>{file.size_human}</td>
                    <td className="mono" style={{ fontSize: '12px' }}>
                      {file.last_modified
                        ? new Date(file.last_modified).toLocaleString()
                        : '-'}
                    </td>
                    <td>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 'var(--space-xs)',
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                        background: file.exists ? 'rgba(25, 135, 84, 0.1)' : 'rgba(108, 117, 125, 0.1)',
                        color: file.exists ? 'var(--status-healthy)' : 'var(--text-secondary)',
                      }}>
                        <span className={`status-dot ${file.exists ? 'healthy' : 'warning'}`} />
                        {file.exists ? 'exists' : 'not found'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{
              marginTop: 'var(--space-md)',
              padding: 'var(--space-sm)',
              background: 'rgba(13, 110, 253, 0.1)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '13px',
              color: 'var(--text-secondary)',
            }}>
              <strong>Note:</strong> Clearing cache will delete these files. They will be automatically regenerated when needed, which may take a few minutes during the next data sync.
            </div>
          </div>
        )}
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

      {/* Frontend Logs */}
      <div style={{ marginTop: 'var(--space-lg)' }}>
        <LogViewer />
      </div>
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
