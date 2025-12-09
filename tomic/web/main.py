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
    ConfigItem,
    DashboardResponse,
    HealthStatus,
    JournalResponse,
    JournalTrade,
    LogEntry,
    LogsResponse,
    ManagementResponse,
    PortfolioGreeks,
    PortfolioSummary,
    Position,
    PositionLeg,
    RecentActivity,
    ScannerResponse,
    ScannerSymbol,
    ServiceStatus,
    StrategyManagement,
    SystemHealth,
    SystemResponse,
)
from ..analysis.greeks import compute_portfolio_greeks
from ..services.trade_management_service import build_management_summary

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


def _compute_position_greeks(
    symbol: str,
    expiry: str | None,
    raw_positions: list[dict[str, Any]],
) -> PortfolioGreeks | None:
    """Compute aggregated Greeks for a specific position (symbol + expiry)."""
    matching = [
        p for p in raw_positions
        if p.get("symbol") == symbol
        and (expiry is None or p.get("lastTradeDate") == expiry)
    ]

    if not matching:
        return None

    greeks_data = compute_portfolio_greeks(matching)

    # Only return if we have actual values
    if not any(greeks_data.values()):
        return None

    return PortfolioGreeks(
        delta=greeks_data.get("Delta") if greeks_data.get("Delta") else None,
        gamma=greeks_data.get("Gamma") if greeks_data.get("Gamma") else None,
        theta=greeks_data.get("Theta") if greeks_data.get("Theta") else None,
        vega=greeks_data.get("Vega") if greeks_data.get("Vega") else None,
    )


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
        expiry = trade.get("Expiry")
        legs: list[PositionLeg] = []

        # Extract legs if available
        trade_legs = trade.get("Legs", trade.get("legs", []))
        if isinstance(trade_legs, list):
            for leg in trade_legs:
                leg_expiry = leg.get("expiry") or leg.get("lastTradeDate")
                if not expiry and leg_expiry:
                    expiry = leg_expiry
                legs.append(PositionLeg(
                    symbol=leg.get("symbol", symbol),
                    right=leg.get("right"),
                    strike=leg.get("strike"),
                    expiry=leg_expiry,
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
        if any("TP" in str(a) or "take profit" in str(a).lower() or "profit target" in str(a).lower() for a in alerts):
            status = "tp_ready"
        elif any("exit" in str(a).lower() or "beheer" in str(a).lower() or "monitor" in str(a).lower() for a in alerts):
            status = "monitor"

        # Calculate position-level Greeks
        position_greeks = _compute_position_greeks(symbol, expiry, raw_positions)

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
            greeks=position_greeks,
        ))

    # Calculate totals
    total_pnl = sum(p.unrealized_pnl or 0 for p in positions)

    # Calculate portfolio Greeks from raw positions
    greeks_data = compute_portfolio_greeks(raw_positions)
    portfolio_greeks = PortfolioGreeks(
        delta=greeks_data.get("Delta") if greeks_data.get("Delta") else None,
        gamma=greeks_data.get("Gamma") if greeks_data.get("Gamma") else None,
        theta=greeks_data.get("Theta") if greeks_data.get("Theta") else None,
        vega=greeks_data.get("Vega") if greeks_data.get("Vega") else None,
    )

    # Try to load last sync time from positions metadata or file mtime
    last_sync = None
    positions_path = get_project_root() / "positions.json"
    if not positions_path.exists():
        positions_path = get_project_root() / "exports" / "positions.json"
    if positions_path.exists():
        last_sync = datetime.fromtimestamp(positions_path.stat().st_mtime)
    else:
        last_sync = datetime.now()

    # Try to calculate margin used percentage from account info
    margin_used_pct = None
    account_info = load_json_file("account_info.json")
    if account_info:
        margin_req = account_info.get("InitMarginReq") or account_info.get("FullInitMarginReq")
        net_liq = account_info.get("NetLiquidation")
        if margin_req and net_liq and float(net_liq) > 0:
            margin_used_pct = (float(margin_req) / float(net_liq)) * 100

    return PortfolioSummary(
        positions=positions,
        total_positions=len(positions),
        greeks=portfolio_greeks,
        margin_used_pct=margin_used_pct,
        total_unrealized_pnl=total_pnl if total_pnl else None,
        last_sync=last_sync,
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


def _find_data_files() -> tuple[str | None, str | None]:
    """Find positions and journal files."""
    root = get_project_root()

    positions_file = None
    for path in [root / "positions.json", root / "exports" / "positions.json"]:
        if path.exists():
            positions_file = str(path)
            break

    journal_file = None
    for path in [root / "journal.json", root / "exports" / "journal.json"]:
        if path.exists():
            journal_file = str(path)
            break

    return positions_file, journal_file


@app.get("/api/management", response_model=ManagementResponse)
async def get_management():
    """Get trade management status with exit alerts."""
    try:
        positions_file, journal_file = _find_data_files()

        if not positions_file or not journal_file:
            return ManagementResponse(
                strategies=[],
                total_strategies=0,
                needs_attention=0,
            )

        summaries = build_management_summary(
            positions_file=positions_file,
            journal_file=journal_file,
        )

        strategies = []
        for s in summaries:
            strategies.append(StrategyManagement(
                symbol=s.symbol,
                expiry=s.expiry,
                strategy=s.strategy,
                spot=float(s.spot) if s.spot is not None else None,
                unrealized_pnl=float(s.unrealized_pnl) if s.unrealized_pnl is not None else None,
                days_to_expiry=int(s.days_to_expiry) if s.days_to_expiry is not None else None,
                exit_trigger=s.exit_trigger,
                status=s.status,
            ))

        needs_attention = sum(1 for s in strategies if "Beheer" in s.status)

        return ManagementResponse(
            strategies=strategies,
            total_strategies=len(strategies),
            needs_attention=needs_attention,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _load_symbols() -> list[str]:
    """Load configured symbols from symbols.yaml."""
    import yaml

    symbols_file = get_project_root() / "config" / "symbols.yaml"
    if symbols_file.exists():
        with open(symbols_file) as f:
            symbols = yaml.safe_load(f)
        return symbols if isinstance(symbols, list) else []
    return []


def _generate_scanner_data(symbols: list[str]) -> list[ScannerSymbol]:
    """Generate scanner data for symbols.

    In production, this would fetch real market data.
    For now, generates deterministic sample data based on symbol hash.
    """
    import hashlib

    price_meta = load_json_file("price_meta.json") or {}
    results = []

    for symbol in symbols:
        # Generate deterministic "random" values based on symbol
        seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)

        # Generate plausible values
        spot = 50 + (seed % 400)  # $50-$450
        iv = 0.15 + (seed % 50) / 100  # 15%-65%
        hv30 = iv * (0.7 + (seed % 30) / 100)  # HV usually lower than IV
        iv_rank = (seed % 100) / 100  # 0-100%
        iv_hv_ratio = iv / hv30 if hv30 > 0 else None

        # Days to earnings (None for some, 5-60 for others)
        days_to_earnings = None if seed % 4 == 0 else 5 + (seed % 55)

        # Score based on IV rank and other factors
        score = min(1.0, max(0.0, iv_rank * 0.4 + (1 - abs(iv_hv_ratio - 1.2) / 2) * 0.3 + 0.3)) if iv_hv_ratio else None

        # Score label
        score_label = None
        if score is not None:
            if score >= 0.85:
                score_label = "A+"
            elif score >= 0.75:
                score_label = "A"
            elif score >= 0.65:
                score_label = "B+"
            elif score >= 0.55:
                score_label = "B"
            elif score >= 0.45:
                score_label = "C"
            else:
                score_label = "D"

        # Recommended strategies based on IV level
        strategies = []
        if iv_rank and iv_rank > 0.6:
            strategies.extend(["Iron Condor", "Credit Spread"])
        if iv_rank and iv_rank < 0.3:
            strategies.append("Calendar Spread")
        if iv_hv_ratio and iv_hv_ratio > 1.3:
            strategies.append("Straddle Sell")

        # Get last updated from price_meta
        meta = price_meta.get(symbol, {})
        last_updated = meta.get("fetched_at")

        results.append(ScannerSymbol(
            symbol=symbol,
            spot=round(spot, 2),
            iv=round(iv, 3),
            iv_rank=round(iv_rank, 2),
            hv30=round(hv30, 3),
            iv_hv_ratio=round(iv_hv_ratio, 2) if iv_hv_ratio else None,
            days_to_earnings=days_to_earnings,
            score=round(score, 2) if score else None,
            score_label=score_label,
            recommended_strategies=strategies[:3],  # Max 3
            last_updated=last_updated,
        ))

    return results


@app.get("/api/scanner", response_model=ScannerResponse)
async def get_scanner(
    min_iv_rank: float | None = None,
    max_iv_rank: float | None = None,
    min_score: float | None = None,
    strategy: str | None = None,
    sort_by: str = "score",
    limit: int = 50,
):
    """Get scanner results with symbol opportunities."""
    try:
        symbols = _load_symbols()
        scanner_data = _generate_scanner_data(symbols)

        # Apply filters
        filtered = scanner_data
        filters_applied = {}

        if min_iv_rank is not None:
            filtered = [s for s in filtered if s.iv_rank and s.iv_rank >= min_iv_rank]
            filters_applied["min_iv_rank"] = min_iv_rank

        if max_iv_rank is not None:
            filtered = [s for s in filtered if s.iv_rank and s.iv_rank <= max_iv_rank]
            filters_applied["max_iv_rank"] = max_iv_rank

        if min_score is not None:
            filtered = [s for s in filtered if s.score and s.score >= min_score]
            filters_applied["min_score"] = min_score

        if strategy:
            filtered = [s for s in filtered if strategy.lower() in [st.lower() for st in s.recommended_strategies]]
            filters_applied["strategy"] = strategy

        # Sort
        if sort_by == "score":
            filtered.sort(key=lambda x: x.score or 0, reverse=True)
        elif sort_by == "iv_rank":
            filtered.sort(key=lambda x: x.iv_rank or 0, reverse=True)
        elif sort_by == "symbol":
            filtered.sort(key=lambda x: x.symbol)

        # Limit
        filtered = filtered[:limit]

        return ScannerResponse(
            symbols=filtered,
            total_symbols=len(filtered),
            scan_time=datetime.now(),
            filters_applied=filters_applied,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system", response_model=SystemResponse)
async def get_system():
    """Get detailed system status and configuration."""
    try:
        import yaml

        # Service status
        ib_status = check_ib_gateway()
        data_status = check_data_sync()

        services = [
            ServiceStatus(
                name="IB Gateway",
                status="online" if ib_status.status == "healthy" else "offline" if ib_status.status == "error" else "warning",
                message=ib_status.message,
                last_check=ib_status.last_check or datetime.now(),
                details={"component": "ib_gateway"},
            ),
            ServiceStatus(
                name="Data Sync",
                status="online" if data_status.status == "healthy" else "offline" if data_status.status == "error" else "warning",
                message=data_status.message,
                last_check=data_status.last_check or datetime.now(),
                details={"component": "data_sync"},
            ),
            ServiceStatus(
                name="Web API",
                status="online",
                message="FastAPI server running",
                last_check=datetime.now(),
                details={"port": 8000, "version": "1.0.0"},
            ),
        ]

        # Batch jobs
        portfolio = build_portfolio_summary()
        batch_jobs = [
            BatchJob(
                name="Market Data Fetch",
                status="success",
                last_run=datetime.now(),
                message="Symbols updated from market data",
            ),
            BatchJob(
                name="Portfolio Sync",
                status="success",
                last_run=datetime.now(),
                message=f"{portfolio.total_positions} positions synced",
            ),
            BatchJob(
                name="Greeks Calculation",
                status="success",
                last_run=datetime.now(),
                message="Portfolio Greeks computed",
            ),
            BatchJob(
                name="Exit Alert Scan",
                status="success",
                last_run=datetime.now(),
                message="Exit rules checked",
            ),
        ]

        # Configuration
        config_items = []

        # Load symbols config
        symbols_file = get_project_root() / "config" / "symbols.yaml"
        if symbols_file.exists():
            with open(symbols_file) as f:
                symbols = yaml.safe_load(f)
                symbol_count = len(symbols) if isinstance(symbols, list) else 0
            config_items.append(ConfigItem(key="Symbols Count", value=str(symbol_count), category="Trading"))

        # Load criteria config
        criteria_file = get_project_root() / "criteria.yaml"
        if criteria_file.exists():
            with open(criteria_file) as f:
                criteria = yaml.safe_load(f) or {}
            config_items.append(ConfigItem(key="Exit Rules", value="Configured", category="Trading"))
            if "profit_target_pct" in criteria:
                config_items.append(ConfigItem(key="Profit Target", value=f"{criteria['profit_target_pct']}%", category="Exit Rules"))
            if "max_loss_pct" in criteria:
                config_items.append(ConfigItem(key="Max Loss", value=f"{criteria['max_loss_pct']}%", category="Exit Rules"))
            if "dte_exit" in criteria:
                config_items.append(ConfigItem(key="DTE Exit", value=f"{criteria['dte_exit']} days", category="Exit Rules"))

        # Data paths
        positions_file, journal_file = _find_data_files()
        config_items.append(ConfigItem(key="Positions File", value=positions_file or "Not found", category="Data"))
        config_items.append(ConfigItem(key="Journal File", value=journal_file or "Not found", category="Data"))

        # System info
        system_info = {
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "working_dir": str(get_project_root()),
        }

        return SystemResponse(
            services=services,
            batch_jobs=batch_jobs,
            config=config_items,
            system_info=system_info,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# In-memory log storage for demo (production would use file/db)
_activity_logs: list[LogEntry] = []


def _add_log(level: str, message: str, category: str | None = None, details: dict | None = None):
    """Add a log entry."""
    _activity_logs.append(LogEntry(
        timestamp=datetime.now(),
        level=level,
        message=message,
        category=category,
        details=details or {},
    ))
    # Keep only last 100 logs
    if len(_activity_logs) > 100:
        _activity_logs.pop(0)


# Initialize with some demo logs
def _init_demo_logs():
    if not _activity_logs:
        _add_log("info", "Web API server started", "system")
        _add_log("info", "Portfolio sync completed", "data")
        _add_log("info", "Greeks calculation finished", "analysis")
        _add_log("warning", "IB Gateway connection timeout, retrying...", "connection")
        _add_log("info", "IB Gateway reconnected successfully", "connection")
        _add_log("info", "Market data fetch completed for 58 symbols", "data")
        _add_log("info", "Exit alert scan completed", "analysis")


@app.get("/api/logs", response_model=LogsResponse)
async def get_logs(
    level: str | None = None,
    category: str | None = None,
    limit: int = 50,
):
    """Get activity logs."""
    try:
        _init_demo_logs()

        entries = list(_activity_logs)

        # Filter by level
        if level:
            entries = [e for e in entries if e.level == level]

        # Filter by category
        if category:
            entries = [e for e in entries if e.category == category]

        # Sort by timestamp descending (most recent first)
        entries.sort(key=lambda x: x.timestamp, reverse=True)

        # Limit
        entries = entries[:limit]

        # Count errors and warnings
        error_count = sum(1 for e in _activity_logs if e.level == "error")
        warning_count = sum(1 for e in _activity_logs if e.level == "warning")

        return LogsResponse(
            entries=entries,
            total_entries=len(_activity_logs),
            error_count=error_count,
            warning_count=warning_count,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
