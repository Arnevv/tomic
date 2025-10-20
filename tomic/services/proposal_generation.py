"""Service helpers for generating strategy proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Mapping, Sequence

from tomic.analysis.proposal_engine import generate_proposals
from tomic.analysis.vol_json import load_latest_summaries
from tomic.config import get as cfg_get


class ProposalGenerationError(RuntimeError):
    """Raised when proposals cannot be generated."""


@dataclass(frozen=True)
class ProposalGenerationResult:
    proposals: Mapping[str, Sequence[Mapping[str, object]]]
    metrics: Mapping[str, object] | None
    warnings: Sequence[str]


def _load_positions(path: Path) -> Iterable[dict]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ProposalGenerationError("Positions-bestand bevat geen lijst")
    return raw


def _load_metrics_from_file(path: Path) -> Mapping[str, object]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ProposalGenerationError("Metrics-bestand bevat geen object")
    return {sym: SimpleNamespace(**vals) for sym, vals in raw.items()}


def _load_metrics_for_symbols(symbols: Iterable[str]) -> Mapping[str, object]:
    return load_latest_summaries(symbols)


def generate_proposal_overview(
    positions_path: str | Path | None = None,
    export_dir: str | Path | None = None,
    metrics_path: str | Path | None = None,
) -> ProposalGenerationResult:
    """Return generated proposals together with bookkeeping information."""

    positions_file = Path(positions_path or cfg_get("POSITIONS_FILE", "positions.json"))
    export_path = Path(export_dir or cfg_get("EXPORT_DIR", "exports"))
    metrics_file = Path(metrics_path) if metrics_path else None

    if not positions_file.exists():
        raise ProposalGenerationError(f"Positions file not found: {positions_file}")

    warnings: list[str] = []
    positions = list(_load_positions(positions_file))

    metrics: Mapping[str, object] | None = None
    if metrics_file:
        if metrics_file.exists():
            try:
                metrics = _load_metrics_from_file(metrics_file)
            except Exception as exc:  # pragma: no cover - defensive logging
                warnings.append(f"Kan metrics niet laden: {exc}")
                metrics = None
        else:
            warnings.append(f"Metrics file not found: {metrics_file}")
    else:
        try:
            symbols = {p.get("symbol") for p in positions if isinstance(p, dict)}
            metrics = _load_metrics_for_symbols(filter(None, symbols))
        except Exception as exc:  # pragma: no cover - data source optional
            warnings.append(f"Volatiliteitsdata niet beschikbaar: {exc}")
            metrics = None

    proposals = generate_proposals(
        str(positions_file),
        str(export_path),
        metrics=metrics,
    )

    return ProposalGenerationResult(
        proposals=proposals or {},
        metrics=metrics,
        warnings=tuple(warnings),
    )


__all__ = [
    "ProposalGenerationResult",
    "ProposalGenerationError",
    "generate_proposal_overview",
]

