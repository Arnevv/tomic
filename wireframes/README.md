# TOMIC Interactive Wireframes

Interactive wireframes based on the UX Design Document (v2.0).

## Running Locally

### Option 1: Python (Recommended)

```bash
cd wireframes
python3 -m http.server 8080
```

Then open: http://localhost:8080

### Option 2: Node.js

```bash
npx serve wireframes
```

### Option 3: Direct File

Simply open `index.html` in your browser directly.

## Features

### Two Modes

- **Monitor Mode** (Default): System health, portfolio overview, system status, logs
- **Decide Mode**: Scanner, symbol details, trade builder, journal

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `M` | Toggle Monitor/Decide mode |
| `1-4` | Navigate to sections |
| `/` | Open quick search |
| `Cmd+K` | Quick actions |
| `Esc` | Close panel / Go back |
| `?` | Show all shortcuts |

### Interactive Elements

- Click on scanner cards to view symbol details
- Click "Evaluate" on strategies to open Trade Builder
- Click on portfolio positions to see detail panel
- Toggle light/dark mode with moon icon
- Switch between tabs in Journal view

### Views Included

#### Monitor Mode
1. **Dashboard** - System health overview, batch status, recent activity
2. **Portfolio** - Positions, Greeks, risk summary, alerts
3. **System** - IB Gateway connection, data pipelines, background tasks
4. **Logs** - Activity logs with filtering

#### Decide Mode
1. **Scanner** - Symbol grid with filters, scan history
2. **Symbol Detail** - Volatility profile, strategy opportunities, portfolio context
3. **Trade Builder** - Proposal summary, legs, P&L scenarios, score breakdown
4. **Journal** - Open/closed trades, analytics

## Mock Data

The wireframes include realistic mock data for:
- 8 symbols (AAPL, MSFT, AMZN, GOOGL, META, NVDA, TSLA, AMD)
- 5 portfolio positions
- Trade analytics
- System status indicators

## Design System

The wireframes implement the full design system from the UX document:
- Light/Dark theme support
- Consistent color palette
- Proper typography scale
- Responsive layout (desktop-first)
- Status indicators and badges
