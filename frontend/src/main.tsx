import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { setupGlobalErrorHandlers } from './utils/globalErrorHandler'
import { ErrorBoundary } from './components/ErrorBoundary'
import { logger } from './utils/logger'

// Initialize global error handlers
setupGlobalErrorHandlers()

// Log application startup
logger.info('TOMIC frontend starting', {
  timestamp: new Date().toISOString(),
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary context="App">
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
