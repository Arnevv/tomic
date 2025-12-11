// Global error handler for unhandled errors and promise rejections
import { logger } from './logger';

const errorLogger = logger.withContext('GlobalError');

export function setupGlobalErrorHandlers(): void {
  // Handle uncaught JavaScript errors
  window.onerror = (
    message: string | Event,
    source?: string,
    lineno?: number,
    colno?: number,
    error?: Error
  ): boolean => {
    errorLogger.error('Uncaught error', error, {
      message: String(message),
      source,
      lineno,
      colno,
    });

    // Return false to allow default error handling (shows in console)
    return false;
  };

  // Handle unhandled promise rejections
  window.onunhandledrejection = (event: PromiseRejectionEvent): void => {
    const error = event.reason;

    errorLogger.error('Unhandled promise rejection', error, {
      type: error?.name || 'Unknown',
      message: error?.message || String(error),
    });
  };

  // Log when the page visibility changes (helps debug issues that occur when tab is hidden)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      errorLogger.debug('Page became hidden');
    } else {
      errorLogger.debug('Page became visible');
    }
  });

  // Log network status changes
  window.addEventListener('online', () => {
    errorLogger.info('Network connection restored');
  });

  window.addEventListener('offline', () => {
    errorLogger.warn('Network connection lost');
  });

  errorLogger.info('Global error handlers initialized');
}
