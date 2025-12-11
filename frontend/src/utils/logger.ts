// Frontend logging utility for TOMIC
// Provides structured logging with levels, context, and optional persistence

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  timestamp: string;
  level: LogLevel;
  message: string;
  context?: string;
  data?: unknown;
  error?: {
    name: string;
    message: string;
    stack?: string;
  };
}

interface LoggerConfig {
  minLevel: LogLevel;
  enableConsole: boolean;
  enableStorage: boolean;
  maxStoredLogs: number;
  storageKey: string;
}

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

// Check if we're in development mode
const isDev = typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

const DEFAULT_CONFIG: LoggerConfig = {
  minLevel: isDev ? 'debug' : 'info',
  enableConsole: true,
  enableStorage: true,
  maxStoredLogs: 100,
  storageKey: 'tomic_frontend_logs',
};

class Logger {
  private config: LoggerConfig;
  private logs: LogEntry[] = [];

  constructor(config: Partial<LoggerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.loadFromStorage();
  }

  private shouldLog(level: LogLevel): boolean {
    return LOG_LEVELS[level] >= LOG_LEVELS[this.config.minLevel];
  }

  private formatError(error: unknown): LogEntry['error'] | undefined {
    if (error instanceof Error) {
      return {
        name: error.name,
        message: error.message,
        stack: error.stack,
      };
    }
    if (error) {
      return {
        name: 'Unknown',
        message: String(error),
      };
    }
    return undefined;
  }

  private createEntry(
    level: LogLevel,
    message: string,
    context?: string,
    data?: unknown,
    error?: unknown
  ): LogEntry {
    return {
      timestamp: new Date().toISOString(),
      level,
      message,
      context,
      data: data !== undefined ? data : undefined,
      error: this.formatError(error),
    };
  }

  private writeToConsole(entry: LogEntry): void {
    if (!this.config.enableConsole) return;

    const prefix = entry.context ? `[${entry.context}]` : '';
    const msg = `${prefix} ${entry.message}`.trim();

    const consoleMethod = {
      debug: console.debug,
      info: console.info,
      warn: console.warn,
      error: console.error,
    }[entry.level];

    if (entry.data !== undefined && entry.error) {
      consoleMethod(msg, entry.data, entry.error);
    } else if (entry.data !== undefined) {
      consoleMethod(msg, entry.data);
    } else if (entry.error) {
      consoleMethod(msg, entry.error);
    } else {
      consoleMethod(msg);
    }
  }

  private persistToStorage(): void {
    if (!this.config.enableStorage) return;

    try {
      // Keep only the most recent logs
      const logsToStore = this.logs.slice(-this.config.maxStoredLogs);
      localStorage.setItem(this.config.storageKey, JSON.stringify(logsToStore));
    } catch {
      // Storage might be full or unavailable
    }
  }

  private loadFromStorage(): void {
    if (!this.config.enableStorage) return;

    try {
      const stored = localStorage.getItem(this.config.storageKey);
      if (stored) {
        this.logs = JSON.parse(stored);
      }
    } catch {
      this.logs = [];
    }
  }

  private log(
    level: LogLevel,
    message: string,
    context?: string,
    data?: unknown,
    error?: unknown
  ): void {
    if (!this.shouldLog(level)) return;

    const entry = this.createEntry(level, message, context, data, error);
    this.logs.push(entry);
    this.writeToConsole(entry);

    // Only persist warn and error to storage to avoid excessive writes
    if (level === 'warn' || level === 'error') {
      this.persistToStorage();
    }
  }

  debug(message: string, data?: unknown): void {
    this.log('debug', message, undefined, data);
  }

  info(message: string, data?: unknown): void {
    this.log('info', message, undefined, data);
  }

  warn(message: string, data?: unknown): void {
    this.log('warn', message, undefined, data);
  }

  error(message: string, error?: unknown, data?: unknown): void {
    this.log('error', message, undefined, data, error);
  }

  // Context-aware logging
  withContext(context: string) {
    return {
      debug: (message: string, data?: unknown) =>
        this.log('debug', message, context, data),
      info: (message: string, data?: unknown) =>
        this.log('info', message, context, data),
      warn: (message: string, data?: unknown) =>
        this.log('warn', message, context, data),
      error: (message: string, error?: unknown, data?: unknown) =>
        this.log('error', message, context, data, error),
    };
  }

  // Get all stored logs
  getLogs(filter?: { level?: LogLevel; context?: string; limit?: number }): LogEntry[] {
    let result = [...this.logs];

    if (filter?.level) {
      const minLevel = LOG_LEVELS[filter.level];
      result = result.filter((log) => LOG_LEVELS[log.level] >= minLevel);
    }

    if (filter?.context) {
      result = result.filter((log) => log.context === filter.context);
    }

    if (filter?.limit) {
      result = result.slice(-filter.limit);
    }

    return result;
  }

  // Get recent errors for debugging
  getRecentErrors(limit = 10): LogEntry[] {
    return this.logs.filter((log) => log.level === 'error').slice(-limit);
  }

  // Clear all logs
  clearLogs(): void {
    this.logs = [];
    if (this.config.enableStorage) {
      try {
        localStorage.removeItem(this.config.storageKey);
      } catch {
        // Ignore storage errors
      }
    }
  }

  // Export logs as JSON for debugging
  exportLogs(): string {
    return JSON.stringify(this.logs, null, 2);
  }

  // Download logs as file
  downloadLogs(): void {
    const blob = new Blob([this.exportLogs()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tomic-logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
}

// Singleton instance
export const logger = new Logger();

// Expose logger to window for debugging in development
if (isDev) {
  (window as unknown as { tomicLogger: Logger }).tomicLogger = logger;
}
