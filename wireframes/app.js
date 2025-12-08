// TOMIC Interactive Wireframes - JavaScript

// ==========================================
// Mock Data
// ==========================================

const mockSymbols = [
  {
    symbol: 'AAPL',
    company: 'Apple Inc.',
    score: 72,
    recommended: true,
    iv: 35.2,
    ivRank: 72,
    ivPercentile: 68,
    earnings: 45,
    bestStrategy: 'IC',
    rom: 8.2,
    spot: 245.50,
    change: 1.2,
    atr: 4.25,
    hv20: 28.1,
    hv30: 30.2,
    inPortfolio: false
  },
  {
    symbol: 'MSFT',
    company: 'Microsoft Corp.',
    score: 68,
    recommended: true,
    iv: 28,
    ivRank: 65,
    ivPercentile: 62,
    earnings: 12,
    bestStrategy: 'SPS',
    rom: 6.5,
    spot: 378.20,
    change: 0.8,
    atr: 5.10,
    hv20: 24.5,
    hv30: 25.8,
    inPortfolio: false
  },
  {
    symbol: 'AMZN',
    company: 'Amazon.com Inc.',
    score: 65,
    recommended: true,
    iv: 42,
    ivRank: 78,
    ivPercentile: 75,
    earnings: 30,
    bestStrategy: 'IC',
    rom: 7.8,
    spot: 185.40,
    change: -0.5,
    atr: 3.80,
    hv20: 35.2,
    hv30: 36.1,
    inPortfolio: false
  },
  {
    symbol: 'GOOGL',
    company: 'Alphabet Inc.',
    score: 62,
    recommended: true,
    iv: 31,
    ivRank: 58,
    ivPercentile: 55,
    earnings: 60,
    bestStrategy: 'SCS',
    rom: 5.8,
    spot: 141.80,
    change: 1.5,
    atr: 2.90,
    hv20: 26.3,
    hv30: 27.5,
    inPortfolio: false
  },
  {
    symbol: 'META',
    company: 'Meta Platforms Inc.',
    score: 58,
    recommended: false,
    iv: 38,
    ivRank: 71,
    ivPercentile: 68,
    earnings: 8,
    bestStrategy: null,
    rom: null,
    spot: 512.30,
    change: 2.1,
    atr: 8.50,
    hv20: 32.1,
    hv30: 33.4,
    inPortfolio: false,
    blocked: 'Earnings too close'
  },
  {
    symbol: 'NVDA',
    company: 'NVIDIA Corp.',
    score: null,
    recommended: false,
    iv: 52,
    ivRank: 82,
    ivPercentile: 79,
    earnings: 25,
    bestStrategy: null,
    rom: null,
    spot: 875.20,
    change: -1.2,
    atr: 18.50,
    hv20: 45.2,
    hv30: 46.8,
    inPortfolio: true,
    blocked: 'In Portfolio'
  },
  {
    symbol: 'TSLA',
    company: 'Tesla Inc.',
    score: 55,
    recommended: false,
    iv: 58,
    ivRank: 55,
    ivPercentile: 52,
    earnings: 35,
    bestStrategy: 'IC',
    rom: 5.2,
    spot: 242.80,
    change: -2.3,
    atr: 8.20,
    hv20: 52.1,
    hv30: 53.4,
    inPortfolio: false
  },
  {
    symbol: 'AMD',
    company: 'Advanced Micro Devices',
    score: 60,
    recommended: true,
    iv: 45,
    ivRank: 68,
    ivPercentile: 65,
    earnings: 42,
    bestStrategy: 'SPS',
    rom: 6.2,
    spot: 138.50,
    change: 0.9,
    atr: 3.20,
    hv20: 38.5,
    hv30: 39.2,
    inPortfolio: false
  }
];

const mockPositions = [
  {
    symbol: 'AAPL',
    strategy: 'Iron Condor',
    entry: '12/01',
    current: 85,
    dte: 18,
    pnl: 23,
    status: 'normal'
  },
  {
    symbol: 'MSFT',
    strategy: 'Short Put',
    entry: '12/03',
    current: 120,
    dte: 25,
    pnl: 18,
    status: 'normal'
  },
  {
    symbol: 'NVDA',
    strategy: 'Put Spread',
    entry: '12/05',
    current: -45,
    dte: 12,
    pnl: -8,
    status: 'warning'
  },
  {
    symbol: 'SPY',
    strategy: 'Iron Condor',
    entry: '11/28',
    current: 210,
    dte: 8,
    pnl: 65,
    status: 'tp-ready'
  },
  {
    symbol: 'QQQ',
    strategy: 'Put Spread',
    entry: '12/02',
    current: 55,
    dte: 15,
    pnl: 12,
    status: 'normal'
  }
];

// ==========================================
// State Management
// ==========================================

let state = {
  mode: 'monitor', // 'monitor' or 'decide'
  currentView: 'dashboard',
  theme: 'light',
  selectedSymbol: null,
  selectedPosition: null,
  detailPanelOpen: false
};

// ==========================================
// DOM Elements
// ==========================================

const modeButtons = document.querySelectorAll('.mode-btn');
const monitorNav = document.querySelector('.monitor-nav');
const decideNav = document.querySelector('.decide-nav');
const navItems = document.querySelectorAll('.nav-item');
const views = document.querySelectorAll('.view');
const themeToggle = document.getElementById('theme-toggle');
const symbolGrid = document.getElementById('symbol-grid');
const detailPanel = document.getElementById('detail-panel');
const closePanel = document.getElementById('close-panel');
const quickActionsModal = document.getElementById('quick-actions-modal');
const shortcutsModal = document.getElementById('shortcuts-modal');

// ==========================================
// Mode Toggle
// ==========================================

function setMode(mode) {
  state.mode = mode;

  // Update mode buttons
  modeButtons.forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });

  // Toggle nav items visibility
  monitorNav.classList.toggle('hidden', mode !== 'monitor');
  decideNav.classList.toggle('hidden', mode !== 'decide');

  // Switch to default view for mode
  if (mode === 'monitor') {
    showView('dashboard');
  } else {
    showView('scanner');
  }
}

modeButtons.forEach(btn => {
  btn.addEventListener('click', () => setMode(btn.dataset.mode));
});

// ==========================================
// Navigation
// ==========================================

function showView(viewId) {
  state.currentView = viewId;

  // Update nav items
  const currentNavItems = state.mode === 'monitor'
    ? monitorNav.querySelectorAll('.nav-item')
    : decideNav.querySelectorAll('.nav-item');

  currentNavItems.forEach(item => {
    item.classList.toggle('active', item.dataset.view === viewId);
  });

  // Show view
  views.forEach(view => {
    view.classList.toggle('active', view.id === `${viewId}-view`);
  });

  // Close detail panel when switching views
  closeDetailPanel();
}

navItems.forEach(item => {
  item.addEventListener('click', () => showView(item.dataset.view));
});

// ==========================================
// Theme Toggle
// ==========================================

function toggleTheme() {
  state.theme = state.theme === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', state.theme);
  themeToggle.querySelector('.icon').textContent = state.theme === 'light' ? '🌙' : '☀️';
  localStorage.setItem('tomic-theme', state.theme);
}

themeToggle.addEventListener('click', toggleTheme);

// Load saved theme
const savedTheme = localStorage.getItem('tomic-theme');
if (savedTheme) {
  state.theme = savedTheme;
  document.documentElement.setAttribute('data-theme', state.theme);
  themeToggle.querySelector('.icon').textContent = state.theme === 'light' ? '🌙' : '☀️';
}

// ==========================================
// Symbol Grid (Scanner)
// ==========================================

function renderSymbolGrid() {
  symbolGrid.innerHTML = mockSymbols.map(symbol => {
    const isBlocked = symbol.blocked || symbol.inPortfolio;
    const cardClass = symbol.recommended ? 'recommended' : (isBlocked ? 'blocked' : '');
    const scoreDisplay = symbol.score ? (symbol.recommended ? `★${symbol.score}` : symbol.score) : '';
    const scoreClass = symbol.recommended ? 'recommended' : '';

    return `
      <div class="symbol-card ${cardClass}" data-symbol="${symbol.symbol}">
        <div class="symbol-card-header">
          <span class="symbol-card-symbol">${symbol.symbol}</span>
          <span class="symbol-card-score ${scoreClass}">${scoreDisplay}</span>
        </div>
        ${isBlocked ? `
          <div class="symbol-card-metrics">
            <div>${symbol.blocked}</div>
            <div style="margin-top: 8px; color: var(--text-muted);">⚠ Blocked</div>
          </div>
        ` : `
          <div class="symbol-card-metrics">
            <div>IV: ${symbol.iv}%</div>
            <div>Rank: ${symbol.ivRank}%</div>
            <div>Earn: ${symbol.earnings}d ${symbol.earnings < 14 ? '⚠' : ''}</div>
          </div>
          <div class="symbol-card-strategy">
            ${symbol.bestStrategy ? `
              Best: <strong>${symbol.bestStrategy}</strong><br>
              ROM: ${symbol.rom}%
            ` : 'No opportunities'}
          </div>
        `}
      </div>
    `;
  }).join('');

  // Add click handlers
  symbolGrid.querySelectorAll('.symbol-card').forEach(card => {
    card.addEventListener('click', () => {
      const symbolData = mockSymbols.find(s => s.symbol === card.dataset.symbol);
      if (symbolData && !symbolData.blocked) {
        showSymbolDetail(symbolData);
      }
    });
  });
}

// ==========================================
// Symbol Detail View
// ==========================================

function showSymbolDetail(symbolData) {
  state.selectedSymbol = symbolData;

  // Update symbol detail view
  document.getElementById('symbol-detail-name').textContent = symbolData.symbol;
  document.getElementById('symbol-detail-company').textContent = symbolData.company;

  // Show symbol detail view
  showView('symbol-detail');
}

// Back to Scanner
document.getElementById('back-to-scanner').addEventListener('click', () => {
  showView('scanner');
});

// Back to Symbol from Trade Builder
document.getElementById('back-to-symbol').addEventListener('click', () => {
  showView('symbol-detail');
});

// Evaluate strategy buttons
document.querySelectorAll('.strategy-row .btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    showView('trade-builder');
  });
});

// ==========================================
// Detail Panel
// ==========================================

function openDetailPanel(title, content) {
  document.getElementById('panel-title').textContent = title;
  document.getElementById('panel-content').innerHTML = content;
  detailPanel.classList.remove('hidden');
  state.detailPanelOpen = true;
}

function closeDetailPanel() {
  detailPanel.classList.add('hidden');
  state.detailPanelOpen = false;
}

closePanel.addEventListener('click', closeDetailPanel);

// Position row clicks
document.querySelectorAll('.position-row').forEach(row => {
  row.addEventListener('click', () => {
    const symbol = row.dataset.symbol;
    const position = mockPositions.find(p => p.symbol === symbol);
    if (position) {
      openDetailPanel(`${position.symbol} - ${position.strategy}`, `
        <div class="detail-section">
          <h4>Position Details</h4>
          <ul class="detail-list">
            <li>Entry Date: ${position.entry}</li>
            <li>Days to Expiration: ${position.dte}</li>
            <li>Current P&L: ${position.pnl > 0 ? '+' : ''}${position.pnl}%</li>
            <li>Status: ${position.status}</li>
          </ul>
        </div>
        <div class="detail-section">
          <h4>Greeks</h4>
          <ul class="detail-list">
            <li>Delta: -0.05</li>
            <li>Gamma: -0.002</li>
            <li>Theta: +$8.50</li>
            <li>Vega: -12.5</li>
          </ul>
        </div>
        <div class="button-group" style="margin-top: 16px;">
          <button class="btn btn-secondary">Refresh Quote</button>
          <button class="btn btn-secondary">View in Journal</button>
          <button class="btn btn-primary">Prepare Exit</button>
        </div>
      `);
    }
  });
});

// ==========================================
// Journal Tabs
// ==========================================

const tabs = document.querySelectorAll('.tab');
const tabContents = document.querySelectorAll('.tab-content');

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;

    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    tabContents.forEach(content => {
      content.classList.toggle('active', content.id === `${tabId}-tab`);
    });
  });
});

// ==========================================
// Quick Actions Modal
// ==========================================

function openQuickActions() {
  quickActionsModal.classList.remove('hidden');
  quickActionsModal.querySelector('.search-input').focus();
}

function closeQuickActions() {
  quickActionsModal.classList.add('hidden');
}

quickActionsModal.querySelector('.modal-backdrop').addEventListener('click', closeQuickActions);

// ==========================================
// Shortcuts Modal
// ==========================================

function openShortcuts() {
  shortcutsModal.classList.remove('hidden');
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.add('hidden');
}

window.closeModal = closeModal;

shortcutsModal.querySelector('.modal-backdrop').addEventListener('click', () => closeModal('shortcuts-modal'));

// ==========================================
// Keyboard Shortcuts
// ==========================================

document.addEventListener('keydown', (e) => {
  // Ignore if typing in an input
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
    if (e.key === 'Escape') {
      e.target.blur();
      closeQuickActions();
    }
    return;
  }

  switch (e.key) {
    case 'm':
    case 'M':
      setMode(state.mode === 'monitor' ? 'decide' : 'monitor');
      break;
    case '1':
      if (state.mode === 'monitor') showView('dashboard');
      else showView('scanner');
      break;
    case '2':
      if (state.mode === 'monitor') showView('portfolio');
      else showView('journal');
      break;
    case '3':
      if (state.mode === 'monitor') showView('system');
      break;
    case '4':
      if (state.mode === 'monitor') showView('logs');
      break;
    case '/':
      e.preventDefault();
      openQuickActions();
      break;
    case '?':
      openShortcuts();
      break;
    case 'Escape':
      if (state.detailPanelOpen) {
        closeDetailPanel();
      } else if (!quickActionsModal.classList.contains('hidden')) {
        closeQuickActions();
      } else if (!shortcutsModal.classList.contains('hidden')) {
        closeModal('shortcuts-modal');
      } else if (state.currentView === 'symbol-detail') {
        showView('scanner');
      } else if (state.currentView === 'trade-builder') {
        showView('symbol-detail');
      }
      break;
    case 'r':
    case 'R':
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        // Simulate refresh
        console.log('Refreshing view...');
      }
      break;
    case 'k':
    case 'K':
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        openQuickActions();
      }
      break;
  }
});

// ==========================================
// Status Bar Interactions
// ==========================================

document.getElementById('tasks-status').addEventListener('click', () => {
  setMode('monitor');
  showView('system');
});

document.getElementById('alerts-status').addEventListener('click', () => {
  setMode('monitor');
  showView('portfolio');
});

// ==========================================
// Simulate Live Updates
// ==========================================

function updateTimestamps() {
  const timestamps = document.querySelectorAll('.data-timestamp');
  // Just a visual simulation - would be real data in production
}

// Update every minute
setInterval(updateTimestamps, 60000);

// Simulate task progress
let taskProgress = 52;
function simulateTaskProgress() {
  const progressFill = document.querySelector('.progress-fill');
  const taskProgressSpan = document.querySelector('.task-progress');

  if (progressFill && taskProgress < 100) {
    taskProgress += Math.random() * 5;
    if (taskProgress > 100) taskProgress = 100;
    progressFill.style.width = `${taskProgress}%`;
    if (taskProgressSpan) {
      taskProgressSpan.textContent = `${Math.round(taskProgress)}%`;
    }
  }
}

setInterval(simulateTaskProgress, 2000);

// ==========================================
// Initialize
// ==========================================

function init() {
  renderSymbolGrid();

  // Log initialization
  console.log('TOMIC Wireframes initialized');
  console.log('Press ? to see keyboard shortcuts');
}

// Run on DOM ready
document.addEventListener('DOMContentLoaded', init);

// Also run immediately if DOM is already loaded
if (document.readyState !== 'loading') {
  init();
}
