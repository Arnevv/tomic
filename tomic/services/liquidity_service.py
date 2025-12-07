"""Liquidity metrics service for calculating ATM volume and open interest.

Uses ORATS cached data to calculate average liquidity metrics for symbols.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.config import get as cfg_get
from tomic.logutils import logger


def _safe_float(value: Optional[str]) -> Optional[float]:
    """Safely convert string to float."""
    if value is None or value == "" or value == "null":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Optional[str]) -> Optional[int]:
    """Safely convert string to int."""
    if value is None or value == "" or value == "null":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _process_date_for_atm(
    cache_dir: Path,
    trade_date: date,
    dte_range: Tuple[int, int] = (20, 60),
) -> Dict[str, Any]:
    """Process a single date's ORATS file and extract ATM metrics for ALL symbols.

    This is the core optimization: instead of processing per-symbol (5812 times),
    we process per-date once and extract all symbols in a single pass.

    Args:
        cache_dir: Path to ORATS cache directory.
        trade_date: Date to process.
        dte_range: DTE range for ATM options (min, max).

    Returns:
        Dict with 'symbols' mapping symbol to metrics, and optionally 'error' if failed.
    """
    year = trade_date.strftime("%Y")
    date_str = trade_date.strftime("%Y%m%d")
    zip_path = cache_dir / year / f"ORATS_SMV_Strikes_{date_str}.zip"

    if not zip_path.exists():
        return {"symbols": {}, "error": f"File not found: {zip_path}"}

    min_dte, max_dte = dte_range
    results: Dict[str, Dict[str, Optional[int]]] = {}

    # Temporary storage for ATM options per symbol
    # {symbol: {"spot": float, "options": [{"type": "C/P", "strike": float, "volume": int, "oi": int}]}}
    symbol_options: Dict[str, Dict] = defaultdict(
        lambda: {"spot": None, "options": []}
    )

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_files:
                return {"symbols": {}, "error": f"No CSV in ZIP: {zip_path}"}

            csv_name = csv_files[0]
            with zf.open(csv_name) as csv_file:
                text_stream = io.TextIOWrapper(csv_file, encoding="utf-8")

                # Detect delimiter
                sample = text_stream.read(10000)
                text_stream.seek(0)
                delimiter = ","
                for delim in [",", "\t", ";", "|"]:
                    if sample.split("\n")[0].count(delim) > 20:
                        delimiter = delim
                        break

                reader = csv.DictReader(text_stream, delimiter=delimiter)

                # Single pass through CSV - extract all symbols
                row_count = 0
                for row in reader:
                    row_count += 1
                    ticker = row.get("ticker", "").strip().upper()
                    if not ticker:
                        continue

                    # Get expiration and calculate DTE
                    expiry_str = row.get("expirDate", "")
                    try:
                        expiry = date(
                            int(expiry_str[:4]),
                            int(expiry_str[5:7]),
                            int(expiry_str[8:10]),
                        )
                        dte = (expiry - trade_date).days
                    except (ValueError, IndexError):
                        continue

                    # Filter by DTE range
                    if dte < min_dte or dte > max_dte:
                        continue

                    # Get spot price
                    spot = _safe_float(row.get("stkPx"))
                    if spot is None or spot <= 0:
                        continue

                    strike = _safe_float(row.get("strike"))
                    if strike is None:
                        continue

                    # Check if ATM (within 2% of spot)
                    if abs(strike - spot) > spot * 0.02:
                        continue

                    # Store spot price
                    if symbol_options[ticker]["spot"] is None:
                        symbol_options[ticker]["spot"] = spot

                    # Extract call metrics
                    call_vol = _safe_int(row.get("cVolu"))
                    call_oi = _safe_int(row.get("cOi"))
                    if call_vol is not None or call_oi is not None:
                        symbol_options[ticker]["options"].append({
                            "type": "C",
                            "volume": call_vol,
                            "oi": call_oi,
                        })

                    # Extract put metrics
                    put_vol = _safe_int(row.get("pVolu"))
                    put_oi = _safe_int(row.get("pOi"))
                    if put_vol is not None or put_oi is not None:
                        symbol_options[ticker]["options"].append({
                            "type": "P",
                            "volume": put_vol,
                            "oi": put_oi,
                        })

        # Aggregate ATM metrics per symbol
        for symbol, data in symbol_options.items():
            if not data["options"]:
                continue

            call_vols = [o["volume"] for o in data["options"] if o["type"] == "C" and o["volume"] is not None]
            call_ois = [o["oi"] for o in data["options"] if o["type"] == "C" and o["oi"] is not None]
            put_vols = [o["volume"] for o in data["options"] if o["type"] == "P" and o["volume"] is not None]
            put_ois = [o["oi"] for o in data["options"] if o["type"] == "P" and o["oi"] is not None]

            results[symbol] = {
                "call_volume": sum(call_vols) if call_vols else None,
                "call_oi": sum(call_ois) if call_ois else None,
                "put_volume": sum(put_vols) if put_vols else None,
                "put_oi": sum(put_ois) if put_ois else None,
            }

    except Exception as e:
        return {"symbols": {}, "error": f"Exception processing {zip_path}: {e}"}

    return {"symbols": results}


@dataclass
class LiquidityMetrics:
    """Liquidity metrics for a symbol."""

    symbol: str
    avg_atm_call_volume: Optional[int] = None
    avg_atm_call_oi: Optional[int] = None
    avg_atm_put_volume: Optional[int] = None
    avg_atm_put_oi: Optional[int] = None
    days_analyzed: int = 0
    data_start: Optional[date] = None
    data_end: Optional[date] = None

    @property
    def total_avg_volume(self) -> Optional[int]:
        """Total average ATM volume (calls + puts)."""
        if self.avg_atm_call_volume is None and self.avg_atm_put_volume is None:
            return None
        call_vol = self.avg_atm_call_volume or 0
        put_vol = self.avg_atm_put_volume or 0
        return call_vol + put_vol

    @property
    def total_avg_oi(self) -> Optional[int]:
        """Total average ATM open interest (calls + puts)."""
        if self.avg_atm_call_oi is None and self.avg_atm_put_oi is None:
            return None
        call_oi = self.avg_atm_call_oi or 0
        put_oi = self.avg_atm_put_oi or 0
        return call_oi + put_oi

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "avg_atm_call_volume": self.avg_atm_call_volume,
            "avg_atm_call_oi": self.avg_atm_call_oi,
            "avg_atm_put_volume": self.avg_atm_put_volume,
            "avg_atm_put_oi": self.avg_atm_put_oi,
            "days_analyzed": self.days_analyzed,
            "data_start": str(self.data_start) if self.data_start else None,
            "data_end": str(self.data_end) if self.data_end else None,
        }


class LiquidityService:
    """Service for calculating liquidity metrics from ORATS data."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the liquidity service.

        Args:
            cache_dir: Directory containing ORATS ZIP files.
                      Defaults to ORATS_CACHE_DIR from config.
        """
        if cache_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            cache_dir = base_dir / cfg_get("ORATS_CACHE_DIR", "tomic/data/orats_cache")
        self.cache_dir = cache_dir.expanduser()

    def get_most_recent_orats_file(self) -> Optional[Path]:
        """Find the most recent ORATS ZIP file in the cache.

        Returns:
            Path to most recent ZIP file, or None if no files found.
        """
        if not self.cache_dir.exists():
            return None

        most_recent: Optional[Path] = None
        most_recent_date: Optional[date] = None

        for year_dir in self.cache_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            for zip_file in year_dir.glob("ORATS_SMV_Strikes_*.zip"):
                try:
                    date_str = zip_file.stem.split("_")[-1]
                    file_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    if most_recent_date is None or file_date > most_recent_date:
                        most_recent_date = file_date
                        most_recent = zip_file
                except (ValueError, IndexError):
                    continue

        return most_recent

    def get_symbols_from_orats_file(self, zip_path: Path) -> List[str]:
        """Extract all unique symbols from an ORATS ZIP file.

        Args:
            zip_path: Path to the ORATS ZIP file.

        Returns:
            Sorted list of unique symbols found in the file.
        """
        import csv
        import io
        import zipfile

        symbols = set()

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_files:
                    return []

                csv_name = csv_files[0]
                with zf.open(csv_name) as csv_file:
                    text_stream = io.TextIOWrapper(csv_file, encoding="utf-8")

                    # Detect delimiter
                    sample = text_stream.read(10000)
                    text_stream.seek(0)
                    delimiter = ","
                    for delim in [',', '\t', ';', '|']:
                        if sample.split('\n')[0].count(delim) > 20:
                            delimiter = delim
                            break

                    reader = csv.DictReader(text_stream, delimiter=delimiter)
                    for row in reader:
                        ticker = row.get("ticker", "").strip().upper()
                        if ticker:
                            symbols.add(ticker)

        except Exception as e:
            logger.error(f"Error reading ORATS file {zip_path}: {e}")
            return []

        return sorted(symbols)

    def get_all_symbols_overview(
        self,
        lookback_days: int = 252,
        progress_callback: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """Get liquidity overview for all symbols in most recent ORATS file.

        Calculates average ATM volume and OI over the specified lookback period
        for all symbols found in the most recent ORATS data file.

        Args:
            lookback_days: Number of trading days to analyze (default 252 = 1 year).
            progress_callback: Optional callback for progress updates (symbol, idx, total).

        Returns:
            List of dicts with symbol, avg_atm_volume, avg_atm_oi, sorted by avg_atm_volume desc.
        """
        most_recent = self.get_most_recent_orats_file()
        if most_recent is None:
            logger.warning("No ORATS files found in cache")
            return []

        logger.info(f"Using most recent ORATS file: {most_recent.name}")
        symbols = self.get_symbols_from_orats_file(most_recent)

        if not symbols:
            logger.warning("No symbols found in ORATS file")
            return []

        logger.info(f"Found {len(symbols)} symbols in ORATS file")

        results = []
        total = len(symbols)

        for idx, symbol in enumerate(symbols, 1):
            if progress_callback:
                progress_callback(symbol, idx, total)

            try:
                metrics = self.calculate_liquidity(
                    symbol,
                    lookback_days=lookback_days,
                    target_dte_range=(20, 60),
                )

                results.append({
                    "symbol": symbol,
                    "avg_atm_volume": metrics.total_avg_volume,
                    "avg_atm_oi": metrics.total_avg_oi,
                    "days_analyzed": metrics.days_analyzed,
                })
            except Exception as e:
                logger.debug(f"Error calculating liquidity for {symbol}: {e}")
                results.append({
                    "symbol": symbol,
                    "avg_atm_volume": None,
                    "avg_atm_oi": None,
                    "days_analyzed": 0,
                })

        # Sort by avg_atm_volume descending (None values at the end)
        results.sort(
            key=lambda x: (x["avg_atm_volume"] is None, -(x["avg_atm_volume"] or 0))
        )

        return results

    def get_all_symbols_overview_optimized(
        self,
        lookback_days: int = 30,
        progress_callback: Optional[callable] = None,
        max_workers: int = 8,
        use_threads: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get liquidity overview for all symbols - OPTIMIZED VERSION.

        Instead of processing each symbol individually (O(symbols × dates × rows)),
        this processes each date once and extracts all symbols (O(dates × rows)).
        This is ~5800x faster for 5812 symbols.

        Args:
            lookback_days: Number of trading days to analyze (default 30 = ~6 weeks).
            progress_callback: Optional callback for progress updates (date_str, idx, total).
            max_workers: Number of parallel workers for date processing.
            use_threads: Use ThreadPoolExecutor instead of ProcessPoolExecutor.
                        Useful for testing or when multiprocessing has issues.

        Returns:
            List of dicts with symbol, avg_atm_volume, avg_atm_oi, sorted by avg_atm_volume desc.
        """
        available_dates = self._get_available_dates(lookback_days)

        if not available_dates:
            logger.warning("No ORATS data available for liquidity calculation")
            return []

        logger.info(f"Processing {len(available_dates)} dates with {max_workers} workers")

        # Collect ATM metrics per symbol across all dates
        # Structure: {symbol: {"call_volumes": [], "call_ois": [], "put_volumes": [], "put_ois": []}}
        symbol_data: Dict[str, Dict[str, List[int]]] = defaultdict(
            lambda: {"call_volumes": [], "call_ois": [], "put_volumes": [], "put_ois": []}
        )

        total_dates = len(available_dates)
        errors_logged = 0

        # Process dates in parallel - use threads or processes
        Executor = ThreadPoolExecutor if use_threads else ProcessPoolExecutor
        with Executor(max_workers=max_workers) as executor:
            # Submit all date processing tasks
            future_to_date = {
                executor.submit(_process_date_for_atm, self.cache_dir, d): d
                for d in available_dates
            }

            for idx, future in enumerate(as_completed(future_to_date), 1):
                trade_date = future_to_date[future]

                if progress_callback:
                    progress_callback(str(trade_date), idx, total_dates)

                try:
                    result = future.result()

                    # Check for errors from subprocess
                    if "error" in result and errors_logged < 3:
                        error_msg = f"Date {trade_date}: {result['error']}"
                        logger.warning(error_msg)
                        print(f"  WARNING: {error_msg}")
                        errors_logged += 1

                    # Merge symbol results into symbol_data
                    symbols_metrics = result.get("symbols", {})
                    for symbol, metrics in symbols_metrics.items():
                        if metrics["call_volume"] is not None:
                            symbol_data[symbol]["call_volumes"].append(metrics["call_volume"])
                        if metrics["call_oi"] is not None:
                            symbol_data[symbol]["call_ois"].append(metrics["call_oi"])
                        if metrics["put_volume"] is not None:
                            symbol_data[symbol]["put_volumes"].append(metrics["put_volume"])
                        if metrics["put_oi"] is not None:
                            symbol_data[symbol]["put_ois"].append(metrics["put_oi"])

                except Exception as e:
                    if errors_logged < 3:
                        error_msg = f"Error processing date {trade_date}: {e}"
                        logger.warning(error_msg)
                        print(f"  WARNING: {error_msg}")
                        errors_logged += 1

        # Fallback: if ProcessPoolExecutor returned no data, try with threads
        if not symbol_data and not use_threads:
            fallback_msg = (
                "ProcessPoolExecutor returned no data. "
                "Retrying with ThreadPoolExecutor (this may be slower)..."
            )
            logger.warning(fallback_msg)
            print(f"\n  {fallback_msg}\n")
            return self.get_all_symbols_overview_optimized(
                lookback_days=lookback_days,
                progress_callback=progress_callback,
                max_workers=max_workers,
                use_threads=True,
            )

        # Calculate averages for each symbol
        results = []
        for symbol, data in symbol_data.items():
            avg_call_vol = int(sum(data["call_volumes"]) / len(data["call_volumes"])) if data["call_volumes"] else None
            avg_call_oi = int(sum(data["call_ois"]) / len(data["call_ois"])) if data["call_ois"] else None
            avg_put_vol = int(sum(data["put_volumes"]) / len(data["put_volumes"])) if data["put_volumes"] else None
            avg_put_oi = int(sum(data["put_ois"]) / len(data["put_ois"])) if data["put_ois"] else None

            total_vol = None
            if avg_call_vol is not None or avg_put_vol is not None:
                total_vol = (avg_call_vol or 0) + (avg_put_vol or 0)

            total_oi = None
            if avg_call_oi is not None or avg_put_oi is not None:
                total_oi = (avg_call_oi or 0) + (avg_put_oi or 0)

            days_with_data = max(
                len(data["call_volumes"]),
                len(data["put_volumes"]),
                len(data["call_ois"]),
                len(data["put_ois"]),
            )

            results.append({
                "symbol": symbol,
                "avg_atm_volume": total_vol,
                "avg_atm_oi": total_oi,
                "days_analyzed": days_with_data,
            })

        # Sort by avg_atm_volume descending (None values at the end)
        results.sort(
            key=lambda x: (x["avg_atm_volume"] is None, -(x["avg_atm_volume"] or 0))
        )

        return results

    def _get_available_dates(self, lookback_days: int = 30) -> List[date]:
        """Get available trading dates from ORATS cache.

        Args:
            lookback_days: Number of days to look back.

        Returns:
            List of available dates, sorted descending (newest first).
        """
        available = []
        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days + 10)  # Buffer for weekends

        # Scan cache directories for available files
        for year_dir in self.cache_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            for zip_file in year_dir.glob("ORATS_SMV_Strikes_*.zip"):
                try:
                    date_str = zip_file.stem.split("_")[-1]
                    file_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    if start_date <= file_date <= end_date:
                        available.append(file_date)
                except (ValueError, IndexError):
                    continue

        return sorted(available, reverse=True)[:lookback_days]

    def calculate_liquidity(
        self,
        symbol: str,
        lookback_days: int = 30,
        target_dte_range: Tuple[int, int] = (20, 60),
    ) -> LiquidityMetrics:
        """Calculate average liquidity metrics for a symbol.

        Uses ORATS data to find ATM options and calculate average volume/OI.

        Args:
            symbol: Stock symbol.
            lookback_days: Number of trading days to analyze.
            target_dte_range: DTE range for ATM options (min, max).

        Returns:
            LiquidityMetrics with calculated averages.
        """
        # Import here to avoid circular imports
        from tomic.backtest.option_chain_loader import OptionChainLoader

        symbol = symbol.upper()
        metrics = LiquidityMetrics(symbol=symbol)

        loader = OptionChainLoader(self.cache_dir)
        available_dates = self._get_available_dates(lookback_days)

        if not available_dates:
            logger.warning(f"No ORATS data available for liquidity calculation")
            return metrics

        call_volumes: List[int] = []
        call_ois: List[int] = []
        put_volumes: List[int] = []
        put_ois: List[int] = []
        analyzed_dates: List[date] = []

        for trade_date in available_dates:
            try:
                chain = loader.load_chain(symbol, trade_date)
                if chain is None or not chain.options:
                    continue

                # Find ATM options in target DTE range
                atm_calls, atm_puts = self._find_atm_options(
                    chain, target_dte_range
                )

                if atm_calls:
                    for opt in atm_calls:
                        if opt.volume is not None:
                            call_volumes.append(opt.volume)
                        if opt.open_interest is not None:
                            call_ois.append(opt.open_interest)

                if atm_puts:
                    for opt in atm_puts:
                        if opt.volume is not None:
                            put_volumes.append(opt.volume)
                        if opt.open_interest is not None:
                            put_ois.append(opt.open_interest)

                analyzed_dates.append(trade_date)

            except Exception as e:
                logger.debug(f"Error loading chain for {symbol} on {trade_date}: {e}")
                continue

        # Calculate averages
        if call_volumes:
            metrics.avg_atm_call_volume = int(sum(call_volumes) / len(call_volumes))
        if call_ois:
            metrics.avg_atm_call_oi = int(sum(call_ois) / len(call_ois))
        if put_volumes:
            metrics.avg_atm_put_volume = int(sum(put_volumes) / len(put_volumes))
        if put_ois:
            metrics.avg_atm_put_oi = int(sum(put_ois) / len(put_ois))

        metrics.days_analyzed = len(analyzed_dates)
        if analyzed_dates:
            metrics.data_start = min(analyzed_dates)
            metrics.data_end = max(analyzed_dates)

        return metrics

    def _find_atm_options(
        self,
        chain,
        dte_range: Tuple[int, int],
    ) -> Tuple[List, List]:
        """Find ATM call and put options within DTE range.

        Args:
            chain: OptionChain object.
            dte_range: (min_dte, max_dte) range.

        Returns:
            Tuple of (atm_calls, atm_puts).
        """
        min_dte, max_dte = dte_range
        spot = chain.spot_price

        if spot is None or spot <= 0:
            return [], []

        # Filter options by DTE
        options_in_range = chain.filter_by_dte_range(min_dte, max_dte)

        if not options_in_range:
            return [], []

        # Find options closest to ATM (within 2% of spot)
        atm_tolerance = spot * 0.02

        atm_calls = [
            opt for opt in options_in_range
            if opt.option_type == "C" and abs(opt.strike - spot) <= atm_tolerance
        ]

        atm_puts = [
            opt for opt in options_in_range
            if opt.option_type == "P" and abs(opt.strike - spot) <= atm_tolerance
        ]

        return atm_calls, atm_puts

    def calculate_liquidity_batch(
        self,
        symbols: List[str],
        lookback_days: int = 30,
    ) -> Dict[str, LiquidityMetrics]:
        """Calculate liquidity metrics for multiple symbols.

        Args:
            symbols: List of stock symbols.
            lookback_days: Number of trading days to analyze.

        Returns:
            Dictionary mapping symbol to LiquidityMetrics.
        """
        results = {}
        for symbol in symbols:
            logger.info(f"Calculating liquidity for {symbol}...")
            results[symbol.upper()] = self.calculate_liquidity(
                symbol, lookback_days
            )
        return results


# Module-level instance for convenience
_service: Optional[LiquidityService] = None


def get_liquidity_service() -> LiquidityService:
    """Get or create the liquidity service singleton."""
    global _service
    if _service is None:
        _service = LiquidityService()
    return _service
