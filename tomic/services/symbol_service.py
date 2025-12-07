"""Symbol management service for basket optimization.

Provides functionality to add/remove symbols with automatic data fetching,
sector classification, and liquidity metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.config import get as cfg_get, update as cfg_update
from tomic.logutils import logger


@dataclass
class SymbolMetadata:
    """Metadata for a single symbol including sector and liquidity info."""

    symbol: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    avg_atm_call_volume: Optional[int] = None
    avg_atm_call_oi: Optional[int] = None
    last_updated: Optional[str] = None
    data_status: str = "unknown"  # unknown, complete, incomplete, missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SymbolMetadata":
        """Create from dictionary."""
        return cls(
            symbol=data.get("symbol", ""),
            sector=data.get("sector"),
            industry=data.get("industry"),
            market_cap=data.get("market_cap"),
            avg_atm_call_volume=data.get("avg_atm_call_volume"),
            avg_atm_call_oi=data.get("avg_atm_call_oi"),
            last_updated=data.get("last_updated"),
            data_status=data.get("data_status", "unknown"),
        )


@dataclass
class DataValidationResult:
    """Result of data validation for a symbol."""

    symbol: str
    has_spot_prices: bool = False
    has_iv_summary: bool = False
    has_earnings: bool = False
    spot_price_days: int = 0
    iv_summary_days: int = 0
    missing_files: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if all required data is present."""
        return self.has_spot_prices and self.has_iv_summary

    @property
    def status(self) -> str:
        """Get status string."""
        if self.is_complete:
            return "complete"
        if self.has_spot_prices or self.has_iv_summary:
            return "incomplete"
        return "missing"


class SymbolService:
    """Service for managing symbols and their associated data."""

    def __init__(self, base_dir: Optional[Path] = None):
        """Initialize the symbol service.

        Args:
            base_dir: Base directory for data files. Defaults to tomic root.
        """
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
        self.base_dir = base_dir
        self._metadata_cache: Dict[str, SymbolMetadata] = {}

    # -------------------------------------------------------------------------
    # Path helpers
    # -------------------------------------------------------------------------

    def _get_data_dir(self) -> Path:
        """Get the data directory path."""
        return self.base_dir / "tomic" / "data"

    def _get_spot_prices_dir(self) -> Path:
        """Get spot prices directory."""
        return self.base_dir / cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices")

    def _get_iv_summary_dir(self) -> Path:
        """Get IV daily summary directory."""
        return self.base_dir / cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary")

    def _get_metadata_path(self) -> Path:
        """Get path to symbol metadata file."""
        return self._get_data_dir() / "symbol_metadata.json"

    def _get_earnings_path(self) -> Path:
        """Get path to earnings dates file."""
        return self.base_dir / cfg_get("EARNINGS_DATES_FILE", "tomic/data/earnings_dates.json")

    def _get_price_meta_path(self) -> Path:
        """Get path to price meta file."""
        return self.base_dir / cfg_get("PRICE_META_FILE", "price_meta.json")

    # -------------------------------------------------------------------------
    # Symbol list management
    # -------------------------------------------------------------------------

    def get_configured_symbols(self) -> List[str]:
        """Get list of currently configured symbols."""
        return [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    def set_configured_symbols(self, symbols: List[str]) -> None:
        """Update the configured symbols list."""
        cfg_update({"DEFAULT_SYMBOLS": [s.upper() for s in symbols]})

    def add_to_config(self, symbols: List[str]) -> List[str]:
        """Add symbols to configuration.

        Args:
            symbols: List of symbols to add.

        Returns:
            List of newly added symbols (excludes already existing).
        """
        current = set(self.get_configured_symbols())
        to_add = [s.upper() for s in symbols if s.upper() not in current]

        if to_add:
            new_list = sorted(current | set(to_add))
            self.set_configured_symbols(new_list)

        return to_add

    def remove_from_config(self, symbols: List[str]) -> List[str]:
        """Remove symbols from configuration.

        Args:
            symbols: List of symbols to remove.

        Returns:
            List of actually removed symbols.
        """
        current = set(self.get_configured_symbols())
        to_remove = [s.upper() for s in symbols if s.upper() in current]

        if to_remove:
            new_list = sorted(current - set(to_remove))
            self.set_configured_symbols(new_list)

        return to_remove

    # -------------------------------------------------------------------------
    # Data file management
    # -------------------------------------------------------------------------

    def get_symbol_data_files(self, symbol: str) -> Dict[str, Path]:
        """Get paths to all data files for a symbol.

        Args:
            symbol: The symbol to get files for.

        Returns:
            Dictionary mapping file type to path.
        """
        symbol = symbol.upper()
        return {
            "spot_prices": self._get_spot_prices_dir() / f"{symbol}.json",
            "iv_summary": self._get_iv_summary_dir() / f"{symbol}.json",
        }

    def delete_symbol_data(self, symbol: str) -> List[str]:
        """Delete all data files for a symbol.

        Args:
            symbol: The symbol to delete data for.

        Returns:
            List of deleted file paths.
        """
        symbol = symbol.upper()
        deleted = []

        for file_type, path in self.get_symbol_data_files(symbol).items():
            if path.exists():
                try:
                    path.unlink()
                    deleted.append(str(path))
                    logger.info(f"Deleted {file_type} for {symbol}: {path}")
                except OSError as e:
                    logger.warning(f"Failed to delete {path}: {e}")

        # Remove from price_meta.json
        self._remove_from_price_meta(symbol)

        # Remove from symbol_metadata.json
        self._remove_symbol_metadata(symbol)

        # Remove from earnings_dates.json
        self._remove_from_earnings(symbol)

        return deleted

    def _remove_from_price_meta(self, symbol: str) -> bool:
        """Remove symbol from price_meta.json."""
        path = self._get_price_meta_path()
        if not path.exists():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if symbol.upper() in data:
                del data[symbol.upper()]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to update price_meta.json: {e}")

        return False

    def _remove_from_earnings(self, symbol: str) -> bool:
        """Remove symbol from earnings_dates.json."""
        path = self._get_earnings_path()
        if not path.exists():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if symbol.upper() in data:
                del data[symbol.upper()]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to update earnings_dates.json: {e}")

        return False

    # -------------------------------------------------------------------------
    # Data validation
    # -------------------------------------------------------------------------

    def validate_symbol_data(self, symbol: str) -> DataValidationResult:
        """Validate data completeness for a symbol.

        Args:
            symbol: The symbol to validate.

        Returns:
            DataValidationResult with validation details.
        """
        symbol = symbol.upper()
        result = DataValidationResult(symbol=symbol)
        files = self.get_symbol_data_files(symbol)

        # Check spot prices
        spot_path = files["spot_prices"]
        if spot_path.exists():
            try:
                with open(spot_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    result.has_spot_prices = True
                    result.spot_price_days = len(data)
            except (json.JSONDecodeError, OSError):
                pass

        if not result.has_spot_prices:
            result.missing_files.append("spot_prices")

        # Check IV summary
        iv_path = files["iv_summary"]
        if iv_path.exists():
            try:
                with open(iv_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    result.has_iv_summary = True
                    result.iv_summary_days = len(data)
            except (json.JSONDecodeError, OSError):
                pass

        if not result.has_iv_summary:
            result.missing_files.append("iv_summary")

        # Check earnings
        earnings_path = self._get_earnings_path()
        if earnings_path.exists():
            try:
                with open(earnings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if symbol in data:
                    result.has_earnings = True
            except (json.JSONDecodeError, OSError):
                pass

        return result

    def validate_all_symbols(self) -> Dict[str, DataValidationResult]:
        """Validate data for all configured symbols.

        Returns:
            Dictionary mapping symbol to validation result.
        """
        results = {}
        for symbol in self.get_configured_symbols():
            results[symbol] = self.validate_symbol_data(symbol)
        return results

    # -------------------------------------------------------------------------
    # Orphaned data detection
    # -------------------------------------------------------------------------

    def find_orphaned_data(self) -> Dict[str, List[str]]:
        """Find data files for symbols not in configuration.

        Returns:
            Dictionary mapping symbol to list of orphaned file paths.
        """
        configured = set(self.get_configured_symbols())
        orphaned: Dict[str, List[str]] = {}

        # Check spot prices directory
        spot_dir = self._get_spot_prices_dir()
        if spot_dir.exists():
            for file in spot_dir.glob("*.json"):
                symbol = file.stem.upper()
                if symbol not in configured:
                    if symbol not in orphaned:
                        orphaned[symbol] = []
                    orphaned[symbol].append(str(file))

        # Check IV summary directory
        iv_dir = self._get_iv_summary_dir()
        if iv_dir.exists():
            for file in iv_dir.glob("*.json"):
                symbol = file.stem.upper()
                if symbol not in configured:
                    if symbol not in orphaned:
                        orphaned[symbol] = []
                    orphaned[symbol].append(str(file))

        return orphaned

    def cleanup_orphaned_data(self, symbols: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """Delete orphaned data files.

        Args:
            symbols: Specific symbols to clean up. If None, cleans all orphaned.

        Returns:
            Dictionary mapping symbol to list of deleted file paths.
        """
        orphaned = self.find_orphaned_data()
        deleted: Dict[str, List[str]] = {}

        for symbol, files in orphaned.items():
            if symbols is not None and symbol not in [s.upper() for s in symbols]:
                continue

            deleted[symbol] = []
            for file_path in files:
                try:
                    Path(file_path).unlink()
                    deleted[symbol].append(file_path)
                    logger.info(f"Deleted orphaned file: {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")

        return deleted

    # -------------------------------------------------------------------------
    # Symbol metadata management
    # -------------------------------------------------------------------------

    def load_all_metadata(self) -> Dict[str, SymbolMetadata]:
        """Load all symbol metadata from file.

        Returns:
            Dictionary mapping symbol to metadata.
        """
        path = self._get_metadata_path()
        if not path.exists():
            return {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                symbol: SymbolMetadata.from_dict({"symbol": symbol, **meta})
                for symbol, meta in data.items()
            }
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load symbol metadata: {e}")
            return {}

    def save_all_metadata(self, metadata: Dict[str, SymbolMetadata]) -> None:
        """Save all symbol metadata to file.

        Args:
            metadata: Dictionary mapping symbol to metadata.
        """
        path = self._get_metadata_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            symbol: {k: v for k, v in meta.to_dict().items() if k != "symbol"}
            for symbol, meta in metadata.items()
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to save symbol metadata: {e}")

    def get_symbol_metadata(self, symbol: str) -> Optional[SymbolMetadata]:
        """Get metadata for a single symbol.

        Args:
            symbol: The symbol to get metadata for.

        Returns:
            SymbolMetadata or None if not found.
        """
        all_meta = self.load_all_metadata()
        return all_meta.get(symbol.upper())

    def update_symbol_metadata(self, metadata: SymbolMetadata) -> None:
        """Update metadata for a single symbol.

        Args:
            metadata: The metadata to save.
        """
        all_meta = self.load_all_metadata()
        all_meta[metadata.symbol.upper()] = metadata
        self.save_all_metadata(all_meta)

    def update_symbols_metadata_batch(
        self,
        metadata_dict: Dict[str, SymbolMetadata],
        existing_metadata: Optional[Dict[str, SymbolMetadata]] = None,
    ) -> None:
        """Update metadata for multiple symbols in a single write.

        This is much more efficient than calling update_symbol_metadata()
        for each symbol individually, as it avoids repeated file I/O.

        Args:
            metadata_dict: Dictionary mapping symbol to metadata to update.
            existing_metadata: Optional pre-loaded metadata to merge with.
                             If None, loads from file.
        """
        if existing_metadata is None:
            all_meta = self.load_all_metadata()
        else:
            all_meta = existing_metadata.copy()

        # Update all symbols
        for symbol, metadata in metadata_dict.items():
            all_meta[symbol.upper()] = metadata

        self.save_all_metadata(all_meta)

    def _remove_symbol_metadata(self, symbol: str) -> bool:
        """Remove symbol from metadata file."""
        all_meta = self.load_all_metadata()
        if symbol.upper() in all_meta:
            del all_meta[symbol.upper()]
            self.save_all_metadata(all_meta)
            return True
        return False

    # -------------------------------------------------------------------------
    # Bulk operations
    # -------------------------------------------------------------------------

    def get_basket_summary(self) -> Dict[str, Any]:
        """Get summary of current basket.

        Returns:
            Dictionary with basket statistics.
        """
        symbols = self.get_configured_symbols()
        validations = self.validate_all_symbols()
        metadata = self.load_all_metadata()

        complete = sum(1 for v in validations.values() if v.is_complete)
        incomplete = sum(1 for v in validations.values() if v.status == "incomplete")
        missing = sum(1 for v in validations.values() if v.status == "missing")

        # Sector breakdown
        sectors: Dict[str, int] = {}
        for symbol in symbols:
            meta = metadata.get(symbol)
            sector = meta.sector if meta else "Unknown"
            sectors[sector] = sectors.get(sector, 0) + 1

        # Liquidity stats
        volumes = [
            m.avg_atm_call_volume
            for m in metadata.values()
            if m.avg_atm_call_volume is not None
        ]
        ois = [
            m.avg_atm_call_oi
            for m in metadata.values()
            if m.avg_atm_call_oi is not None
        ]

        return {
            "total_symbols": len(symbols),
            "data_complete": complete,
            "data_incomplete": incomplete,
            "data_missing": missing,
            "sectors": sectors,
            "avg_volume": int(sum(volumes) / len(volumes)) if volumes else None,
            "avg_oi": int(sum(ois) / len(ois)) if ois else None,
        }


# Module-level instance for convenience
_service: Optional[SymbolService] = None


def get_symbol_service() -> SymbolService:
    """Get or create the symbol service singleton."""
    global _service
    if _service is None:
        _service = SymbolService()
    return _service
