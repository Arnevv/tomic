import { Component, ReactNode } from 'react';
import { logger } from '../utils/logger';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  context?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  private contextLogger = logger.withContext(this.props.context || 'ErrorBoundary');

  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    this.setState({ errorInfo });

    this.contextLogger.error('Uncaught error in component tree', error, {
      componentStack: errorInfo.componentStack,
    });
  }

  handleRetry = (): void => {
    this.contextLogger.info('User initiated retry after error');
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  handleCopyError = (): void => {
    const { error, errorInfo } = this.state;
    const errorReport = {
      timestamp: new Date().toISOString(),
      error: {
        name: error?.name,
        message: error?.message,
        stack: error?.stack,
      },
      componentStack: errorInfo?.componentStack,
      context: this.props.context,
      userAgent: navigator.userAgent,
      url: window.location.href,
    };

    navigator.clipboard.writeText(JSON.stringify(errorReport, null, 2));
    this.contextLogger.info('Error report copied to clipboard');
  };

  handleDownloadLogs = (): void => {
    logger.downloadLogs();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const { error, errorInfo } = this.state;

      return (
        <div className="card" style={{ margin: 'var(--space-lg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', marginBottom: 'var(--space-md)' }}>
            <span style={{ color: 'var(--status-error)', fontSize: '1.5rem' }}>!</span>
            <h2 style={{ margin: 0, color: 'var(--status-error)' }}>Something went wrong</h2>
          </div>

          <p style={{ color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
            An unexpected error occurred. You can try again or copy the error details for debugging.
          </p>

          <div
            style={{
              background: 'var(--surface-secondary)',
              padding: 'var(--space-md)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 'var(--space-md)',
              fontFamily: 'monospace',
              fontSize: '0.85rem',
              overflow: 'auto',
              maxHeight: '200px',
            }}
          >
            <div style={{ color: 'var(--status-error)', fontWeight: 'bold' }}>
              {error?.name}: {error?.message}
            </div>
            {error?.stack && (
              <pre style={{ margin: 'var(--space-sm) 0 0', whiteSpace: 'pre-wrap', color: 'var(--text-muted)' }}>
                {error.stack.split('\n').slice(1, 6).join('\n')}
              </pre>
            )}
            {errorInfo?.componentStack && (
              <details style={{ marginTop: 'var(--space-sm)' }}>
                <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)' }}>
                  Component Stack
                </summary>
                <pre style={{ margin: 'var(--space-sm) 0 0', whiteSpace: 'pre-wrap', color: 'var(--text-muted)' }}>
                  {errorInfo.componentStack.slice(0, 500)}
                </pre>
              </details>
            )}
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={this.handleRetry}>
              Try Again
            </button>
            <button className="btn btn-secondary" onClick={this.handleCopyError}>
              Copy Error Details
            </button>
            <button className="btn btn-secondary" onClick={this.handleDownloadLogs}>
              Download Logs
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
