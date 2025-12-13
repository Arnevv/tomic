import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../api/client';
import type {
  BacktestConfig,
  BacktestConfigRequest,
  BacktestJobStatus,
  BacktestResult,
  BacktestMetrics,
} from '../types';

type StrategyType = 'iron_condor' | 'calendar';

interface ParameterChange {
  key: string;
  label: string;
  liveValue: number | null;
  whatifValue: number | null;
  min: number;
  max: number;
  step: number;
  unit: string;
  category: 'entry' | 'exit' | 'position' | 'costs';
}

// Storage key for persisting job state
const STORAGE_KEY = 'whatif_jobs';

interface StoredJobState {
  liveJobId: string;
  whatifJobId: string;
  strategyType: StrategyType;
  timestamp: number;
}

function saveJobState(state: StoredJobState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function loadJobState(): StoredJobState | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return null;
    const state = JSON.parse(stored) as StoredJobState;
    // Expire after 5 minutes
    if (Date.now() - state.timestamp > 5 * 60 * 1000) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return state;
  } catch {
    return null;
  }
}

function clearJobState() {
  localStorage.removeItem(STORAGE_KEY);
}

export function WhatIf() {
  const [strategyType, setStrategyType] = useState<StrategyType>('iron_condor');
  const [liveConfig, setLiveConfig] = useState<BacktestConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // What-if parameters (modified values)
  const [whatifParams, setWhatifParams] = useState<BacktestConfigRequest>({});

  // Job tracking
  const [liveJobId, setLiveJobId] = useState<string | null>(null);
  const [whatifJobId, setWhatifJobId] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<BacktestJobStatus | null>(null);
  const [whatifStatus, setWhatifStatus] = useState<BacktestJobStatus | null>(null);
  const [liveResult, setLiveResult] = useState<BacktestResult | null>(null);
  const [whatifResult, setWhatifResult] = useState<BacktestResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  // Track if we've restored from storage
  const hasRestoredRef = useRef(false);

  // Restore job state on mount
  useEffect(() => {
    if (hasRestoredRef.current) return;
    hasRestoredRef.current = true;

    const stored = loadJobState();
    if (stored) {
      setLiveJobId(stored.liveJobId);
      setWhatifJobId(stored.whatifJobId);
      setStrategyType(stored.strategyType);
      setIsRunning(true);
    }
  }, []);

  // Load live config
  useEffect(() => {
    setLoading(true);
    setError(null);
    api.getBacktestLiveConfig(strategyType)
      .then((config) => {
        setLiveConfig(config);
        setWhatifParams({ strategy_type: strategyType });
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [strategyType]);

  // Poll for job status
  useEffect(() => {
    if (!liveJobId && !whatifJobId) return;

    let isCancelled = false;

    const poll = async () => {
      if (isCancelled) return;

      try {
        let liveIsDone = false;
        let whatifIsDone = false;

        if (liveJobId) {
          const status = await api.getBacktestStatus(liveJobId);
          if (isCancelled) return;
          setLiveStatus(status);

          if (status.status === 'completed' || status.status === 'failed') {
            liveIsDone = true;
            if (status.status === 'completed') {
              const result = await api.getBacktestResult(liveJobId);
              if (isCancelled) return;
              setLiveResult(result);
            }
          }
        } else {
          liveIsDone = true;
        }

        if (whatifJobId) {
          const status = await api.getBacktestStatus(whatifJobId);
          if (isCancelled) return;
          setWhatifStatus(status);

          if (status.status === 'completed' || status.status === 'failed') {
            whatifIsDone = true;
            if (status.status === 'completed') {
              const result = await api.getBacktestResult(whatifJobId);
              if (isCancelled) return;
              setWhatifResult(result);
            }
          }
        } else {
          whatifIsDone = true;
        }

        // Only mark as not running when BOTH are done
        if (liveIsDone && whatifIsDone) {
          setIsRunning(false);
          clearJobState();
        }
      } catch (err) {
        console.error('Polling error:', err);
      }
    };

    // Initial poll
    poll();

    // Continue polling while running
    const interval = setInterval(poll, 1000);

    return () => {
      isCancelled = true;
      clearInterval(interval);
    };
  }, [liveJobId, whatifJobId]);

  // Build parameter list based on live config
  const getParameters = useCallback((): ParameterChange[] => {
    if (!liveConfig) return [];

    const params: ParameterChange[] = [];

    // Entry rules
    if (strategyType === 'iron_condor') {
      params.push({
        key: 'entry_rules.iv_percentile_min',
        label: 'IV Percentile Min',
        liveValue: liveConfig.entry_rules.iv_percentile_min,
        whatifValue: whatifParams.entry_rules?.iv_percentile_min ?? liveConfig.entry_rules.iv_percentile_min,
        min: 0,
        max: 100,
        step: 5,
        unit: '%',
        category: 'entry',
      });
    } else {
      params.push({
        key: 'entry_rules.iv_percentile_max',
        label: 'IV Percentile Max',
        liveValue: liveConfig.entry_rules.iv_percentile_max,
        whatifValue: whatifParams.entry_rules?.iv_percentile_max ?? liveConfig.entry_rules.iv_percentile_max,
        min: 0,
        max: 100,
        step: 5,
        unit: '%',
        category: 'entry',
      });
    }

    params.push({
      key: 'entry_rules.min_days_until_earnings',
      label: 'Min Days to Earnings',
      liveValue: liveConfig.entry_rules.min_days_until_earnings,
      whatifValue: whatifParams.entry_rules?.min_days_until_earnings ?? liveConfig.entry_rules.min_days_until_earnings,
      min: 0,
      max: 30,
      step: 1,
      unit: 'd',
      category: 'entry',
    });

    // Exit rules
    params.push({
      key: 'exit_rules.profit_target_pct',
      label: 'Take Profit',
      liveValue: liveConfig.exit_rules.profit_target_pct,
      whatifValue: whatifParams.exit_rules?.profit_target_pct ?? liveConfig.exit_rules.profit_target_pct,
      min: 10,
      max: 80,
      step: 5,
      unit: '%',
      category: 'exit',
    });

    params.push({
      key: 'exit_rules.stop_loss_pct',
      label: 'Stop Loss',
      liveValue: liveConfig.exit_rules.stop_loss_pct,
      whatifValue: whatifParams.exit_rules?.stop_loss_pct ?? liveConfig.exit_rules.stop_loss_pct,
      min: 50,
      max: 300,
      step: 10,
      unit: '%',
      category: 'exit',
    });

    params.push({
      key: 'exit_rules.min_dte',
      label: 'Min DTE Exit',
      liveValue: liveConfig.exit_rules.min_dte,
      whatifValue: whatifParams.exit_rules?.min_dte ?? liveConfig.exit_rules.min_dte,
      min: 1,
      max: 21,
      step: 1,
      unit: 'd',
      category: 'exit',
    });

    params.push({
      key: 'exit_rules.max_days_in_trade',
      label: 'Max Days in Trade',
      liveValue: liveConfig.exit_rules.max_days_in_trade,
      whatifValue: whatifParams.exit_rules?.max_days_in_trade ?? liveConfig.exit_rules.max_days_in_trade,
      min: 7,
      max: 60,
      step: 1,
      unit: 'd',
      category: 'exit',
    });

    // Position sizing
    params.push({
      key: 'position_sizing.max_risk_per_trade',
      label: 'Max Risk Per Trade',
      liveValue: liveConfig.position_sizing.max_risk_per_trade,
      whatifValue: whatifParams.position_sizing?.max_risk_per_trade ?? liveConfig.position_sizing.max_risk_per_trade,
      min: 50,
      max: 1000,
      step: 50,
      unit: '$',
      category: 'position',
    });

    params.push({
      key: 'position_sizing.max_total_positions',
      label: 'Max Total Positions',
      liveValue: liveConfig.position_sizing.max_total_positions,
      whatifValue: whatifParams.position_sizing?.max_total_positions ?? liveConfig.position_sizing.max_total_positions,
      min: 1,
      max: 20,
      step: 1,
      unit: '',
      category: 'position',
    });

    // Costs
    params.push({
      key: 'costs.commission_per_contract',
      label: 'Commission',
      liveValue: liveConfig.costs.commission_per_contract,
      whatifValue: whatifParams.costs?.commission_per_contract ?? liveConfig.costs.commission_per_contract,
      min: 0,
      max: 5,
      step: 0.1,
      unit: '$/c',
      category: 'costs',
    });

    params.push({
      key: 'costs.slippage_pct',
      label: 'Slippage',
      liveValue: liveConfig.costs.slippage_pct,
      whatifValue: whatifParams.costs?.slippage_pct ?? liveConfig.costs.slippage_pct,
      min: 0,
      max: 20,
      step: 1,
      unit: '%',
      category: 'costs',
    });

    return params;
  }, [liveConfig, whatifParams, strategyType]);

  // Update a parameter value
  const updateParameter = (key: string, value: number) => {
    const parts = key.split('.');
    const category = parts[0] as 'entry_rules' | 'exit_rules' | 'position_sizing' | 'costs';
    const param = parts[1];

    setWhatifParams((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        [param]: value,
      },
    }));
  };

  // Reset to live config
  const resetToLive = () => {
    setWhatifParams({ strategy_type: strategyType });
    setLiveResult(null);
    setWhatifResult(null);
    setLiveStatus(null);
    setWhatifStatus(null);
    clearJobState();
  };

  // Start simulation
  const startSimulation = async () => {
    if (!liveConfig) return;

    setIsRunning(true);
    setLiveResult(null);
    setWhatifResult(null);
    setLiveStatus(null);
    setWhatifStatus(null);
    setError(null);

    try {
      // Start both backtests
      const comparison = await api.startWhatIfComparison({
        ...whatifParams,
        strategy_type: strategyType,
      });

      setLiveJobId(comparison.live_job_id);
      setWhatifJobId(comparison.whatif_job_id);

      // Persist job state for navigation recovery
      saveJobState({
        liveJobId: comparison.live_job_id,
        whatifJobId: comparison.whatif_job_id,
        strategyType,
        timestamp: Date.now(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start simulation');
      setIsRunning(false);
    }
  };

  // Calculate delta between metrics
  const getDelta = (live: number | null | undefined, whatif: number | null | undefined): { value: number | null; isPositive: boolean } => {
    if (live == null || whatif == null) return { value: null, isPositive: false };
    const delta = whatif - live;
    return { value: delta, isPositive: delta > 0 };
  };

  // Format metric value
  const formatMetric = (value: number | null | undefined, type: 'percent' | 'currency' | 'number' | 'ratio'): string => {
    if (value == null) return '--';
    switch (type) {
      case 'percent':
        return `${(value * 100).toFixed(1)}%`;
      case 'currency':
        return `$${value.toFixed(2)}`;
      case 'ratio':
        return value.toFixed(2);
      case 'number':
      default:
        return value.toFixed(0);
    }
  };

  // Get status badge color and text
  const getStatusBadge = (status: BacktestJobStatus | null, label: string) => {
    if (!status) {
      return { color: 'var(--text-muted)', text: `${label}: Wachten...`, icon: '○' };
    }
    switch (status.status) {
      case 'pending':
        return { color: 'var(--text-muted)', text: `${label}: In wachtrij`, icon: '○' };
      case 'running':
        return { color: 'var(--cobra-jungle-green)', text: `${label}: Bezig (${status.progress?.toFixed(0) ?? 0}%)`, icon: '◐' };
      case 'completed':
        return { color: 'var(--status-success)', text: `${label}: Voltooid`, icon: '●' };
      case 'failed':
        return { color: 'var(--status-error)', text: `${label}: Mislukt`, icon: '✕' };
      default:
        return { color: 'var(--text-muted)', text: `${label}: Onbekend`, icon: '?' };
    }
  };

  // Render metrics comparison table
  const renderMetricsComparison = () => {
    const liveMetrics = liveResult?.combined_metrics;
    const whatifMetrics = whatifResult?.combined_metrics;

    const metrics: { key: keyof BacktestMetrics; label: string; type: 'percent' | 'currency' | 'number' | 'ratio'; higherBetter: boolean }[] = [
      { key: 'win_rate', label: 'Win Rate', type: 'percent', higherBetter: true },
      { key: 'total_pnl', label: 'Total P&L', type: 'currency', higherBetter: true },
      { key: 'total_return_pct', label: 'Return', type: 'percent', higherBetter: true },
      { key: 'sharpe_ratio', label: 'Sharpe Ratio', type: 'ratio', higherBetter: true },
      { key: 'max_drawdown_pct', label: 'Max Drawdown', type: 'percent', higherBetter: false },
      { key: 'profit_factor', label: 'Profit Factor', type: 'ratio', higherBetter: true },
      { key: 'total_trades', label: 'Total Trades', type: 'number', higherBetter: true },
      { key: 'avg_days_in_trade', label: 'Avg Days in Trade', type: 'number', higherBetter: false },
      { key: 'expectancy', label: 'Expectancy', type: 'currency', higherBetter: true },
    ];

    return (
      <table className="table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Live Config</th>
            <th>What-If</th>
            <th>Delta</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => {
            const liveVal = liveMetrics?.[m.key] as number | undefined;
            const whatifVal = whatifMetrics?.[m.key] as number | undefined;
            const delta = getDelta(liveVal, whatifVal);
            const deltaIsGood = delta.value !== null && ((m.higherBetter && delta.isPositive) || (!m.higherBetter && !delta.isPositive));

            return (
              <tr key={m.key}>
                <td>{m.label}</td>
                <td className="mono">{formatMetric(liveVal, m.type)}</td>
                <td className="mono">{formatMetric(whatifVal, m.type)}</td>
                <td className={`mono ${delta.value !== null ? (deltaIsGood ? 'pnl-positive' : 'pnl-negative') : ''}`}>
                  {delta.value !== null ? (
                    <>
                      {delta.value > 0 ? '+' : ''}
                      {m.type === 'percent' ? `${(delta.value * 100).toFixed(1)}%` :
                       m.type === 'currency' ? `$${delta.value.toFixed(2)}` :
                       delta.value.toFixed(2)}
                    </>
                  ) : '--'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  };

  if (loading) {
    return <div className="loading">Loading configuration...</div>;
  }

  if (error && !isRunning) {
    return (
      <div className="card">
        <h2>Error</h2>
        <p style={{ color: 'var(--status-error)' }}>{error}</p>
        <button className="btn btn-secondary" onClick={() => window.location.reload()}>
          Retry
        </button>
      </div>
    );
  }

  const parameters = getParameters();
  const hasChanges = Object.keys(whatifParams).length > 1; // More than just strategy_type
  const hasResults = liveResult || whatifResult;
  const liveBadge = getStatusBadge(liveStatus, 'Live');
  const whatifBadge = getStatusBadge(whatifStatus, 'What-If');

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>What-If Analyse</h2>
        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button className="btn btn-secondary" onClick={resetToLive} disabled={isRunning}>
            Reset naar Live
          </button>
          <button className="btn btn-primary" onClick={startSimulation} disabled={isRunning || !hasChanges}>
            {isRunning ? 'Bezig...' : 'Simulatie Starten'}
          </button>
        </div>
      </div>

      {/* Strategy Type Selector */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Strategie Type</span>
        </div>
        <div style={{ padding: 'var(--space-md)', display: 'flex', gap: 'var(--space-md)' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)', cursor: 'pointer' }}>
            <input
              type="radio"
              name="strategy"
              checked={strategyType === 'iron_condor'}
              onChange={() => setStrategyType('iron_condor')}
              disabled={isRunning}
            />
            Iron Condor
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)', cursor: 'pointer' }}>
            <input
              type="radio"
              name="strategy"
              checked={strategyType === 'calendar'}
              onChange={() => setStrategyType('calendar')}
              disabled={isRunning}
            />
            Calendar Spread
          </label>
        </div>
      </div>

      <div className="grid-2">
        {/* Parameters Panel */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Parameters Aanpassen</span>
          </div>
          <div style={{ padding: 'var(--space-md)' }}>
            {['entry', 'exit', 'position', 'costs'].map((category) => {
              const categoryParams = parameters.filter((p) => p.category === category);
              if (categoryParams.length === 0) return null;

              const categoryLabels: Record<string, string> = {
                entry: 'Entry Rules',
                exit: 'Exit Rules',
                position: 'Position Sizing',
                costs: 'Costs',
              };

              return (
                <div key={category} style={{ marginBottom: 'var(--space-lg)' }}>
                  <h4 style={{ marginBottom: 'var(--space-sm)', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                    {categoryLabels[category]}
                  </h4>
                  {categoryParams.map((param) => {
                    const isChanged = param.whatifValue !== param.liveValue;
                    return (
                      <div key={param.key} style={{ marginBottom: 'var(--space-md)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-xs)' }}>
                          <span style={{ fontWeight: 500 }}>{param.label}</span>
                          <span
                            className="mono"
                            style={{
                              color: isChanged ? 'var(--cobra-orange)' : 'var(--text-secondary)',
                              fontWeight: isChanged ? 600 : 400,
                            }}
                          >
                            {param.whatifValue ?? '--'}{param.unit}
                            {isChanged && param.liveValue !== null && (
                              <span style={{ color: 'var(--text-muted)', marginLeft: 'var(--space-xs)' }}>
                                (live: {param.liveValue}{param.unit})
                              </span>
                            )}
                          </span>
                        </div>
                        <input
                          type="range"
                          min={param.min}
                          max={param.max}
                          step={param.step}
                          value={param.whatifValue ?? param.liveValue ?? param.min}
                          onChange={(e) => updateParameter(param.key, parseFloat(e.target.value))}
                          disabled={isRunning}
                          style={{
                            width: '100%',
                            height: '6px',
                            borderRadius: 'var(--radius-pill)',
                            background: 'var(--bg-tertiary)',
                            cursor: isRunning ? 'not-allowed' : 'pointer',
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>

        {/* Results Panel */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Vergelijking</span>
          </div>
          <div style={{ padding: 'var(--space-md)' }}>
            {/* Status indicators - always show when running or have job IDs */}
            {(isRunning || liveJobId || whatifJobId) && (
              <div style={{
                marginBottom: 'var(--space-lg)',
                padding: 'var(--space-md)',
                background: 'var(--bg-tertiary)',
                borderRadius: 'var(--radius-md)'
              }}>
                {/* Status badges */}
                <div style={{ display: 'flex', gap: 'var(--space-lg)', marginBottom: 'var(--space-md)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
                    <span style={{ color: liveBadge.color }}>{liveBadge.icon}</span>
                    <span style={{ fontSize: '0.875rem', color: liveBadge.color }}>{liveBadge.text}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
                    <span style={{ color: whatifBadge.color }}>{whatifBadge.icon}</span>
                    <span style={{ fontSize: '0.875rem', color: whatifBadge.color }}>{whatifBadge.text}</span>
                  </div>
                </div>

                {/* Progress bars */}
                {isRunning && (
                  <>
                    <div style={{ marginBottom: 'var(--space-sm)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '0.75rem' }}>
                        <span>Live Config</span>
                        <span className="mono">{(liveStatus?.progress ?? 0).toFixed(0)}%</span>
                      </div>
                      <div style={{ height: '6px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
                        <div
                          style={{
                            height: '100%',
                            width: `${liveStatus?.progress ?? 0}%`,
                            background: 'var(--cobra-oxford-blue)',
                            borderRadius: 'var(--radius-pill)',
                            transition: 'width 0.3s',
                          }}
                        />
                      </div>
                    </div>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '0.75rem' }}>
                        <span>What-If</span>
                        <span className="mono">{(whatifStatus?.progress ?? 0).toFixed(0)}%</span>
                      </div>
                      <div style={{ height: '6px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
                        <div
                          style={{
                            height: '100%',
                            width: `${whatifStatus?.progress ?? 0}%`,
                            background: 'var(--cobra-orange)',
                            borderRadius: 'var(--radius-pill)',
                            transition: 'width 0.3s',
                          }}
                        />
                      </div>
                    </div>

                    {/* Progress message */}
                    {(liveStatus?.progress_message || whatifStatus?.progress_message) && (
                      <div style={{ marginTop: 'var(--space-sm)', fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        {liveStatus?.progress_message || whatifStatus?.progress_message}
                      </div>
                    )}
                  </>
                )}

                {/* Error messages */}
                {liveStatus?.status === 'failed' && (
                  <div style={{ marginTop: 'var(--space-sm)', padding: 'var(--space-sm)', background: 'rgba(220, 53, 69, 0.1)', borderRadius: 'var(--radius-sm)', color: 'var(--status-error)', fontSize: '0.875rem' }}>
                    Live backtest mislukt: {liveStatus.error_message || 'Onbekende fout'}
                  </div>
                )}
                {whatifStatus?.status === 'failed' && (
                  <div style={{ marginTop: 'var(--space-sm)', padding: 'var(--space-sm)', background: 'rgba(220, 53, 69, 0.1)', borderRadius: 'var(--radius-sm)', color: 'var(--status-error)', fontSize: '0.875rem' }}>
                    What-if backtest mislukt: {whatifStatus.error_message || 'Onbekende fout'}
                  </div>
                )}
              </div>
            )}

            {/* Results table */}
            {hasResults && renderMetricsComparison()}

            {/* Empty state */}
            {!isRunning && !hasResults && !liveJobId && !whatifJobId && (
              <div style={{ textAlign: 'center', padding: 'var(--space-xl)', color: 'var(--text-muted)' }}>
                <p>Pas parameters aan en klik "Simulatie Starten" om de impact te zien.</p>
              </div>
            )}

            {/* Validation messages */}
            {whatifResult?.validation_messages && whatifResult.validation_messages.length > 0 && (
              <div style={{ marginTop: 'var(--space-lg)' }}>
                {whatifResult.validation_messages.map((msg, i) => (
                  <div
                    key={i}
                    style={{
                      padding: 'var(--space-sm) var(--space-md)',
                      background: msg.includes('Warning') ? 'rgba(255, 193, 7, 0.1)' : 'var(--bg-tertiary)',
                      borderRadius: 'var(--radius-sm)',
                      marginBottom: 'var(--space-xs)',
                      fontSize: '0.875rem',
                      color: msg.includes('Warning') ? '#997404' : 'var(--text-secondary)',
                    }}
                  >
                    {msg}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Config Summary */}
      {liveConfig && (
        <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-header">
            <span className="card-title">Live Config Details</span>
          </div>
          <div style={{ padding: 'var(--space-md)', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--space-md)' }}>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 'var(--space-xs)' }}>Symbolen</div>
              <div className="mono">{liveConfig.symbols.slice(0, 5).join(', ')}{liveConfig.symbols.length > 5 ? ` +${liveConfig.symbols.length - 5}` : ''}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 'var(--space-xs)' }}>Periode</div>
              <div className="mono">{liveConfig.start_date} - {liveConfig.end_date}</div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 'var(--space-xs)' }}>Target DTE</div>
              <div className="mono">{liveConfig.target_dte} dagen</div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 'var(--space-xs)' }}>Wing Width</div>
              <div className="mono">${liveConfig.iron_condor_wing_width}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
