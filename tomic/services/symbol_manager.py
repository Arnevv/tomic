"""Symbol manager for basket optimization.

Orchestrates symbol management operations including:
- Adding/removing symbols with automatic data fetching
- Sector classification from Polygon API
- Liquidity metrics from ORATS data
- Data validation and cleanup
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.services.symbol_service import (
    SymbolService,
    SymbolMetadata,
    DataValidationResult,
    get_symbol_service,
)
from tomic.services.liquidity_service import (
    LiquidityService,
    LiquidityMetrics,
    get_liquidity_service,
)


# SIC code to sector mapping
SIC_SECTOR_MAP = {
    # Technology
    "73": "Technology",
    "35": "Technology",
    "36": "Technology",
    "38": "Technology",
    "48": "Technology",
    # Financials
    "60": "Financials",
    "61": "Financials",
    "62": "Financials",
    "63": "Financials",
    "64": "Financials",
    "65": "Financials",
    "67": "Financials",
    # Healthcare
    "28": "Healthcare",
    "80": "Healthcare",
    "83": "Healthcare",
    # Consumer Discretionary
    "52": "Consumer Discretionary",
    "53": "Consumer Discretionary",
    "54": "Consumer Discretionary",
    "55": "Consumer Discretionary",
    "56": "Consumer Discretionary",
    "57": "Consumer Discretionary",
    "58": "Consumer Discretionary",
    "59": "Consumer Discretionary",
    "70": "Consumer Discretionary",
    "79": "Consumer Discretionary",
    # Consumer Staples
    "20": "Consumer Staples",
    "21": "Consumer Staples",
    "51": "Consumer Staples",
    # Industrials
    "15": "Industrials",
    "16": "Industrials",
    "17": "Industrials",
    "34": "Industrials",
    "37": "Industrials",
    "40": "Industrials",
    "41": "Industrials",
    "42": "Industrials",
    "44": "Industrials",
    "45": "Industrials",
    "47": "Industrials",
    # Energy
    "10": "Energy",
    "12": "Energy",
    "13": "Energy",
    "14": "Energy",
    "29": "Energy",
    "46": "Energy",
    # Materials
    "24": "Materials",
    "26": "Materials",
    "30": "Materials",
    "32": "Materials",
    "33": "Materials",
    # Utilities
    "49": "Utilities",
    # Real Estate
    "65": "Real Estate",
    # Communication Services
    "27": "Communication Services",
    "78": "Communication Services",
}

# ETF type mappings
ETF_SECTORS = {
    "SPY": "ETF - Index",
    "QQQ": "ETF - Index",
    "IWM": "ETF - Index",
    "DIA": "ETF - Index",
    "VTI": "ETF - Index",
    "VOO": "ETF - Index",
    "XLF": "ETF - Financials",
    "XLK": "ETF - Technology",
    "XLE": "ETF - Energy",
    "XLV": "ETF - Healthcare",
    "XLY": "ETF - Consumer Discretionary",
    "XLP": "ETF - Consumer Staples",
    "XLI": "ETF - Industrials",
    "XLB": "ETF - Materials",
    "XLU": "ETF - Utilities",
    "XLRE": "ETF - Real Estate",
    "XLC": "ETF - Communication Services",
    "GLD": "ETF - Commodities",
    "SLV": "ETF - Commodities",
    "TLT": "ETF - Bonds",
    "HYG": "ETF - Bonds",
    "EEM": "ETF - International",
    "EFA": "ETF - International",
    "VWO": "ETF - International",
    "ARKK": "ETF - Thematic",
}


@dataclass
class AddSymbolResult:
    """Result of adding a symbol."""

    symbol: str
    success: bool
    message: str
    metadata: Optional[SymbolMetadata] = None
    validation: Optional[DataValidationResult] = None
    data_fetched: bool = False


@dataclass
class RemoveSymbolResult:
    """Result of removing a symbol."""

    symbol: str
    success: bool
    message: str
    files_deleted: List[str] = None

    def __post_init__(self):
        if self.files_deleted is None:
            self.files_deleted = []


class SymbolManager:
    """High-level manager for symbol operations."""

    def __init__(
        self,
        symbol_service: Optional[SymbolService] = None,
        liquidity_service: Optional[LiquidityService] = None,
    ):
        """Initialize the symbol manager.

        Args:
            symbol_service: Symbol service instance.
            liquidity_service: Liquidity service instance.
        """
        self.symbol_service = symbol_service or get_symbol_service()
        self.liquidity_service = liquidity_service or get_liquidity_service()
        self._polygon_client = None

    def _get_polygon_client(self):
        """Get or create Polygon client."""
        if self._polygon_client is None:
            from tomic.integrations.polygon.client import PolygonClient

            self._polygon_client = PolygonClient()
            self._polygon_client.connect()
        return self._polygon_client

    def _map_sic_to_sector(self, sic_code: Optional[str]) -> str:
        """Map SIC code to sector name.

        Args:
            sic_code: SIC code string.

        Returns:
            Sector name or "Unknown".
        """
        if not sic_code:
            return "Unknown"

        # Get first 2 digits of SIC code
        prefix = str(sic_code)[:2]
        return SIC_SECTOR_MAP.get(prefix, "Unknown")

    def _get_sector_for_symbol(self, symbol: str, ticker_details: Dict[str, Any]) -> str:
        """Determine sector for a symbol.

        Args:
            symbol: Stock symbol.
            ticker_details: Details from Polygon API.

        Returns:
            Sector name.
        """
        symbol = symbol.upper()

        # Check if it's a known ETF
        if symbol in ETF_SECTORS:
            return ETF_SECTORS[symbol]

        # Check if it's an ETF type
        if ticker_details.get("type") == "ETF":
            return "ETF - Other"

        # Use SIC code mapping
        sic_code = ticker_details.get("sic_code")
        if sic_code:
            return self._map_sic_to_sector(str(sic_code))

        # Use sic_description if available
        sic_desc = ticker_details.get("sic_description", "")
        if sic_desc:
            sic_lower = sic_desc.lower()
            if "software" in sic_lower or "computer" in sic_lower or "electronic" in sic_lower:
                return "Technology"
            if "bank" in sic_lower or "insurance" in sic_lower or "financial" in sic_lower:
                return "Financials"
            if "pharmaceutical" in sic_lower or "medical" in sic_lower or "health" in sic_lower:
                return "Healthcare"
            if "oil" in sic_lower or "gas" in sic_lower or "petroleum" in sic_lower:
                return "Energy"
            if "retail" in sic_lower or "restaurant" in sic_lower:
                return "Consumer Discretionary"

        return "Unknown"

    # -------------------------------------------------------------------------
    # Add symbols
    # -------------------------------------------------------------------------

    def add_symbols(
        self,
        symbols: List[str],
        fetch_data: bool = True,
        fetch_sector: bool = True,
        fetch_liquidity: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[AddSymbolResult]:
        """Add symbols to the basket with automatic data fetching.

        Args:
            symbols: List of symbols to add.
            fetch_data: Whether to fetch historical data.
            fetch_sector: Whether to fetch sector information.
            fetch_liquidity: Whether to calculate liquidity metrics.
            progress_callback: Optional callback for progress updates.

        Returns:
            List of AddSymbolResult for each symbol.
        """
        results = []

        # Add to config first
        added = self.symbol_service.add_to_config(symbols)
        already_exists = [s.upper() for s in symbols if s.upper() not in added]

        # Report already existing symbols
        for symbol in already_exists:
            results.append(AddSymbolResult(
                symbol=symbol,
                success=True,
                message="Already in basket",
            ))

        # Process newly added symbols
        for symbol in added:
            if progress_callback:
                progress_callback(symbol, "Processing...")

            result = self._add_single_symbol(
                symbol,
                fetch_data=fetch_data,
                fetch_sector=fetch_sector,
                fetch_liquidity=fetch_liquidity,
                progress_callback=progress_callback,
            )
            results.append(result)

        return results

    def _add_single_symbol(
        self,
        symbol: str,
        fetch_data: bool,
        fetch_sector: bool,
        fetch_liquidity: bool,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> AddSymbolResult:
        """Add a single symbol with all data fetching.

        Args:
            symbol: Symbol to add.
            fetch_data: Whether to fetch historical data.
            fetch_sector: Whether to fetch sector information.
            fetch_liquidity: Whether to calculate liquidity metrics.
            progress_callback: Optional callback for progress updates.

        Returns:
            AddSymbolResult with details.
        """
        symbol = symbol.upper()
        metadata = SymbolMetadata(symbol=symbol)
        data_fetched = False

        try:
            # Fetch sector information
            if fetch_sector:
                if progress_callback:
                    progress_callback(symbol, "Fetching sector info...")
                try:
                    client = self._get_polygon_client()
                    details = client.fetch_ticker_details(symbol)

                    metadata.sector = self._get_sector_for_symbol(symbol, details)
                    metadata.industry = details.get("sic_description")
                    metadata.market_cap = details.get("market_cap")
                except Exception as e:
                    logger.warning(f"Failed to fetch sector for {symbol}: {e}")

            # Fetch historical data
            if fetch_data:
                if progress_callback:
                    progress_callback(symbol, "Fetching historical data...")
                try:
                    data_fetched = self._fetch_historical_data(symbol)
                except Exception as e:
                    logger.warning(f"Failed to fetch historical data for {symbol}: {e}")

            # Calculate liquidity
            if fetch_liquidity:
                if progress_callback:
                    progress_callback(symbol, "Calculating liquidity...")
                try:
                    liquidity = self.liquidity_service.calculate_liquidity(symbol)
                    metadata.avg_atm_call_volume = liquidity.avg_atm_call_volume
                    metadata.avg_atm_call_oi = liquidity.avg_atm_call_oi
                except Exception as e:
                    logger.warning(f"Failed to calculate liquidity for {symbol}: {e}")

            # Validate data
            validation = self.symbol_service.validate_symbol_data(symbol)
            metadata.data_status = validation.status
            metadata.last_updated = datetime.now().isoformat()

            # Save metadata
            self.symbol_service.update_symbol_metadata(metadata)

            return AddSymbolResult(
                symbol=symbol,
                success=True,
                message="Added successfully",
                metadata=metadata,
                validation=validation,
                data_fetched=data_fetched,
            )

        except Exception as e:
            logger.error(f"Error adding symbol {symbol}: {e}")
            return AddSymbolResult(
                symbol=symbol,
                success=False,
                message=f"Error: {e}",
            )

    def _fetch_historical_data(self, symbol: str) -> bool:
        """Fetch historical price and IV data for a symbol.

        Args:
            symbol: Symbol to fetch data for.

        Returns:
            True if data was fetched successfully.
        """
        # Import here to avoid circular imports
        from tomic.cli.services import price_history_polygon

        try:
            # Use existing price history fetcher
            price_history_polygon.fetch_symbol(symbol)
            return True
        except Exception as e:
            logger.warning(f"Failed to fetch price history for {symbol}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Remove symbols
    # -------------------------------------------------------------------------

    def remove_symbols(
        self,
        symbols: List[str],
        delete_data: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[RemoveSymbolResult]:
        """Remove symbols from the basket.

        Args:
            symbols: List of symbols to remove.
            delete_data: Whether to delete associated data files.
            progress_callback: Optional callback for progress updates.

        Returns:
            List of RemoveSymbolResult for each symbol.
        """
        results = []

        # Remove from config
        removed = self.symbol_service.remove_from_config(symbols)
        not_found = [s.upper() for s in symbols if s.upper() not in removed]

        # Report not found symbols
        for symbol in not_found:
            results.append(RemoveSymbolResult(
                symbol=symbol,
                success=False,
                message="Not in basket",
            ))

        # Delete data for removed symbols
        for symbol in removed:
            if progress_callback:
                progress_callback(symbol, "Removing...")

            files_deleted = []
            if delete_data:
                files_deleted = self.symbol_service.delete_symbol_data(symbol)

            results.append(RemoveSymbolResult(
                symbol=symbol,
                success=True,
                message=f"Removed ({len(files_deleted)} files deleted)",
                files_deleted=files_deleted,
            ))

        return results

    # -------------------------------------------------------------------------
    # Sync and refresh
    # -------------------------------------------------------------------------

    def sync_metadata(
        self,
        symbols: Optional[List[str]] = None,
        refresh_sector: bool = True,
        refresh_liquidity: bool = True,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        batch_size: int = 5,
        max_liquidity_workers: int = 4,
    ) -> Dict[str, SymbolMetadata]:
        """Sync metadata for symbols with optimized batch processing.

        Optimizations:
        - In-memory metadata: Load once, save periodically (every batch_size symbols)
        - Parallel liquidity: Calculate liquidity metrics using thread pool
        - Checkpoint saves: Progress is saved every batch_size symbols

        Args:
            symbols: Symbols to sync. If None, syncs all configured.
            refresh_sector: Whether to refresh sector information.
            refresh_liquidity: Whether to refresh liquidity metrics.
            progress_callback: Optional callback for progress updates.
            batch_size: Number of symbols to process before checkpoint save.
            max_liquidity_workers: Max parallel workers for liquidity calculation.

        Returns:
            Dictionary mapping symbol to updated metadata.
        """
        if symbols is None:
            symbols = self.symbol_service.get_configured_symbols()

        # Load all metadata once at the start (O(1) instead of O(n))
        all_metadata = self.symbol_service.load_all_metadata()
        results: Dict[str, SymbolMetadata] = {}
        batch_updates: Dict[str, SymbolMetadata] = {}
        sleep_time = cfg_get("POLYGON_SLEEP_BETWEEN", 1.2)

        # Pre-calculate liquidity for all symbols in parallel if requested
        liquidity_cache: Dict[str, LiquidityMetrics] = {}
        if refresh_liquidity:
            if progress_callback:
                progress_callback("", "Pre-calculating liquidity metrics...")

            liquidity_cache = self._calculate_liquidity_parallel(
                symbols,
                max_workers=max_liquidity_workers,
                progress_callback=progress_callback,
            )

        total = len(symbols)
        for i, symbol in enumerate(symbols):
            symbol = symbol.upper()

            if progress_callback:
                progress_callback(symbol, f"Syncing ({i + 1}/{total})...")

            # Get existing metadata from in-memory cache or create new
            metadata = all_metadata.get(symbol)
            if metadata is None:
                metadata = SymbolMetadata(symbol=symbol)

            # Refresh sector (requires API call with rate limiting)
            if refresh_sector:
                try:
                    client = self._get_polygon_client()
                    details = client.fetch_ticker_details(symbol)
                    metadata.sector = self._get_sector_for_symbol(symbol, details)
                    metadata.industry = details.get("sic_description")
                    metadata.market_cap = details.get("market_cap")
                except Exception as e:
                    logger.warning(f"Failed to refresh sector for {symbol}: {e}")

            # Use pre-calculated liquidity from cache
            if refresh_liquidity and symbol in liquidity_cache:
                liquidity = liquidity_cache[symbol]
                metadata.avg_atm_call_volume = liquidity.avg_atm_call_volume
                metadata.avg_atm_call_oi = liquidity.avg_atm_call_oi

            # Update validation status
            validation = self.symbol_service.validate_symbol_data(symbol)
            metadata.data_status = validation.status
            metadata.last_updated = datetime.now().isoformat()

            # Store in results and batch
            results[symbol] = metadata
            batch_updates[symbol] = metadata
            all_metadata[symbol] = metadata

            # Checkpoint save every batch_size symbols
            if len(batch_updates) >= batch_size:
                self.symbol_service.update_symbols_metadata_batch(
                    batch_updates, existing_metadata=all_metadata
                )
                batch_updates.clear()
                if progress_callback:
                    progress_callback("", f"Checkpoint saved ({i + 1}/{total})")

            # Rate limiting for sector API calls
            if refresh_sector and i < total - 1:
                time.sleep(sleep_time)

        # Final save for remaining symbols
        if batch_updates:
            self.symbol_service.update_symbols_metadata_batch(
                batch_updates, existing_metadata=all_metadata
            )

        return results

    def _calculate_liquidity_parallel(
        self,
        symbols: List[str],
        max_workers: int = 4,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, LiquidityMetrics]:
        """Calculate liquidity metrics for multiple symbols in parallel.

        Args:
            symbols: List of symbols to calculate liquidity for.
            max_workers: Maximum number of parallel workers.
            progress_callback: Optional callback for progress updates.

        Returns:
            Dictionary mapping symbol to liquidity metrics.
        """
        results: Dict[str, LiquidityMetrics] = {}

        def calculate_single(symbol: str) -> Tuple[str, Optional[LiquidityMetrics]]:
            """Calculate liquidity for a single symbol."""
            try:
                liquidity = self.liquidity_service.calculate_liquidity(symbol)
                return (symbol, liquidity)
            except Exception as e:
                logger.warning(f"Failed to calculate liquidity for {symbol}: {e}")
                return (symbol, None)

        # Use ThreadPoolExecutor for parallel calculation
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(calculate_single, s.upper()): s.upper()
                for s in symbols
            }

            completed = 0
            total = len(futures)
            for future in as_completed(futures):
                symbol, liquidity = future.result()
                if liquidity is not None:
                    results[symbol] = liquidity
                completed += 1

                if progress_callback and completed % 10 == 0:
                    progress_callback(
                        "", f"Liquidity: {completed}/{total} symbols..."
                    )

        return results

    # -------------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------------

    def get_basket_overview(self) -> Dict[str, Any]:
        """Get comprehensive basket overview.

        Returns:
            Dictionary with basket statistics and per-symbol details.
        """
        symbols = self.symbol_service.get_configured_symbols()
        metadata = self.symbol_service.load_all_metadata()
        validations = self.symbol_service.validate_all_symbols()

        # Build per-symbol details
        symbol_details = []
        for symbol in sorted(symbols):
            meta = metadata.get(symbol, SymbolMetadata(symbol=symbol))
            validation = validations.get(symbol)

            symbol_details.append({
                "symbol": symbol,
                "sector": meta.sector or "Unknown",
                "industry": meta.industry,
                "avg_atm_volume": meta.avg_atm_call_volume,
                "avg_atm_oi": meta.avg_atm_call_oi,
                "data_status": validation.status if validation else "unknown",
                "spot_days": validation.spot_price_days if validation else 0,
                "iv_days": validation.iv_summary_days if validation else 0,
            })

        # Sector breakdown
        sectors: Dict[str, List[str]] = {}
        for detail in symbol_details:
            sector = detail["sector"]
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(detail["symbol"])

        # Liquidity stats
        volumes = [d["avg_atm_volume"] for d in symbol_details if d["avg_atm_volume"]]
        ois = [d["avg_atm_oi"] for d in symbol_details if d["avg_atm_oi"]]

        return {
            "total_symbols": len(symbols),
            "symbols": symbol_details,
            "sectors": {k: {"count": len(v), "symbols": v} for k, v in sectors.items()},
            "sector_count": len(sectors),
            "avg_volume": int(sum(volumes) / len(volumes)) if volumes else None,
            "avg_oi": int(sum(ois) / len(ois)) if ois else None,
            "data_complete": sum(1 for d in symbol_details if d["data_status"] == "complete"),
            "data_incomplete": sum(1 for d in symbol_details if d["data_status"] == "incomplete"),
            "data_missing": sum(1 for d in symbol_details if d["data_status"] == "missing"),
        }

    def get_sector_analysis(self) -> Dict[str, Any]:
        """Get detailed sector analysis.

        Returns:
            Dictionary with sector breakdown and recommendations.
        """
        overview = self.get_basket_overview()
        sectors = overview["sectors"]
        total = overview["total_symbols"]

        # Calculate percentages
        sector_pcts = {}
        for sector, data in sectors.items():
            pct = (data["count"] / total * 100) if total > 0 else 0
            sector_pcts[sector] = {
                "count": data["count"],
                "percentage": round(pct, 1),
                "symbols": data["symbols"],
            }

        # Identify overweight sectors (>40%)
        overweight = [s for s, d in sector_pcts.items() if d["percentage"] > 40]

        # Identify missing major sectors
        major_sectors = {"Technology", "Financials", "Healthcare", "Consumer Discretionary", "Energy"}
        missing_sectors = major_sectors - set(sectors.keys())

        return {
            "sectors": sector_pcts,
            "overweight": overweight,
            "missing_sectors": list(missing_sectors),
            "recommendations": self._generate_sector_recommendations(
                sector_pcts, overweight, missing_sectors
            ),
        }

    def _generate_sector_recommendations(
        self,
        sector_pcts: Dict[str, Any],
        overweight: List[str],
        missing: set,
    ) -> List[str]:
        """Generate sector recommendations.

        Args:
            sector_pcts: Sector percentages.
            overweight: Overweight sectors.
            missing: Missing sectors.

        Returns:
            List of recommendation strings.
        """
        recommendations = []

        for sector in overweight:
            pct = sector_pcts[sector]["percentage"]
            recommendations.append(
                f"Consider reducing {sector} exposure ({pct:.0f}% > 40%)"
            )

        for sector in missing:
            recommendations.append(f"Consider adding {sector} exposure")

        return recommendations

    def get_liquidity_warnings(self, min_volume: int = 10000) -> List[Dict[str, Any]]:
        """Get symbols with low liquidity.

        Args:
            min_volume: Minimum acceptable average volume.

        Returns:
            List of symbols with liquidity warnings.
        """
        overview = self.get_basket_overview()
        warnings = []

        for symbol_data in overview["symbols"]:
            vol = symbol_data["avg_atm_volume"]
            if vol is not None and vol < min_volume:
                warnings.append({
                    "symbol": symbol_data["symbol"],
                    "avg_volume": vol,
                    "avg_oi": symbol_data["avg_atm_oi"],
                    "message": f"Low volume ({vol:,} < {min_volume:,})",
                })

        return sorted(warnings, key=lambda x: x["avg_volume"] or 0)


# Module-level instance for convenience
_manager: Optional[SymbolManager] = None


def get_symbol_manager() -> SymbolManager:
    """Get or create the symbol manager singleton."""
    global _manager
    if _manager is None:
        _manager = SymbolManager()
    return _manager
