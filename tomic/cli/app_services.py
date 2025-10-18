from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tomic import config as cfg
from tomic.cli import services as cli_services
from tomic.services.market_snapshot_service import MarketSnapshotService
from tomic.services.portfolio_service import PortfolioService
from tomic.services.strategy_pipeline import StrategyPipeline


@dataclass
class ExportServices:
    """Wrapper for export and data retrieval helpers used by the CLI."""

    export_chain: Callable[..., Path | None]
    fetch_polygon_chain: Callable[..., Path | None]
    find_latest_chain: Callable[..., Path | None]
    git_commit: Callable[..., bool]


@dataclass
class ControlPanelServices:
    """Container bundling long-lived services required by the control panel."""

    pipeline_factory: Callable[[], StrategyPipeline]
    market_snapshot: MarketSnapshotService
    portfolio: PortfolioService
    export: ExportServices
    _pipeline: StrategyPipeline | None = field(default=None, init=False, repr=False)

    def get_pipeline(self) -> StrategyPipeline:
        if self._pipeline is None:
            self._pipeline = self.pipeline_factory()
        return self._pipeline


def create_controlpanel_services(
    *,
    strike_selector_factory: Callable[..., object],
    strategy_generator: Callable[..., object],
) -> ControlPanelServices:
    """Construct the service container used by the control panel menus."""

    def _pipeline_factory() -> StrategyPipeline:
        return StrategyPipeline(
            cfg,
            None,
            strike_selector_factory=strike_selector_factory,
            strategy_generator=strategy_generator,
        )

    export = ExportServices(
        export_chain=cli_services.export_chain,
        fetch_polygon_chain=cli_services.fetch_polygon_chain,
        find_latest_chain=cli_services.find_latest_chain,
        git_commit=cli_services.git_commit,
    )

    return ControlPanelServices(
        pipeline_factory=_pipeline_factory,
        market_snapshot=MarketSnapshotService(cfg),
        portfolio=PortfolioService(),
        export=export,
    )
