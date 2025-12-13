import { useState, useCallback } from 'react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { ErrorDisplay } from '../components/ErrorDisplay';
import type { ScannerData, ScannerSymbol } from '../types';

interface FilterState {
  minIvRank: string;
  maxIvRank: string;
  minScore: string;
  strategy: string;
  sortBy: string;
}

export function Scanner() {
  const [filters, setFilters] = useState<FilterState>({
    minIvRank: '',
    maxIvRank: '',
    minScore: '',
    strategy: '',
    sortBy: 'score',
  });
  const [selectedSymbol, setSelectedSymbol] = useState<ScannerSymbol | null>(null);

  const fetchScanner = useCallback(() => {
    return api.getScanner({
      min_iv_rank: filters.minIvRank ? parseFloat(filters.minIvRank) : undefined,
      max_iv_rank: filters.maxIvRank ? parseFloat(filters.maxIvRank) : undefined,
      min_score: filters.minScore ? parseFloat(filters.minScore) : undefined,
      strategy: filters.strategy || undefined,
      sort_by: filters.sortBy,
      limit: 50,
    });
  }, [filters]);

  const { data, loading, error, refetch, retry } = useApi<ScannerData>(fetchScanner);

  const handleFilterChange = (key: keyof FilterState, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const applyFilters = () => {
    refetch();
  };

  const clearFilters = () => {
    setFilters({
      minIvRank: '',
      maxIvRank: '',
      minScore: '',
      strategy: '',
      sortBy: 'score',
    });
  };

  const getScoreColor = (label: string | null) => {
    if (!label) return 'var(--text-muted)';
    if (label.startsWith('A')) return 'var(--status-healthy)';
    if (label.startsWith('B')) return 'var(--accent-info)';
    if (label.startsWith('C')) return 'var(--status-warning)';
    return 'var(--text-muted)';
  };

  const getIvRankColor = (ivRank: number | null) => {
    if (ivRank === null) return 'inherit';
    if (ivRank >= 0.7) return 'var(--status-healthy)';
    if (ivRank >= 0.5) return 'var(--accent-info)';
    if (ivRank >= 0.3) return 'var(--status-warning)';
    return 'var(--text-muted)';
  };

  if (loading) {
    return <div className="loading">Scanning opportunities...</div>;
  }

  if (error) {
    return <ErrorDisplay error={error} onRetry={retry} context="Scanner" />;
  }

  if (!data) return null;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-lg)' }}>
        <h2>Opportunity Scanner</h2>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
            {data.total_symbols} symbols
          </span>
          <button className="btn btn-primary" onClick={refetch}>
            Scan
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-header">
          <span className="card-title">Filters</span>
          <button className="btn btn-secondary" onClick={clearFilters} style={{ fontSize: '12px', padding: '4px 12px' }}>
            Clear
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 'var(--space-md)' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Min IV Rank
            </label>
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              value={filters.minIvRank}
              onChange={(e) => handleFilterChange('minIvRank', e.target.value)}
              placeholder="0.0"
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
              }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Max IV Rank
            </label>
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              value={filters.maxIvRank}
              onChange={(e) => handleFilterChange('maxIvRank', e.target.value)}
              placeholder="1.0"
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
              }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Min Score
            </label>
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              value={filters.minScore}
              onChange={(e) => handleFilterChange('minScore', e.target.value)}
              placeholder="0.0"
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
              }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Strategy
            </label>
            <select
              value={filters.strategy}
              onChange={(e) => handleFilterChange('strategy', e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
              }}
            >
              <option value="">All Strategies</option>
              <option value="Iron Condor">Iron Condor</option>
              <option value="Credit Spread">Credit Spread</option>
              <option value="Straddle Sell">Straddle Sell</option>
              <option value="Strangle Sell">Strangle Sell</option>
              <option value="Calendar Spread">Calendar Spread</option>
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Sort By
            </label>
            <select
              value={filters.sortBy}
              onChange={(e) => handleFilterChange('sortBy', e.target.value)}
              style={{
                width: '100%',
                padding: '8px',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
              }}
            >
              <option value="score">Score (High to Low)</option>
              <option value="iv_rank">IV Rank (High to Low)</option>
              <option value="symbol">Symbol (A-Z)</option>
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary" onClick={applyFilters} style={{ width: '100%' }}>
              Apply Filters
            </button>
          </div>
        </div>
      </div>

      {/* Results Table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Scan Results</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Spot</th>
              <th>IV</th>
              <th>IV Rank</th>
              <th>HV30</th>
              <th>Score</th>
              <th>Strategies</th>
            </tr>
          </thead>
          <tbody>
            {data.symbols.map((symbol) => (
              <tr
                key={symbol.symbol}
                style={{ cursor: 'pointer' }}
                onClick={() => setSelectedSymbol(symbol)}
              >
                <td style={{ fontWeight: '600' }}>{symbol.symbol}</td>
                <td className="mono">${symbol.spot?.toFixed(2) ?? '-'}</td>
                <td className="mono">{symbol.iv !== null ? `${(symbol.iv * 100).toFixed(1)}%` : '-'}</td>
                <td className="mono" style={{ color: getIvRankColor(symbol.iv_rank) }}>
                  {symbol.iv_rank !== null ? `${(symbol.iv_rank * 100).toFixed(0)}%` : '-'}
                </td>
                <td className="mono">{symbol.hv30 !== null ? `${(symbol.hv30 * 100).toFixed(1)}%` : '-'}</td>
                <td>
                  <span
                    style={{
                      fontWeight: '600',
                      color: getScoreColor(symbol.score_label),
                    }}
                  >
                    {symbol.score_label || '-'}
                  </span>
                </td>
                <td>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {symbol.recommended_strategies.slice(0, 2).map((strat) => (
                      <span
                        key={strat}
                        style={{
                          background: 'var(--bg-secondary)',
                          padding: '2px 8px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '11px',
                        }}
                      >
                        {strat}
                      </span>
                    ))}
                    {symbol.recommended_strategies.length > 2 && (
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        +{symbol.recommended_strategies.length - 2}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {data.symbols.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 'var(--space-xl)' }}>
                  No symbols match your filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Symbol Detail Modal */}
      {selectedSymbol && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setSelectedSymbol(null)}
        >
          <div
            className="card"
            style={{
              maxWidth: '600px',
              width: '90%',
              maxHeight: '90vh',
              overflow: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-header">
              <span className="card-title">{selectedSymbol.symbol} Analysis</span>
              <button
                className="btn btn-secondary"
                onClick={() => setSelectedSymbol(null)}
                style={{ padding: '4px 12px' }}
              >
                Close
              </button>
            </div>

            {/* Symbol Overview */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 'var(--space-md)', marginBottom: 'var(--space-lg)' }}>
              <div style={{ textAlign: 'center', padding: 'var(--space-md)', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '24px', fontWeight: '700' }}>${selectedSymbol.spot?.toFixed(2) ?? '-'}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Spot Price</div>
              </div>
              <div style={{ textAlign: 'center', padding: 'var(--space-md)', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '24px', fontWeight: '700', color: getScoreColor(selectedSymbol.score_label) }}>
                  {selectedSymbol.score_label || '-'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>Score</div>
              </div>
              <div style={{ textAlign: 'center', padding: 'var(--space-md)', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '24px', fontWeight: '700', color: getIvRankColor(selectedSymbol.iv_rank) }}>
                  {selectedSymbol.iv_rank !== null ? `${(selectedSymbol.iv_rank * 100).toFixed(0)}%` : '-'}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>IV Rank</div>
              </div>
            </div>

            {/* Volatility Profile */}
            <div style={{ marginBottom: 'var(--space-lg)' }}>
              <h4 style={{ marginBottom: 'var(--space-sm)' }}>Volatility Profile</h4>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-md)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: 'var(--space-sm)', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Implied Volatility</span>
                  <span className="mono">{selectedSymbol.iv !== null ? `${(selectedSymbol.iv * 100).toFixed(1)}%` : '-'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: 'var(--space-sm)', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Historical Vol (30d)</span>
                  <span className="mono">{selectedSymbol.hv30 !== null ? `${(selectedSymbol.hv30 * 100).toFixed(1)}%` : '-'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: 'var(--space-sm)', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>IV/HV Ratio</span>
                  <span className="mono" style={{ color: selectedSymbol.iv_hv_ratio && selectedSymbol.iv_hv_ratio > 1.2 ? 'var(--status-healthy)' : 'inherit' }}>
                    {selectedSymbol.iv_hv_ratio?.toFixed(2) ?? '-'}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: 'var(--space-sm)', borderBottom: '1px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Days to Earnings</span>
                  <span className="mono" style={{ color: selectedSymbol.days_to_earnings !== null && selectedSymbol.days_to_earnings < 14 ? 'var(--status-warning)' : 'inherit' }}>
                    {selectedSymbol.days_to_earnings ?? 'N/A'}
                  </span>
                </div>
              </div>
            </div>

            {/* Recommended Strategies */}
            <div>
              <h4 style={{ marginBottom: 'var(--space-sm)' }}>Recommended Strategies</h4>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-sm)' }}>
                {selectedSymbol.recommended_strategies.map((strat) => (
                  <span
                    key={strat}
                    style={{
                      background: 'var(--accent-info)',
                      color: 'white',
                      padding: '8px 16px',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '14px',
                      fontWeight: '500',
                    }}
                  >
                    {strat}
                  </span>
                ))}
                {selectedSymbol.recommended_strategies.length === 0 && (
                  <span style={{ color: 'var(--text-muted)' }}>No strategies recommended</span>
                )}
              </div>
            </div>

            {/* IV Rank Visual */}
            <div style={{ marginTop: 'var(--space-lg)' }}>
              <h4 style={{ marginBottom: 'var(--space-sm)' }}>IV Rank Position</h4>
              <div style={{ position: 'relative', height: '24px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${(selectedSymbol.iv_rank ?? 0) * 100}%`,
                    background: `linear-gradient(to right, var(--status-error), var(--status-warning), var(--status-healthy))`,
                    borderRadius: 'var(--radius-sm)',
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    left: `${(selectedSymbol.iv_rank ?? 0) * 100}%`,
                    top: '-4px',
                    bottom: '-4px',
                    width: '4px',
                    background: 'var(--text-primary)',
                    borderRadius: '2px',
                    transform: 'translateX(-50%)',
                  }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '11px', color: 'var(--text-muted)' }}>
                <span>Low (0%)</span>
                <span>High (100%)</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
