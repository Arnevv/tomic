import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import type { SystemData } from '../types';

export function System() {
  const { data, loading, error, refetch } = useApi<SystemData>(() => api.getSystem());

  if (loading) {
    return <div className="loading">Loading system status...</div>;
  }

  if (error) {
    return (
      <div className="card">
        <p style={{ color: 'var(--status-error)' }}>Error loading system: {error.message}</p>
        <button className="btn btn-primary" onClick={refetch} style={{ marginTop: 'var(--space-md)' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online':
      case 'success':
        return 'var(--status-healthy)';
      case 'warning':
        return 'var(--status-warning)';
      case 'offline':
      case 'error':
        return 'var(--status-error)';
      default:
        return 'var(--text-muted)';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'online':
      case 'success':
        return '●';
      case 'warning':
        return '◐';
      case 'offline':
      case 'error':
        return '○';
      case 'running':
        return '◌';
      default:
        return '?';
    }
  };

  // Group config items by category
  const configByCategory = data.config.reduce((acc, item) => {
    if (!acc[item.category]) acc[item.category] = [];
    acc[item.category].push(item);
    return acc;
  }, {} as Record<string, typeof data.config>);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>System Status</h2>
        <button className="btn btn-primary" onClick={refetch}>
          Refresh
        </button>
      </div>

      {/* Services Status */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Services</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 'var(--space-md)' }}>
          {data.services.map((service, i) => (
            <div
              key={i}
              style={{
                padding: 'var(--space-md)',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-sm)',
                borderLeft: `4px solid ${getStatusColor(service.status)}`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: '600' }}>{service.name}</span>
                <span style={{ color: getStatusColor(service.status), fontSize: '18px' }}>
                  {getStatusIcon(service.status)}
                </span>
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: 'var(--space-xs)' }}>
                {service.message || service.status}
              </div>
              {service.last_check && (
                <div style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: 'var(--space-xs)' }}>
                  Last check: {new Date(service.last_check).toLocaleTimeString()}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Batch Jobs */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Background Jobs</span>
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
            {data.batch_jobs.map((job, i) => (
              <tr key={i}>
                <td style={{ fontWeight: '500' }}>{job.name}</td>
                <td>
                  <span style={{ color: getStatusColor(job.status) }}>
                    {getStatusIcon(job.status)} {job.status}
                  </span>
                </td>
                <td className="mono" style={{ fontSize: '12px' }}>
                  {job.last_run ? new Date(job.last_run).toLocaleTimeString() : '-'}
                </td>
                <td style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                  {job.message || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Configuration */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Configuration</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--space-lg)' }}>
          {Object.entries(configByCategory).map(([category, items]) => (
            <div key={category}>
              <h4 style={{ marginBottom: 'var(--space-sm)', color: 'var(--text-muted)', fontSize: '12px', textTransform: 'uppercase' }}>
                {category}
              </h4>
              <div style={{ background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                {items.map((item, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      padding: 'var(--space-sm) var(--space-md)',
                      borderBottom: i < items.length - 1 ? '1px solid var(--border-color)' : 'none',
                    }}
                  >
                    <span>{item.key}</span>
                    <span className="mono" style={{ color: 'var(--text-muted)', fontSize: '13px', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* System Info */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">System Information</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 'var(--space-md)' }}>
          {Object.entries(data.system_info).map(([key, value]) => (
            <div key={key} style={{ padding: 'var(--space-sm)' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: '12px', marginBottom: '2px' }}>
                {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
              </div>
              <div className="mono">{value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
