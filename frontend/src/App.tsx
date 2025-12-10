import { useState } from 'react';
import { Dashboard } from './pages/Dashboard';
import { Portfolio } from './pages/Portfolio';
import { Management } from './pages/Management';
import { Scanner } from './pages/Scanner';
import { System } from './pages/System';
import { ActivityLogs } from './pages/ActivityLogs';
import { WhatIf } from './pages/WhatIf';
import { StatusBar } from './components/StatusBar';
import { api } from './api/client';
import { useApi } from './hooks/useApi';
import type { SystemHealth } from './types';

type Mode = 'monitor' | 'decide';
type MonitorView = 'dashboard' | 'portfolio' | 'manage' | 'system' | 'logs';
type DecideView = 'scanner' | 'journal' | 'whatif';

function App() {
  const [mode, setMode] = useState<Mode>('monitor');
  const [monitorView, setMonitorView] = useState<MonitorView>('dashboard');
  const [decideView, setDecideView] = useState<DecideView>('scanner');
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  const { data: health } = useApi<SystemHealth>(() => api.getHealth());

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  };

  return (
    <div className="app-layout">
      {/* Header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
          <h1 style={{ color: 'var(--cobra-orange)' }}>TOMIC</h1>
          <span className="tagline">implementing happiness</span>
        </div>

        <div className="mode-toggle">
          <button
            className={mode === 'monitor' ? 'active' : ''}
            onClick={() => setMode('monitor')}
          >
            Monitor
          </button>
          <button
            className={mode === 'decide' ? 'active' : ''}
            onClick={() => setMode('decide')}
          >
            Decide
          </button>
        </div>

        <button
          className="btn btn-secondary"
          onClick={toggleTheme}
          style={{ fontSize: '12px', padding: '6px 12px' }}
        >
          {theme === 'light' ? 'Dark' : 'Light'}
        </button>
      </header>

      {/* Main Content */}
      <div className="app-content">
        {/* Navigation Rail */}
        <nav className="nav-rail">
          {mode === 'monitor' ? (
            <>
              <div
                className={`nav-item ${monitorView === 'dashboard' ? 'active' : ''}`}
                onClick={() => setMonitorView('dashboard')}
              >
                Dashboard
              </div>
              <div
                className={`nav-item ${monitorView === 'portfolio' ? 'active' : ''}`}
                onClick={() => setMonitorView('portfolio')}
              >
                Portfolio
              </div>
              <div
                className={`nav-item ${monitorView === 'manage' ? 'active' : ''}`}
                onClick={() => setMonitorView('manage')}
              >
                Manage
              </div>
              <div
                className={`nav-item ${monitorView === 'system' ? 'active' : ''}`}
                onClick={() => setMonitorView('system')}
              >
                System
              </div>
              <div
                className={`nav-item ${monitorView === 'logs' ? 'active' : ''}`}
                onClick={() => setMonitorView('logs')}
              >
                Logs
              </div>
            </>
          ) : (
            <>
              <div
                className={`nav-item ${decideView === 'scanner' ? 'active' : ''}`}
                onClick={() => setDecideView('scanner')}
              >
                Scanner
              </div>
              <div
                className={`nav-item ${decideView === 'whatif' ? 'active' : ''}`}
                onClick={() => setDecideView('whatif')}
              >
                What-If
              </div>
              <div
                className={`nav-item ${decideView === 'journal' ? 'active' : ''}`}
                onClick={() => setDecideView('journal')}
              >
                Journal
              </div>
            </>
          )}
        </nav>

        {/* Main Content Area */}
        <main className="main-content">
          {mode === 'monitor' && monitorView === 'dashboard' && <Dashboard />}
          {mode === 'monitor' && monitorView === 'portfolio' && <Portfolio />}
          {mode === 'monitor' && monitorView === 'manage' && <Management />}
          {mode === 'monitor' && monitorView === 'system' && <System />}
          {mode === 'monitor' && monitorView === 'logs' && <ActivityLogs />}
          {mode === 'decide' && decideView === 'scanner' && <Scanner />}
          {mode === 'decide' && decideView === 'whatif' && <WhatIf />}
          {mode === 'decide' && decideView === 'journal' && (
            <div className="card">
              <h2>Trade Journal</h2>
              <p style={{ color: 'var(--text-muted)', marginTop: 'var(--space-md)' }}>
                Coming soon...
              </p>
            </div>
          )}
        </main>
      </div>

      {/* Status Bar */}
      <StatusBar health={health} />
    </div>
  );
}

export default App;
