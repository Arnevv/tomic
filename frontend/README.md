# TOMIC Web Frontend

React frontend voor het TOMIC options trading system.

## Vereisten

- Node.js 18+
- npm of yarn
- Python 3.10+ (voor de backend)

## Quick Start

### 1. Backend starten

```bash
# Vanuit de TOMIC root directory
cd /path/to/tomic

# Installeer Python dependencies (inclusief FastAPI)
pip install -r requirements.txt

# Start de API server
python -m uvicorn tomic.web.main:app --reload --port 8000
```

De API draait nu op http://localhost:8000

### 2. Frontend starten

```bash
# Vanuit de frontend directory
cd frontend

# Installeer dependencies (eerste keer)
npm install

# Start development server
npm run dev
```

De frontend draait nu op http://localhost:5173

## Beschikbare API Endpoints

| Endpoint | Beschrijving |
|----------|--------------|
| GET /api/health | System health status |
| GET /api/dashboard | Complete dashboard data |
| GET /api/portfolio | Portfolio posities en Greeks |
| GET /api/journal | Trade journal |
| GET /api/symbols | Geconfigureerde symbols |
| POST /api/portfolio/refresh | Trigger portfolio refresh |

## Project Structuur

```
frontend/
├── src/
│   ├── api/           # API client
│   ├── components/    # Herbruikbare componenten
│   ├── hooks/         # Custom React hooks
│   ├── pages/         # Pagina componenten
│   ├── types/         # TypeScript types
│   ├── App.tsx        # Main app component
│   ├── main.tsx       # Entry point
│   └── index.css      # Global styles
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## Beschikbare Views

### Monitor Mode
- **Dashboard** - System health, portfolio summary, alerts
- **Portfolio** - Posities, Greeks, P&L overzicht
- **System** - IB Gateway status, data pipelines (coming soon)
- **Logs** - Activity logs (coming soon)

### Decide Mode
- **Scanner** - Symbol opportunities (coming soon - Phase 2)
- **Journal** - Trade tracking (coming soon)

## Development

```bash
# Development server met hot reload
npm run dev

# Production build
npm run build

# Preview production build
npm run preview
```
