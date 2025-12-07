"""Service layer helpers for CLI orchestration.

Imports are lazy to avoid loading heavy dependencies (like ibapi) when only
lightweight modules such as chain_sources are needed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import hints only
    from .strategy_pipeline import (
        StrategyPipeline,
        StrategyContext,
        StrategyProposal,
        RejectionSummary,
    )
    from .pipeline_refresh import (
        PipelineError,
        PipelineStats,
        PipelineTimeout,
        Proposal,
        RefreshContext,
        RefreshParams,
        RefreshResult,
        RefreshSource,
        Rejection,
        build_proposal_from_entry,
        refresh_pipeline,
    )
    from .proposal_details import (
        ProposalCore,
        build_proposal_core,
        build_proposal_viewmodel,
    )

_LAZY_ATTRS = {
    # strategy_pipeline
    "StrategyPipeline": "tomic.services.strategy_pipeline",
    "StrategyContext": "tomic.services.strategy_pipeline",
    "StrategyProposal": "tomic.services.strategy_pipeline",
    "RejectionSummary": "tomic.services.strategy_pipeline",
    # pipeline_refresh
    "PipelineError": "tomic.services.pipeline_refresh",
    "PipelineStats": "tomic.services.pipeline_refresh",
    "PipelineTimeout": "tomic.services.pipeline_refresh",
    "Proposal": "tomic.services.pipeline_refresh",
    "RefreshContext": "tomic.services.pipeline_refresh",
    "RefreshParams": "tomic.services.pipeline_refresh",
    "RefreshResult": "tomic.services.pipeline_refresh",
    "RefreshSource": "tomic.services.pipeline_refresh",
    "Rejection": "tomic.services.pipeline_refresh",
    "build_proposal_from_entry": "tomic.services.pipeline_refresh",
    "refresh_pipeline": "tomic.services.pipeline_refresh",
    # proposal_details
    "ProposalCore": "tomic.services.proposal_details",
    "build_proposal_core": "tomic.services.proposal_details",
    "build_proposal_viewmodel": "tomic.services.proposal_details",
}


def __getattr__(name: str):
    module_name = _LAZY_ATTRS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name)
    attr = getattr(module, name)
    globals()[name] = attr
    return attr


__all__ = [
    "StrategyPipeline",
    "StrategyContext",
    "StrategyProposal",
    "RejectionSummary",
    "PipelineError",
    "PipelineStats",
    "PipelineTimeout",
    "Proposal",
    "RefreshContext",
    "RefreshParams",
    "RefreshResult",
    "RefreshSource",
    "Rejection",
    "build_proposal_from_entry",
    "refresh_pipeline",
    "ProposalCore",
    "build_proposal_core",
    "build_proposal_viewmodel",
]
