"""Symbol qualification service for strategy eligibility tracking.

Tracks which symbols are qualified/disqualified for each strategy (Calendar, Iron Condor).
Simple MVP: JSON file storage with status and reason per strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from tomic.logutils import logger

# Type aliases
QualificationStatus = Literal["qualified", "disqualified", "watchlist"]
StrategyType = Literal["calendar", "iron_condor"]

STRATEGIES: List[StrategyType] = ["calendar", "iron_condor"]
VALID_STATUSES: List[QualificationStatus] = ["qualified", "disqualified", "watchlist"]


@dataclass
class StrategyQualification:
    """Qualification status for a single strategy."""

    status: QualificationStatus
    reason: str = ""
    updated: Optional[str] = None  # ISO format timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "reason": self.reason,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyQualification":
        """Create from dictionary."""
        return cls(
            status=data.get("status", "qualified"),
            reason=data.get("reason", ""),
            updated=data.get("updated"),
        )


@dataclass
class SymbolQualification:
    """Qualification data for a symbol across all strategies."""

    symbol: str
    calendar: StrategyQualification
    iron_condor: StrategyQualification

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "calendar": self.calendar.to_dict(),
            "iron_condor": self.iron_condor.to_dict(),
        }

    @classmethod
    def from_dict(cls, symbol: str, data: Dict[str, Any]) -> "SymbolQualification":
        """Create from dictionary."""
        return cls(
            symbol=symbol,
            calendar=StrategyQualification.from_dict(data.get("calendar", {})),
            iron_condor=StrategyQualification.from_dict(data.get("iron_condor", {})),
        )

    @classmethod
    def default(cls, symbol: str) -> "SymbolQualification":
        """Create default qualification (all qualified, no reason)."""
        return cls(
            symbol=symbol,
            calendar=StrategyQualification(status="qualified"),
            iron_condor=StrategyQualification(status="qualified"),
        )

    def get_strategy(self, strategy: StrategyType) -> StrategyQualification:
        """Get qualification for a specific strategy."""
        if strategy == "calendar":
            return self.calendar
        return self.iron_condor

    def set_strategy(
        self,
        strategy: StrategyType,
        status: QualificationStatus,
        reason: str = "",
    ) -> None:
        """Set qualification for a specific strategy."""
        qual = StrategyQualification(
            status=status,
            reason=reason,
            updated=datetime.now().strftime("%Y-%m-%d"),
        )
        if strategy == "calendar":
            self.calendar = qual
        else:
            self.iron_condor = qual


class QualificationService:
    """Service for managing symbol qualifications."""

    def __init__(self, base_dir: Optional[Path] = None):
        """Initialize the qualification service.

        Args:
            base_dir: Base directory for data files. Defaults to tomic root.
        """
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
        self.base_dir = base_dir
        self._cache: Optional[Dict[str, SymbolQualification]] = None

    def _get_data_path(self) -> Path:
        """Get path to qualification data file."""
        return self.base_dir / "tomic" / "data" / "symbol_qualification.json"

    def _load_raw(self) -> Dict[str, Any]:
        """Load raw JSON data from file."""
        path = self._get_data_path()
        if not path.exists():
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load qualification data: {e}")
            return {}

    def _save_raw(self, data: Dict[str, Any]) -> None:
        """Save raw JSON data to file."""
        path = self._get_data_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
        except OSError as e:
            logger.error(f"Failed to save qualification data: {e}")

    def load_all(self) -> Dict[str, SymbolQualification]:
        """Load all symbol qualifications.

        Returns:
            Dictionary mapping symbol to qualification data.
        """
        if self._cache is not None:
            return self._cache

        raw = self._load_raw()
        self._cache = {
            symbol: SymbolQualification.from_dict(symbol, data)
            for symbol, data in raw.items()
        }
        return self._cache

    def save_all(self, qualifications: Dict[str, SymbolQualification]) -> None:
        """Save all symbol qualifications.

        Args:
            qualifications: Dictionary mapping symbol to qualification data.
        """
        raw = {
            symbol: qual.to_dict()
            for symbol, qual in qualifications.items()
        }
        self._save_raw(raw)
        self._cache = qualifications

    def get(self, symbol: str) -> SymbolQualification:
        """Get qualification for a symbol.

        If symbol doesn't exist, returns default (all qualified).

        Args:
            symbol: The symbol to get qualification for.

        Returns:
            SymbolQualification for the symbol.
        """
        all_quals = self.load_all()
        symbol = symbol.upper()
        if symbol not in all_quals:
            return SymbolQualification.default(symbol)
        return all_quals[symbol]

    def update(
        self,
        symbol: str,
        strategy: StrategyType,
        status: QualificationStatus,
        reason: str = "",
    ) -> SymbolQualification:
        """Update qualification for a symbol/strategy.

        Args:
            symbol: The symbol to update.
            strategy: The strategy to update.
            status: New status.
            reason: Reason for the status (optional).

        Returns:
            Updated SymbolQualification.
        """
        symbol = symbol.upper()
        all_quals = self.load_all()

        if symbol not in all_quals:
            all_quals[symbol] = SymbolQualification.default(symbol)

        all_quals[symbol].set_strategy(strategy, status, reason)
        self.save_all(all_quals)

        logger.info(f"Updated {symbol} {strategy} -> {status}: {reason}")
        return all_quals[symbol]

    def get_qualified_symbols(
        self,
        strategy: StrategyType,
        configured_symbols: List[str],
    ) -> List[str]:
        """Get list of qualified symbols for a strategy.

        Only returns symbols that are both configured AND qualified.

        Args:
            strategy: The strategy to filter for.
            configured_symbols: List of currently configured symbols.

        Returns:
            List of qualified symbols.
        """
        all_quals = self.load_all()
        qualified = []

        for symbol in configured_symbols:
            symbol = symbol.upper()
            if symbol in all_quals:
                qual = all_quals[symbol].get_strategy(strategy)
                if qual.status == "qualified":
                    qualified.append(symbol)
            else:
                # Not in qualification file = qualified by default
                qualified.append(symbol)

        return qualified

    def get_matrix(
        self,
        symbols: List[str],
    ) -> List[Dict[str, Any]]:
        """Get qualification matrix for display.

        Args:
            symbols: List of symbols to include.

        Returns:
            List of dicts with symbol and strategy statuses.
        """
        all_quals = self.load_all()
        matrix = []

        for symbol in symbols:
            symbol = symbol.upper()
            qual = all_quals.get(symbol, SymbolQualification.default(symbol))

            matrix.append({
                "symbol": symbol,
                "calendar_status": qual.calendar.status,
                "calendar_reason": qual.calendar.reason,
                "iron_condor_status": qual.iron_condor.status,
                "iron_condor_reason": qual.iron_condor.reason,
            })

        return matrix

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        self._cache = None


# Module-level instance for convenience
_service: Optional[QualificationService] = None


def get_qualification_service() -> QualificationService:
    """Get or create the qualification service singleton."""
    global _service
    if _service is None:
        _service = QualificationService()
    return _service
