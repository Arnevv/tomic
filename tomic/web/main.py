"""TOMIC Web API - FastAPI application."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    Alert,
    BatchJob,
    DashboardResponse,
    HealthStatus,
    JournalResponse,
    JournalTrade,
    PortfolioGreeks,
    PortfolioSummary,
    Position,
    PositionLeg,
    RecentActivity,
    SystemHealth,
)

# Initialize FastAPI app
app = FastAPI(
    title="TOMIC Web API",
    description="REST API for TOMIC options trading system",
    version="1.0.0",
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_project_root() -> Path:
    """Get the TOMIC project root directory."""
    return Path(__file__).parent.parent.parent


def load_json_file(filename: str) -> Any:
    """Load a JSON file from the project."""
    import json

    # Try multiple locations
    paths_to_try = [
        get_project_root() / filename,
        get_project_root() / "exports" / filename,
        Path(filename),
    ]

    for path in paths_to_try:
        if path.exists():
            with open(path) as f:
                return json.load(f)

    return None


def check_ib_gateway() -> HealthStatus:
    """Check IB Gateway connection status."""
    try:
        # Try to run the connection test script
        script_path = get_project_root() / "scripts" / "tws_connection_test.py"
        if script_path.exists():
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return HealthStatus(
                    component="IB Gateway",
                    status="healthy",
                    message="Connected",
                    last_check=datetime.now(),
                )
            else:
                return HealthStatus(
                    component="IB Gateway",
                    status="error",
                    message="Connection failed",
                    last_check=datetime.now(),
                )
        else:
            return HealthStatus(
                component="IB Gateway",
                status="warning",
                message="Connection test script not found",
                last_check=datetime.now(),
            )
    except subprocess.TimeoutExpired:
        return HealthStatus(
            component="IB Gateway",
            status="error",
            message="Connection timeout",
            last_check=datetime.now(),
        )
    except Exception as e:
        return HealthStatus(
            component="IB Gateway",
            status="error",
            message=str(e),
            last_check=datetime.now(),
        )


def check_data_sync() -> HealthStatus:
    """Check data synchronization status."""
    # Check if we have recent market data
    price_meta = get_project_root() / "price_meta.json"

    if price_meta.exists():
        import json
        try:
            with open(price_meta) as f:
                meta = json.load(f)
            # Check last update time if available
            return HealthStatus(
                component="Data Sync",
                status="healthy",
                message=f"Price data available ({len(meta)} symbols)" if isinstance(meta, dict) else "Data available",
                last_check=datetime.now(),
            )
        except Exception:
            pass

    return HealthStatus(
        component="Data Sync",
        status="warning",
        message="No recent price data",
        last_check=datetime.now(),
    )


def load_positions() -> list[dict[str, Any]]:
    """Load positions from JSON file."""
    positions = load_json_file("positions.json")
    if positions is None:
        # Try exports directory
        positions = load_json_file("exports/positions.json")
    return positions if isinstance(positions, list) else []


def load_journal() -> list[dict[str, Any]]:
    """Load journal from JSON file."""
    journal = load_json_file("journal.json")
    if journal is None:
        journal = load_json_file("exports/journal.json")
    return journal if isinstance(journal, list) else []


def build_portfolio_summary() -> PortfolioSummary:
    """Build portfolio summary from positions and journal."""
    raw_positions = load_positions()
    journal = load_journal()

    # Group positions by symbol/expiry into strategies
    positions: list[Position] = []

    # Get open trades from journal
    open_trades = [t for t in journal if t.get("Status", "").lower() != "gesloten"]

    for trade in open_trades:
        symbol = trade.get("Symbol", trade.get("symbol", ""))
        legs: list[PositionLeg] = []

        # Extract legs if available
        trade_legs = trade.get("Legs", trade.get("legs", []))
        if isinstance(trade_legs, list):
            for leg in trade_legs:
                legs.append(PositionLeg(
                    symbol=leg.get("symbol", symbol),
                    right=leg.get("right"),
                    strike=leg.get("strike"),
                    expiry=leg.get("expiry") or leg.get("lastTradeDate"),
                    position=leg.get("position", 0),
                    avg_cost=leg.get("avgCost"),
                ))

        # Calculate P&L
        entry_credit = trade.get("Credit", trade.get("credit"))
        current_value = trade.get("CurrentValue")
        unrealized_pnl = trade.get("unrealizedPnL")
        pnl_percent = None

        if entry_credit and unrealized_pnl:
            try:
                pnl_percent = (float(unrealized_pnl) / abs(float(entry_credit))) * 100
            except (ValueError, ZeroDivisionError):
                pass

        # Determine status based on alerts
        alerts = trade.get("alerts", [])
        status = "normal"
        if any("TP" in str(a) or "take profit" in str(a).lower() for a in alerts):
            status = "tp_ready"
        elif any("exit" in str(a).lower() or "beheer" in str(a).lower() for a in alerts):
            status = "monitor"

        positions.append(Position(
            symbol=symbol,
            strategy=trade.get("Strategy", trade.get("strategy")),
            legs=legs,
            entry_date=trade.get("DatumIn", trade.get("entry_date")),
            entry_credit=float(entry_credit) if entry_credit else None,
            current_value=float(current_value) if current_value else None,
            unrealized_pnl=float(unrealized_pnl) if unrealized_pnl else None,
            pnl_percent=pnl_percent,
            days_to_expiry=trade.get("days_to_expiry"),
            status=status,
            alerts=alerts if isinstance(alerts, list) else [],
        ))

    # Calculate totals
    total_pnl = sum(p.unrealized_pnl or 0 for p in positions)

    return PortfolioSummary(
        positions=positions,
        total_positions=len(positions),
        greeks=PortfolioGreeks(),  # Would need live data
        total_unrealized_pnl=total_pnl if total_pnl else None,
        last_sync=datetime.now(),
    )


# === API Endpoints ===

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TOMIC Web API", "version": "1.0.0"}


@app.get("/api/health", response_model=SystemHealth)
async def get_health():
    """Get system health status."""
    ib_status = check_ib_gateway()
    data_status = check_data_sync()

    # Determine overall health
    statuses = [ib_status.status, data_status.status]
    if "error" in statuses:
        overall = "error"
    elif "warning" in statuses:
        overall = "warning"
    else:
        overall = "healthy"

    return SystemHealth(
        ib_gateway=ib_status,
        data_sync=data_status,
        overall=overall,
    )


@app.get("/api/portfolio", response_model=PortfolioSummary)
async def get_portfolio():
    """Get portfolio summary with positions."""
    try:
        return build_portfolio_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard", response_model=DashboardResponse)
async def get_dashboard():
    """Get complete dashboard data."""
    try:
        health = SystemHealth(
            ib_gateway=check_ib_gateway(),
            data_sync=check_data_sync(),
            overall="healthy",
        )

        portfolio = build_portfolio_summary()

        # Build alerts from positions with issues
        alerts: list[Alert] = []
        for i, pos in enumerate(portfolio.positions):
            for alert_msg in pos.alerts:
                alerts.append(Alert(
                    id=f"alert-{i}-{hash(alert_msg) % 10000}",
                    level="warning",
                    message=alert_msg,
                    symbol=pos.symbol,
                    created_at=datetime.now(),
                ))

        # Mock batch jobs - would connect to actual job scheduler
        batch_jobs = [
            BatchJob(
                name="Market Data Fetch",
                status="success",
                last_run=datetime.now(),
                message="47 symbols updated",
            ),
            BatchJob(
                name="Portfolio Sync",
                status="success",
                last_run=datetime.now(),
                message=f"{portfolio.total_positions} positions synced",
            ),
        ]

        return DashboardResponse(
            health=health,
            portfolio_summary=portfolio,
            batch_jobs=batch_jobs,
            alerts=alerts,
            recent_activity=[],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/journal", response_model=JournalResponse)
async def get_journal():
    """Get trading journal."""
    try:
        raw_journal = load_journal()

        trades: list[JournalTrade] = []
        for entry in raw_journal:
            trade_id = str(entry.get("TradeID", entry.get("trade_id", "")))
            status = entry.get("Status", "Open")

            trades.append(JournalTrade(
                trade_id=trade_id,
                symbol=entry.get("Symbol", entry.get("symbol", "")),
                strategy=entry.get("Strategy", entry.get("strategy")),
                entry_date=entry.get("DatumIn", entry.get("entry_date")),
                exit_date=entry.get("DatumUit", entry.get("exit_date")),
                entry_credit=entry.get("Credit", entry.get("credit")),
                exit_debit=entry.get("Debit", entry.get("debit")),
                pnl=entry.get("PnL", entry.get("pnl")),
                status=status,
                notes=entry.get("Notes", entry.get("notes")),
                legs=entry.get("Legs", entry.get("legs", [])),
            ))

        open_count = sum(1 for t in trades if t.status.lower() != "gesloten")
        closed_count = len(trades) - open_count

        return JournalResponse(
            trades=trades,
            total_trades=len(trades),
            open_trades=open_count,
            closed_trades=closed_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/symbols")
async def get_symbols():
    """Get configured symbols list."""
    try:
        import yaml

        symbols_file = get_project_root() / "config" / "symbols.yaml"
        if symbols_file.exists():
            with open(symbols_file) as f:
                symbols = yaml.safe_load(f)
            return {"symbols": symbols if isinstance(symbols, list) else []}
        return {"symbols": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/portfolio/refresh")
async def refresh_portfolio():
    """Trigger portfolio refresh."""
    # This would trigger the actual IB sync
    return {"status": "initiated", "message": "Portfolio refresh started"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
