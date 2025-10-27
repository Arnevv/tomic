"""Centralised utilities to resolve option chain data sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal, Sequence

from ..logutils import logger

ChainSourceName = Literal["polygon", "tws"]


class ChainSourceError(RuntimeError):
    """Raised when the requested option chain source is unavailable."""


@dataclass(frozen=True, slots=True)
class ChainSourceDecision:
    """Represents a resolved option chain together with provenance metadata."""

    symbol: str
    source: ChainSourceName
    path: Path
    source_provenance: str
    schema_version: str | None = None


def _format_patterns(symbol: str, templates: Iterable[str]) -> list[str]:
    symbol_upper = symbol.upper()
    symbol_lower = symbol.lower()
    return [
        template.format(
            symbol=symbol,
            symbol_upper=symbol_upper,
            symbol_lower=symbol_lower,
        )
        for template in templates
    ]


class PolygonFileAdapter:
    """Adapter that resolves locally stored Polygon option chain CSV files."""

    def __init__(
        self,
        *,
        export_dir: Path,
        fetcher: Callable[[str], object] | None = None,
        patterns: Sequence[str] | None = None,
        schema_version: str | None = None,
    ) -> None:
        self._export_dir = export_dir
        self._fetcher = fetcher
        self._pattern_templates: tuple[str, ...] = tuple(
            patterns
            or (
                "{symbol_upper}_*-optionchainpolygon.csv",
                "option_chain_{symbol_upper}_*.csv",
                "{symbol_upper}_*-optionchain.csv",
            )
        )
        self._schema_version = schema_version

    def acquire(self, symbol: str, *, existing_dir: Path | None = None) -> ChainSourceDecision:
        """Return the most recent Polygon CSV for ``symbol``.

        When ``existing_dir`` is provided it is searched before consulting the
        configured export directory.  If a ``fetcher`` was supplied the adapter
        will invoke it when no CSV is found locally.
        """

        search_patterns = _format_patterns(symbol, self._pattern_templates)

        if existing_dir is not None:
            logger.debug(
                "Searching %s for Polygon chains of %s using patterns %s",
                existing_dir,
                symbol,
                search_patterns,
            )
            path = self._find_latest(existing_dir, search_patterns)
            if path is not None:
                logger.info("Using Polygon chain for %s from %s", symbol, path)
                return ChainSourceDecision(
                    symbol=symbol,
                    source="polygon",
                    path=path,
                    source_provenance=str(path),
                    schema_version=self._schema_version,
                )

        if self._fetcher is not None:
            logger.info("Fetching Polygon chain for %s", symbol)
            try:
                self._fetcher(symbol)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Polygon fetch failed for %s: %s", symbol, exc, exc_info=True)
                raise ChainSourceError(
                    f"Polygon-chain voor {symbol} kon niet worden opgehaald."
                    " Controleer de netwerkverbinding en probeer opnieuw."
                ) from exc

        logger.debug(
            "Searching %s for Polygon chains of %s using patterns %s",
            self._export_dir,
            symbol,
            search_patterns,
        )
        path = self._find_latest(self._export_dir, search_patterns)
        if path is None:
            base = existing_dir if existing_dir is not None else self._export_dir
            raise ChainSourceError(
                "Geen Polygon-chain gevonden voor "
                f"{symbol} in {base}. Download een nieuwe chain via 'Download"
                " nieuwe chain via Polygon' of controleer het pad."
            )

        logger.info("Using Polygon chain for %s from %s", symbol, path)
        return ChainSourceDecision(
            symbol=symbol,
            source="polygon",
            path=path,
            source_provenance=str(path),
            schema_version=self._schema_version,
        )

    @staticmethod
    def _find_latest(base: Path, patterns: Sequence[str]) -> Path | None:
        if not base.exists():
            return None
        matches: list[Path] = []
        for pattern in patterns:
            matches.extend(base.rglob(pattern))
        if not matches:
            return None
        return max(matches, key=lambda candidate: candidate.stat().st_mtime)


class TwsLiveAdapter:
    """Adapter that exports live chains using the TWS API."""

    def __init__(
        self,
        *,
        exporter: Callable[[str], Path | None],
        schema_version: str | None = None,
    ) -> None:
        self._exporter = exporter
        self._schema_version = schema_version

    def acquire(self, symbol: str) -> ChainSourceDecision:
        logger.info("Exporting TWS option chain for %s", symbol)
        path = self._exporter(symbol)
        if path is None:
            raise ChainSourceError(
                f"TWS-chain voor {symbol} kon niet worden opgehaald."
                " Zorg dat TWS of IB Gateway verbonden is en probeer opnieuw."
            )
        logger.info("Using TWS chain for %s from %s", symbol, path)
        return ChainSourceDecision(
            symbol=symbol,
            source="tws",
            path=path,
            source_provenance=str(path),
            schema_version=self._schema_version,
        )


def resolve_chain_source(
    symbol: str,
    *,
    source: ChainSourceName,
    polygon: PolygonFileAdapter,
    tws: TwsLiveAdapter,
    existing_dir: Path | None = None,
) -> ChainSourceDecision:
    """Resolve an option chain based on the selected ``source``."""

    if source == "polygon":
        decision = polygon.acquire(symbol, existing_dir=existing_dir)
    elif source == "tws":
        decision = tws.acquire(symbol)
    else:  # pragma: no cover - defensive guard against invalid input
        raise ChainSourceError(f"Onbekende chain-bron: {source!r}")

    logger.debug(
        "Chain source decision for %s: %s (%s, schema=%s)",
        symbol,
        decision.source,
        decision.source_provenance,
        decision.schema_version,
    )
    return decision


__all__ = [
    "ChainSourceDecision",
    "ChainSourceError",
    "ChainSourceName",
    "PolygonFileAdapter",
    "TwsLiveAdapter",
    "resolve_chain_source",
]

