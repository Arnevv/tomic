"""Backtest API endpoints for TOMIC Web API.

Provides async backtest execution with job tracking for:
- What-If analysis (compare modified config vs live)
- Live config retrieval
- Job status polling
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from .models import (
    BacktestConfigRequest,
    BacktestEntryRules,
    BacktestExitRules,
    BacktestJobStatus,
    BacktestMetrics,
    BacktestPositionSizing,
    BacktestCosts,
    BacktestResultResponse,
    BacktestTrade,
    EquityCurvePoint,
    LiveConfigResponse,
    WhatIfComparisonResponse,
)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


# In-memory job storage (in production, use Redis or database)
_backtest_jobs: Dict[str, Dict[str, Any]] = {}
_job_lock = threading.Lock()


def get_project_root() -> Path:
    """Get the TOMIC project root directory."""
    return Path(__file__).parent.parent.parent


def _load_live_config(strategy_type: str = "iron_condor") -> Dict[str, Any]:
    """Load live configuration from YAML files.

    Combines settings from:
    - config/backtest.yaml or config/backtest_calendar.yaml
    - config/strategies.yaml
    - config/criteria.yaml
    """
    import yaml

    root = get_project_root()

    # Load backtest config based on strategy type
    if strategy_type == "calendar":
        config_path = root / "config" / "backtest_calendar.yaml"
    else:
        config_path = root / "config" / "backtest.yaml"

    if not config_path.exists():
        # Return defaults if config doesn't exist
        return _get_default_config(strategy_type)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return config


def _get_default_config(strategy_type: str) -> Dict[str, Any]:
    """Get default configuration for a strategy type."""
    if strategy_type == "calendar":
        return {
            "strategy_type": "calendar",
            "symbols": ["SPY", "QQQ", "IWM"],
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "target_dte": 45,
            "entry_rules": {
                "iv_percentile_max": 40.0,
            },
            "exit_rules": {
                "profit_target_pct": 10.0,
                "stop_loss_pct": 10.0,
                "min_dte": 5,
                "max_days_in_trade": 10,
            },
            "position_sizing": {
                "max_risk_per_trade": 200.0,
                "max_positions_per_symbol": 1,
                "max_total_positions": 10,
            },
            "costs": {
                "commission_per_contract": 1.0,
                "slippage_pct": 5.0,
            },
            "calendar_near_dte": 37,
            "calendar_far_dte": 75,
            "iron_condor_wing_width": 5,
            "iron_condor_short_delta": 0.16,
        }
    else:
        return {
            "strategy_type": "iron_condor",
            "symbols": ["SPY", "QQQ", "IWM"],
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "target_dte": 45,
            "entry_rules": {
                "iv_percentile_min": 60.0,
            },
            "exit_rules": {
                "profit_target_pct": 50.0,
                "stop_loss_pct": 100.0,
                "min_dte": 5,
                "max_days_in_trade": 45,
            },
            "position_sizing": {
                "max_risk_per_trade": 200.0,
                "max_positions_per_symbol": 1,
                "max_total_positions": 10,
            },
            "costs": {
                "commission_per_contract": 1.0,
                "slippage_pct": 5.0,
            },
            "iron_condor_wing_width": 5,
            "iron_condor_short_delta": 0.16,
            "calendar_near_dte": 37,
            "calendar_far_dte": 75,
        }


def _create_backtest_config(config_dict: Dict[str, Any]):
    """Create a BacktestConfig from dictionary."""
    from tomic.backtest.config import (
        BacktestConfig,
        EntryRulesConfig,
        ExitRulesConfig,
        PositionSizingConfig,
        CostConfig,
    )

    # Handle nested configs
    if "entry_rules" in config_dict and isinstance(config_dict["entry_rules"], dict):
        config_dict["entry_rules"] = EntryRulesConfig(**config_dict["entry_rules"])
    if "exit_rules" in config_dict and isinstance(config_dict["exit_rules"], dict):
        config_dict["exit_rules"] = ExitRulesConfig(**config_dict["exit_rules"])
    if "position_sizing" in config_dict and isinstance(config_dict["position_sizing"], dict):
        config_dict["position_sizing"] = PositionSizingConfig(**config_dict["position_sizing"])
    if "costs" in config_dict and isinstance(config_dict["costs"], dict):
        config_dict["costs"] = CostConfig(**config_dict["costs"])

    return BacktestConfig(**config_dict)


def _run_backtest_job(job_id: str, config_dict: Dict[str, Any]) -> None:
    """Run backtest in background thread."""
    from tomic.backtest.engine import BacktestEngine
    from tomic.backtest.results import TradeStatus

    try:
        with _job_lock:
            _backtest_jobs[job_id]["status"] = "running"
            _backtest_jobs[job_id]["started_at"] = datetime.now()

        # Create config object
        config = _create_backtest_config(config_dict)

        # Progress callback to update job status
        def progress_callback(message: str, percent: float) -> None:
            with _job_lock:
                if job_id in _backtest_jobs:
                    _backtest_jobs[job_id]["progress"] = percent
                    _backtest_jobs[job_id]["progress_message"] = message

        # Run the backtest
        engine = BacktestEngine(config=config, progress_callback=progress_callback)
        result = engine.run()

        # Convert result to serializable format
        metrics = None
        if result.combined_metrics:
            m = result.combined_metrics
            metrics = {
                "total_trades": m.total_trades,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "win_rate": m.win_rate,
                "total_pnl": m.total_pnl,
                "average_pnl": m.average_pnl,
                "average_winner": m.average_winner,
                "average_loser": m.average_loser,
                "profit_factor": m.profit_factor,
                "expectancy": m.expectancy,
                "total_return_pct": m.total_return_pct,
                "sharpe_ratio": m.sharpe_ratio,
                "sortino_ratio": m.sortino_ratio,
                "max_drawdown": m.max_drawdown,
                "max_drawdown_pct": m.max_drawdown_pct,
                "calmar_ratio": m.calmar_ratio,
                "sqn": m.sqn,
                "avg_days_in_trade": m.avg_days_in_trade,
                "exits_by_reason": m.exits_by_reason,
            }

        in_sample_metrics = None
        if result.in_sample_metrics:
            m = result.in_sample_metrics
            in_sample_metrics = {
                "total_trades": m.total_trades,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "win_rate": m.win_rate,
                "total_pnl": m.total_pnl,
                "sharpe_ratio": m.sharpe_ratio,
                "max_drawdown_pct": m.max_drawdown_pct,
                "profit_factor": m.profit_factor,
                "expectancy": m.expectancy,
                "avg_days_in_trade": m.avg_days_in_trade,
            }

        out_sample_metrics = None
        if result.out_sample_metrics:
            m = result.out_sample_metrics
            out_sample_metrics = {
                "total_trades": m.total_trades,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "win_rate": m.win_rate,
                "total_pnl": m.total_pnl,
                "sharpe_ratio": m.sharpe_ratio,
                "max_drawdown_pct": m.max_drawdown_pct,
                "profit_factor": m.profit_factor,
                "expectancy": m.expectancy,
                "avg_days_in_trade": m.avg_days_in_trade,
            }

        # Convert trades (limit to 500 for performance)
        trades = []
        for t in result.trades[:500]:
            trades.append({
                "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date) if t.exit_date else None,
                "symbol": t.symbol,
                "strategy_type": t.strategy_type,
                "iv_at_entry": t.iv_at_entry,
                "iv_at_exit": t.iv_at_exit,
                "spot_at_entry": t.spot_at_entry,
                "spot_at_exit": t.spot_at_exit,
                "max_risk": t.max_risk,
                "estimated_credit": t.estimated_credit,
                "final_pnl": t.final_pnl,
                "exit_reason": t.exit_reason.value if t.exit_reason else None,
                "days_in_trade": t.days_in_trade,
            })

        # Store result
        with _job_lock:
            _backtest_jobs[job_id]["status"] = "completed"
            _backtest_jobs[job_id]["completed_at"] = datetime.now()
            _backtest_jobs[job_id]["progress"] = 100
            _backtest_jobs[job_id]["result"] = {
                "config_summary": result.config_summary,
                "start_date": str(result.start_date) if result.start_date else None,
                "end_date": str(result.end_date) if result.end_date else None,
                "combined_metrics": metrics,
                "in_sample_metrics": in_sample_metrics,
                "out_sample_metrics": out_sample_metrics,
                "equity_curve": result.equity_curve[:200],  # Limit for performance
                "trades": trades,
                "degradation_score": result.degradation_score,
                "is_valid": result.is_valid,
                "validation_messages": result.validation_messages,
            }

    except Exception as e:
        with _job_lock:
            _backtest_jobs[job_id]["status"] = "failed"
            _backtest_jobs[job_id]["completed_at"] = datetime.now()
            _backtest_jobs[job_id]["error_message"] = str(e)


@router.get("/live-config/{strategy_type}", response_model=LiveConfigResponse)
async def get_live_config(strategy_type: str = "iron_condor"):
    """Get the current live configuration for a strategy type.

    This returns the baseline configuration that will be used
    for what-if comparisons.
    """
    if strategy_type not in ["iron_condor", "calendar"]:
        raise HTTPException(status_code=400, detail="Invalid strategy type")

    config = _load_live_config(strategy_type)

    # Extract nested configs with defaults
    entry_rules = config.get("entry_rules", {})
    exit_rules = config.get("exit_rules", {})
    position_sizing = config.get("position_sizing", {})
    costs = config.get("costs", {})

    return LiveConfigResponse(
        strategy_type=config.get("strategy_type", strategy_type),
        symbols=config.get("symbols", ["SPY", "QQQ", "IWM"]),
        start_date=config.get("start_date", "2023-01-01"),
        end_date=config.get("end_date", "2024-12-31"),
        target_dte=config.get("target_dte", 45),
        entry_rules=BacktestEntryRules(
            iv_percentile_min=entry_rules.get("iv_percentile_min"),
            iv_percentile_max=entry_rules.get("iv_percentile_max"),
            iv_rank_min=entry_rules.get("iv_rank_min"),
            iv_rank_max=entry_rules.get("iv_rank_max"),
            dte_min=entry_rules.get("dte_min"),
            dte_max=entry_rules.get("dte_max"),
            min_days_until_earnings=entry_rules.get("min_days_until_earnings"),
        ),
        exit_rules=BacktestExitRules(
            profit_target_pct=exit_rules.get("profit_target_pct", 50.0),
            stop_loss_pct=exit_rules.get("stop_loss_pct", 100.0),
            min_dte=exit_rules.get("min_dte", 5),
            max_days_in_trade=exit_rules.get("max_days_in_trade", 45),
            iv_collapse_threshold=exit_rules.get("iv_collapse_threshold"),
            delta_breach_threshold=exit_rules.get("delta_breach_threshold"),
        ),
        position_sizing=BacktestPositionSizing(
            max_risk_per_trade=position_sizing.get("max_risk_per_trade", 200.0),
            max_positions_per_symbol=position_sizing.get("max_positions_per_symbol", 1),
            max_total_positions=position_sizing.get("max_total_positions", 10),
        ),
        costs=BacktestCosts(
            commission_per_contract=costs.get("commission_per_contract", 1.0),
            slippage_pct=costs.get("slippage_pct", 5.0),
        ),
        iron_condor_wing_width=config.get("iron_condor_wing_width", 5),
        iron_condor_short_delta=config.get("iron_condor_short_delta", 0.16),
        calendar_near_dte=config.get("calendar_near_dte", 37),
        calendar_far_dte=config.get("calendar_far_dte", 75),
    )


@router.post("/run", response_model=BacktestJobStatus)
async def start_backtest(config: BacktestConfigRequest):
    """Start a new backtest job with the given configuration.

    Returns immediately with a job_id that can be used to poll for status.
    """
    # Load base config and merge with request
    base_config = _load_live_config(config.strategy_type)

    # Merge request config into base config
    if config.symbols is not None:
        base_config["symbols"] = config.symbols
    if config.start_date is not None:
        base_config["start_date"] = config.start_date
    if config.end_date is not None:
        base_config["end_date"] = config.end_date
    if config.target_dte is not None:
        base_config["target_dte"] = config.target_dte

    base_config["strategy_type"] = config.strategy_type

    # Merge entry rules
    if config.entry_rules is not None:
        if "entry_rules" not in base_config:
            base_config["entry_rules"] = {}
        for key, value in config.entry_rules.model_dump(exclude_none=True).items():
            base_config["entry_rules"][key] = value

    # Merge exit rules
    if config.exit_rules is not None:
        if "exit_rules" not in base_config:
            base_config["exit_rules"] = {}
        for key, value in config.exit_rules.model_dump(exclude_none=True).items():
            base_config["exit_rules"][key] = value

    # Merge position sizing
    if config.position_sizing is not None:
        if "position_sizing" not in base_config:
            base_config["position_sizing"] = {}
        for key, value in config.position_sizing.model_dump(exclude_none=True).items():
            base_config["position_sizing"][key] = value

    # Merge costs
    if config.costs is not None:
        if "costs" not in base_config:
            base_config["costs"] = {}
        for key, value in config.costs.model_dump(exclude_none=True).items():
            base_config["costs"][key] = value

    # Strategy-specific params
    if config.iron_condor_wing_width is not None:
        base_config["iron_condor_wing_width"] = config.iron_condor_wing_width
    if config.iron_condor_short_delta is not None:
        base_config["iron_condor_short_delta"] = config.iron_condor_short_delta
    if config.calendar_near_dte is not None:
        base_config["calendar_near_dte"] = config.calendar_near_dte
    if config.calendar_far_dte is not None:
        base_config["calendar_far_dte"] = config.calendar_far_dte

    # Create job
    job_id = str(uuid.uuid4())
    now = datetime.now()

    with _job_lock:
        _backtest_jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0.0,
            "progress_message": "Job queued",
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "config": base_config,
            "result": None,
        }

    # Start background thread
    thread = threading.Thread(
        target=_run_backtest_job,
        args=(job_id, base_config),
        daemon=True,
    )
    thread.start()

    return BacktestJobStatus(
        job_id=job_id,
        status="pending",
        progress=0.0,
        progress_message="Job queued",
        created_at=now,
    )


@router.get("/status/{job_id}", response_model=BacktestJobStatus)
async def get_backtest_status(job_id: str):
    """Get the status of a backtest job."""
    with _job_lock:
        if job_id not in _backtest_jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        job = _backtest_jobs[job_id]
        return BacktestJobStatus(
            job_id=job["job_id"],
            status=job["status"],
            progress=job["progress"],
            progress_message=job.get("progress_message"),
            created_at=job["created_at"],
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
            error_message=job.get("error_message"),
        )


@router.get("/result/{job_id}", response_model=BacktestResultResponse)
async def get_backtest_result(job_id: str):
    """Get the result of a completed backtest job."""
    with _job_lock:
        if job_id not in _backtest_jobs:
            raise HTTPException(status_code=404, detail="Job not found")

        job = _backtest_jobs[job_id]

        if job["status"] == "pending" or job["status"] == "running":
            return BacktestResultResponse(
                job_id=job_id,
                status=job["status"],
            )

        if job["status"] == "failed":
            return BacktestResultResponse(
                job_id=job_id,
                status="failed",
                validation_messages=[job.get("error_message", "Unknown error")],
            )

        result = job.get("result", {})

        # Convert metrics
        combined_metrics = None
        if result.get("combined_metrics"):
            combined_metrics = BacktestMetrics(**result["combined_metrics"])

        in_sample_metrics = None
        if result.get("in_sample_metrics"):
            in_sample_metrics = BacktestMetrics(**result["in_sample_metrics"])

        out_sample_metrics = None
        if result.get("out_sample_metrics"):
            out_sample_metrics = BacktestMetrics(**result["out_sample_metrics"])

        # Convert equity curve
        equity_curve = [
            EquityCurvePoint(**point) for point in result.get("equity_curve", [])
        ]

        # Convert trades
        trades = [
            BacktestTrade(**trade) for trade in result.get("trades", [])
        ]

        return BacktestResultResponse(
            job_id=job_id,
            status="completed",
            config_summary=result.get("config_summary", {}),
            start_date=result.get("start_date"),
            end_date=result.get("end_date"),
            combined_metrics=combined_metrics,
            in_sample_metrics=in_sample_metrics,
            out_sample_metrics=out_sample_metrics,
            equity_curve=equity_curve,
            trades=trades,
            degradation_score=result.get("degradation_score"),
            is_valid=result.get("is_valid", True),
            validation_messages=result.get("validation_messages", []),
        )


@router.post("/whatif", response_model=WhatIfComparisonResponse)
async def start_whatif_comparison(whatif_config: BacktestConfigRequest):
    """Start a what-if comparison between live config and modified config.

    Starts two backtest jobs:
    1. Live config (baseline)
    2. What-if config (with modifications)

    Returns both job IDs to poll for status.
    """
    # Start live config backtest
    live_config = BacktestConfigRequest(strategy_type=whatif_config.strategy_type)
    live_job = await start_backtest(live_config)

    # Start what-if backtest
    whatif_job = await start_backtest(whatif_config)

    return WhatIfComparisonResponse(
        live_job_id=live_job.job_id,
        whatif_job_id=whatif_job.job_id,
        live_status=live_job.status,
        whatif_status=whatif_job.status,
    )


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a backtest job from memory."""
    with _job_lock:
        if job_id in _backtest_jobs:
            del _backtest_jobs[job_id]
            return {"status": "deleted"}
        raise HTTPException(status_code=404, detail="Job not found")


@router.get("/jobs", response_model=list[BacktestJobStatus])
async def list_jobs():
    """List all backtest jobs."""
    with _job_lock:
        jobs = []
        for job in _backtest_jobs.values():
            jobs.append(BacktestJobStatus(
                job_id=job["job_id"],
                status=job["status"],
                progress=job["progress"],
                progress_message=job.get("progress_message"),
                created_at=job["created_at"],
                started_at=job.get("started_at"),
                completed_at=job.get("completed_at"),
                error_message=job.get("error_message"),
            ))
        return jobs
