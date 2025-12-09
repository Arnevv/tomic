import type { SystemHealth } from '../types';

interface StatusBarProps {
  health: SystemHealth | null;
}

export function StatusBar({ health }: StatusBarProps) {
  const getStatusClass = (status: string) => {
    switch (status) {
      case 'healthy': return 'healthy';
      case 'warning': return 'warning';
      case 'error': return 'error';
      default: return '';
    }
  };

  return (
    <footer className="status-bar">
      <div className="status-bar-item">
        <span className={`status-dot ${getStatusClass(health?.ib_gateway?.status || 'warning')}`} />
        IB: {health?.ib_gateway?.message || 'Checking...'}
      </div>

      <div className="status-bar-item">
        <span className={`status-dot ${getStatusClass(health?.data_sync?.status || 'warning')}`} />
        Data: {health?.data_sync?.message || 'Checking...'}
      </div>

      <div className="status-bar-item">
        Last refresh: just now
      </div>
    </footer>
  );
}
