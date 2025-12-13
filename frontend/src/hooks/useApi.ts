import { useState, useEffect, useRef, useCallback } from 'react';
import { logger } from '../utils/logger';
import { ApiError, NetworkError } from '../api/client';

const hookLogger = logger.withContext('useApi');

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  errorType: 'api' | 'network' | 'unknown' | null;
  refetch: () => void;
  retry: () => void;
}

function getErrorType(error: Error | null): 'api' | 'network' | 'unknown' | null {
  if (!error) return null;
  if (error instanceof ApiError) return 'api';
  if (error instanceof NetworkError) return 'network';
  return 'unknown';
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = []
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const fetcherRef = useRef(fetcher);

  // Keep fetcher ref updated
  fetcherRef.current = fetcher;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
    } catch (err) {
      const normalizedError = err instanceof Error ? err : new Error('Unknown error');
      setError(normalizedError);

      // Log with context about the error type
      if (err instanceof ApiError) {
        hookLogger.warn(`API error (status ${err.status})`, {
          endpoint: err.endpoint,
          status: err.status,
          responseBody: err.responseBody,
        });
      } else if (err instanceof NetworkError) {
        hookLogger.warn('Network error', {
          endpoint: err.endpoint,
          originalError: String(err.originalError),
        });
      } else {
        hookLogger.error('Unexpected error in useApi', normalizedError);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Retry function that increments retry count
  const retry = useCallback(() => {
    hookLogger.info(`Manual retry triggered (attempt ${retryCount + 1})`);
    setRetryCount((c) => c + 1);
  }, [retryCount]);

  useEffect(() => {
    fetchData();
    // Intentionally spreading deps array to allow caller to specify additional dependencies.
    // This is a deliberate pattern to make the hook flexible while keeping fetchData stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchData, retryCount, ...deps]);

  return {
    data,
    loading,
    error,
    errorType: getErrorType(error),
    refetch: fetchData,
    retry,
  };
}
