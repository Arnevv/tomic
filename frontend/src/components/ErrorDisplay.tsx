import { ApiError, NetworkError } from '../api/client';
import { logger } from '../utils/logger';

interface ErrorDisplayProps {
  error: Error | null;
  onRetry?: () => void;
  context?: string;
}

function getErrorDetails(error: Error): {
  title: string;
  message: string;
  details?: string;
  isRetryable: boolean;
} {
  if (error instanceof NetworkError) {
    return {
      title: 'Connection Error',
      message: 'Unable to connect to the server. Please check your network connection.',
      details: error.endpoint,
      isRetryable: true,
    };
  }

  if (error instanceof ApiError) {
    // Map HTTP status codes to user-friendly messages
    const statusMessages: Record<number, { title: string; message: string; isRetryable: boolean }> = {
      400: {
        title: 'Invalid Request',
        message: 'The request was invalid. Please try again or contact support.',
        isRetryable: false,
      },
      401: {
        title: 'Unauthorized',
        message: 'You are not authorized to perform this action.',
        isRetryable: false,
      },
      403: {
        title: 'Access Denied',
        message: 'You do not have permission to access this resource.',
        isRetryable: false,
      },
      404: {
        title: 'Not Found',
        message: 'The requested resource was not found.',
        isRetryable: false,
      },
      500: {
        title: 'Server Error',
        message: 'An internal server error occurred. Please try again later.',
        isRetryable: true,
      },
      502: {
        title: 'Bad Gateway',
        message: 'The server is temporarily unavailable. Please try again.',
        isRetryable: true,
      },
      503: {
        title: 'Service Unavailable',
        message: 'The service is temporarily unavailable. Please try again.',
        isRetryable: true,
      },
      504: {
        title: 'Gateway Timeout',
        message: 'The request timed out. Please try again.',
        isRetryable: true,
      },
    };

    const statusInfo = statusMessages[error.status] || {
      title: `Error ${error.status}`,
      message: error.statusText || 'An unexpected error occurred.',
      isRetryable: error.status >= 500,
    };

    // Try to extract more details from response body
    let details: string | undefined;
    if (error.responseBody) {
      if (typeof error.responseBody === 'object' && error.responseBody !== null) {
        const body = error.responseBody as Record<string, unknown>;
        details = body.detail?.toString() || body.message?.toString() || body.error?.toString();
      } else if (typeof error.responseBody === 'string') {
        details = error.responseBody;
      }
    }

    return {
      ...statusInfo,
      details: details || `Endpoint: ${error.endpoint}`,
    };
  }

  return {
    title: 'Error',
    message: error.message || 'An unexpected error occurred.',
    isRetryable: true,
  };
}

export function ErrorDisplay({ error, onRetry, context }: ErrorDisplayProps) {
  if (!error) return null;

  const { title, message, details, isRetryable } = getErrorDetails(error);

  const handleCopyError = () => {
    const errorReport = {
      timestamp: new Date().toISOString(),
      context,
      error: {
        name: error.name,
        message: error.message,
        ...(error instanceof ApiError && {
          status: error.status,
          endpoint: error.endpoint,
          responseBody: error.responseBody,
        }),
        ...(error instanceof NetworkError && {
          endpoint: error.endpoint,
        }),
        stack: error.stack,
      },
    };

    navigator.clipboard.writeText(JSON.stringify(errorReport, null, 2));
    logger.withContext(context || 'ErrorDisplay').info('Error details copied to clipboard');
  };

  return (
    <div className="card">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-sm)',
          marginBottom: 'var(--space-sm)',
        }}
      >
        <span style={{ color: 'var(--status-error)', fontSize: '1.25rem' }}>!</span>
        <h3 style={{ margin: 0, color: 'var(--status-error)' }}>{title}</h3>
      </div>

      <p style={{ color: 'var(--text-secondary)', margin: '0 0 var(--space-sm)' }}>{message}</p>

      {details && (
        <p
          style={{
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
            margin: '0 0 var(--space-md)',
            fontFamily: 'monospace',
          }}
        >
          {details}
        </p>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
        {onRetry && isRetryable && (
          <button className="btn btn-primary" onClick={onRetry}>
            Retry
          </button>
        )}
        <button className="btn btn-secondary" onClick={handleCopyError}>
          Copy Error
        </button>
      </div>
    </div>
  );
}
