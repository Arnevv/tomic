"""Interactive flow for ORATS IV backfill from FTP."""

from __future__ import annotations

import csv
import ftplib
import io
import os
import shutil
import socket
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import yaml

from tomic import config as cfg
from tomic.cli.common import prompt, prompt_yes_no
from tomic.cli.services.vol_helpers import (
    _get_closes,
    iv_percentile,
    iv_rank,
    rolling_hv,
    get_historical_iv_series,
)
from tomic.helpers.json_utils import dump_json
from tomic.journal.utils import load_json
from tomic.logutils import logger
from tomic.utils import _is_third_friday

try:
    from tabulate import tabulate
except Exception:

    def tabulate(
        rows: Sequence[Sequence[Any]],
        headers: Sequence[str] | None = None,
        tablefmt: str | None = None,
    ) -> str:
        def _stringify(value: Any) -> str:
            return "" if value is None else str(value)

        table_rows = list(rows)
        if headers:
            table_rows = [headers] + table_rows

        if not table_rows:
            return ""

        widths = [
            max(len(_stringify(row[idx])) for row in table_rows)
            for idx in range(len(table_rows[0]))
        ]

        def fmt(row: Sequence[Any]) -> str:
            return "| " + " | ".join(
                _stringify(col).ljust(widths[idx]) for idx, col in enumerate(row)
            ) + " |"

        lines = []
        if headers:
            lines.append(fmt(headers))
            lines.append(
                "|-" + "-|-".join("-" * widths[idx] for idx in range(len(widths))) + "-|"
            )
        for row in rows:
            lines.append(fmt(row))
        return "\n".join(lines)


@dataclass
class OratsRecord:
    """Single row from ORATS CSV with calculated metrics.

    Metrics aligned with Polygon methodology:
    - Expiration filtering: Only Third Friday expirations (matching Polygon)
    - Deduplication: Remove duplicate (strike, type) combinations
    - ATM IV: Single ATM call from front month (13-48 DTE preferred, fallback to >= 7 DTE)
    - Term structure: M1-M2 and M1-M3 using single ATM calls per month
    - Skew: Delta ±0.25 from front month only
    - IV Rank/Percentile: Based on 30-day rolling HV
    """

    ticker: str
    date: str
    atm_iv: float | None
    term_m1_m2: float | None
    term_m1_m3: float | None
    skew: float | None
    iv_rank: float | None
    iv_percentile: float | None


@dataclass
class ValidationEntry:
    """Tracking old vs new values for validation report."""

    symbol: str
    date: str
    old_atm_iv: float | None
    new_atm_iv: float | None
    delta_atm_iv: float | None


class OratsBackfillFlow:
    """Main class for ORATS backfill operations."""

    # FTP timeout in seconds - prevents indefinite hangs on network issues
    FTP_TIMEOUT = 60
    # Number of downloads between keepalive checks
    KEEPALIVE_INTERVAL = 10
    # Delay between downloads to avoid overwhelming the server (seconds)
    DOWNLOAD_DELAY = 0.5

    def __init__(self):
        # Strip any trailing slashes and paths from hostname (FTP expects hostname only)
        raw_host = os.getenv("ORATS_FTP_HOST", "de1.hostedftp.com")
        self.ftp_host = raw_host.split("/")[0] if "/" in raw_host else raw_host
        self.ftp_user = os.getenv("ORATS_FTP_USER", "")
        self.ftp_password = os.getenv("ORATS_FTP_PASSWORD", "")
        self.ftp_path = os.getenv("ORATS_FTP_PATH", "smvstrikes")
        self.validation_entries: list[ValidationEntry] = []
        self._download_count = 0
        # Cache directory for persistent ZIP storage
        self.cache_dir = Path(cfg.get("ORATS_CACHE_DIR", "tomic/data/orats_cache")).expanduser()

    def _connect_ftp(self) -> ftplib.FTP:
        """Connect to ORATS FTP server with timeout.

        Uses a 60-second timeout to prevent indefinite hangs on network issues.
        """
        if not self.ftp_user or not self.ftp_password:
            raise ValueError(
                "ORATS FTP credentials niet gevonden. "
                "Zet ORATS_FTP_USER en ORATS_FTP_PASSWORD in .env file."
            )

        try:
            ftp = ftplib.FTP(self.ftp_host, timeout=self.FTP_TIMEOUT)
            ftp.login(self.ftp_user, self.ftp_password)
            logger.info(f"FTP verbinding gemaakt met {self.ftp_host} (timeout={self.FTP_TIMEOUT}s)")
            return ftp
        except Exception as exc:
            logger.error(f"FTP verbinding mislukt: {exc}")
            raise

    def _ensure_ftp_connected(self, ftp: ftplib.FTP | None) -> ftplib.FTP:
        """Ensure FTP connection is alive, reconnect if necessary.

        Checks connection health using NOOP command and reconnects if stale.
        """
        if ftp is None:
            logger.info("Geen FTP verbinding, maak nieuwe verbinding...")
            return self._connect_ftp()

        try:
            # NOOP command to check if connection is alive
            ftp.voidcmd("NOOP")
            return ftp
        except Exception as exc:
            logger.warning(f"FTP verbinding verloren ({exc}), opnieuw verbinden...")
            try:
                ftp.quit()
            except Exception:
                pass
            return self._connect_ftp()

    def _download_file(
        self, ftp: ftplib.FTP, remote_path: str, local_path: Path
    ) -> tuple[bool, ftplib.FTP]:
        """Download file from FTP with retry logic and reconnection support.

        Returns tuple of (success, ftp_connection) - ftp may be new connection if
        reconnection was needed.
        """
        max_retries = 3
        current_ftp = ftp

        for attempt in range(max_retries):
            try:
                # Check/refresh connection every KEEPALIVE_INTERVAL downloads
                self._download_count += 1
                if self._download_count % self.KEEPALIVE_INTERVAL == 0:
                    current_ftp = self._ensure_ftp_connected(current_ftp)

                with local_path.open("wb") as f:
                    current_ftp.retrbinary(f"RETR {remote_path}", f.write)
                logger.info(f"Downloaded: {remote_path}")

                # Add small delay to avoid overwhelming the server
                time.sleep(self.DOWNLOAD_DELAY)
                return True, current_ftp

            except (socket.timeout, TimeoutError) as exc:
                logger.warning(
                    f"Download timeout voor {remote_path}: {exc}. "
                    f"Reconnecting..."
                )
                current_ftp = self._connect_ftp()
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"Download definitief mislukt na {max_retries} pogingen: {remote_path}")
                    return False, current_ftp

            except Exception as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Download poging {attempt + 1} mislukt voor {remote_path}: {exc}. "
                        f"Retry in {wait}s..."
                    )
                    time.sleep(wait)
                    # Try to reconnect on any error
                    try:
                        current_ftp = self._ensure_ftp_connected(current_ftp)
                    except Exception:
                        current_ftp = self._connect_ftp()
                else:
                    logger.error(f"Download definitief mislukt na {max_retries} pogingen: {remote_path}")
                    return False, current_ftp

        return False, current_ftp

    def _get_cache_path(self, date: datetime) -> Path:
        """Get the cache path for a given date's ZIP file.

        Cache is organized by year: orats_cache/2024/ORATS_SMV_Strikes_20240115.zip
        """
        year = date.strftime("%Y")
        date_str = date.strftime("%Y%m%d")
        cache_year_dir = self.cache_dir / year
        return cache_year_dir / f"ORATS_SMV_Strikes_{date_str}.zip"

    def _get_cached_or_download(
        self, ftp: ftplib.FTP | None, date: datetime
    ) -> tuple[Path | None, ftplib.FTP | None]:
        """Get ZIP file from cache or download if not cached.

        Returns tuple of (zip_path, ftp_connection).
        zip_path is None if download failed.
        ftp is the (possibly reconnected) FTP connection.
        """
        cache_path = self._get_cache_path(date)
        date_str = date.strftime("%Y%m%d")
        year = date.strftime("%Y")

        # Check if already in cache
        if cache_path.exists():
            logger.info(f"Cache hit: {cache_path.name}")
            return cache_path, ftp

        # Need to download - ensure cache directory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to FTP if not connected
        if ftp is None:
            try:
                ftp = self._connect_ftp()
            except Exception as exc:
                logger.error(f"FTP verbinding mislukt: {exc}")
                return None, None

        # Download to cache
        remote_path = f"{self.ftp_path}/{year}/ORATS_SMV_Strikes_{date_str}.zip"
        success, ftp = self._download_file(ftp, remote_path, cache_path)

        if success:
            return cache_path, ftp
        else:
            # Remove partial download if exists
            if cache_path.exists():
                self._safe_delete_file(cache_path)
            return None, ftp

    def _get_existing_dates_for_symbol(self, symbol: str) -> set[str]:
        """Get set of dates that already have data for a symbol.

        Returns dates in YYYY-MM-DD format.
        """
        summary_dir = Path(cfg.get("IV_SUMMARY_DIR", "tomic/data/iv_daily_summary")).expanduser()
        summary_file = summary_dir / f"{symbol}.json"

        existing = load_json(summary_file)
        if not isinstance(existing, list):
            return set()

        dates = set()
        for record in existing:
            if isinstance(record, dict) and "date" in record:
                # Check if record has ORATS-specific fields (not just Polygon data)
                if record.get("atm_iv") is not None:
                    dates.add(str(record["date"]))
        return dates

    def _get_missing_dates_for_symbols(
        self, symbols: list[str], trading_days: list[datetime]
    ) -> dict[str, set[str]]:
        """Determine which dates are missing data for each symbol.

        Returns dict mapping symbol -> set of missing date strings (YYYY-MM-DD).
        """
        missing: dict[str, set[str]] = {}
        all_dates = {d.strftime("%Y-%m-%d") for d in trading_days}

        for symbol in symbols:
            existing = self._get_existing_dates_for_symbol(symbol)
            symbol_missing = all_dates - existing
            if symbol_missing:
                missing[symbol] = symbol_missing

        return missing

    def _get_dates_to_process(
        self, symbols: list[str], trading_days: list[datetime]
    ) -> tuple[list[datetime], dict[str, set[str]]]:
        """Determine which dates need processing based on symbol gaps.

        Returns:
        - List of dates that need to be processed (have at least one symbol missing)
        - Dict mapping symbol -> set of missing dates
        """
        missing_by_symbol = self._get_missing_dates_for_symbols(symbols, trading_days)

        # Collect all dates that have at least one symbol missing data
        dates_needed: set[str] = set()
        for symbol_dates in missing_by_symbol.values():
            dates_needed.update(symbol_dates)

        # Convert back to datetime and sort
        dates_to_process = [
            d for d in trading_days
            if d.strftime("%Y-%m-%d") in dates_needed
        ]

        return dates_to_process, missing_by_symbol

    def _parse_orats_csv(
        self, zip_path: Path, requested_symbols: set[str]
    ) -> dict[str, list[OratsRecord]]:
        """Parse ORATS ZIP file and extract metrics per symbol.

        Returns dict mapping symbol -> list of OratsRecord objects.
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                csv_files = [name for name in zf.namelist() if name.endswith(".csv")]
                if not csv_files:
                    logger.warning(f"Geen CSV gevonden in {zip_path.name}")
                    return {}

                csv_name = csv_files[0]
                with zf.open(csv_name) as csv_file:
                    # Detect delimiter by reading a sample
                    text_stream = io.TextIOWrapper(csv_file, encoding="utf-8")
                    sample = text_stream.read(10000)
                    text_stream.seek(0)

                    # Try to detect delimiter (ORATS may use comma or tab)
                    detected_delimiter = ","  # Default to comma
                    for test_delimiter in [',', '\t', ';', '|']:
                        lines = sample.split('\n')[:5]
                        if lines:
                            header_line = lines[0]
                            num_delimiters = header_line.count(test_delimiter)
                            # ORATS should have 30+ columns
                            if num_delimiters > 20:
                                detected_delimiter = test_delimiter
                                logger.info(f"Detected CSV delimiter: {repr(test_delimiter)} ({num_delimiters + 1} columns)")
                                break

                    reader = csv.DictReader(text_stream, delimiter=detected_delimiter)

                    # Group rows by ticker
                    symbol_rows: dict[str, list[dict[str, str]]] = {}
                    for row in reader:
                        ticker = row.get("ticker", "").strip().upper()
                        if ticker and ticker in requested_symbols:
                            if ticker not in symbol_rows:
                                symbol_rows[ticker] = []
                            symbol_rows[ticker].append(row)

                    # Calculate metrics for each symbol
                    results: dict[str, list[OratsRecord]] = {}
                    for ticker, rows in symbol_rows.items():
                        record = self._calculate_metrics(ticker, rows)
                        if record:
                            results[ticker] = [record]

                    return results

        except zipfile.BadZipFile:
            logger.error(f"Corrupt ZIP bestand: {zip_path.name}")
            return {}
        except Exception as exc:
            logger.error(f"CSV parse fout in {zip_path.name}: {exc}")
            return {}

    def _calculate_metrics(
        self, ticker: str, rows: list[dict[str, str]]
    ) -> OratsRecord | None:
        """Calculate ATM IV, term structure, and skew from ORATS rows.

        ALIGNED WITH POLYGON METHODOLOGY (polygon_iv.py):
        - Expiration selection: Only Third Friday expirations (13-48 DTE for front month,
          fallback to nearest expiration with DTE >= 7 if none in standard range)
        - Deduplication: Remove duplicate (strike, type) combinations
        - ATM IV: Single ATM call from front month
        - Term structure: M1-M2 and M1-M3 using single ATM calls per month
        - Skew: Delta ±0.25 from front month only (not all expirations)
        - IV Rank/Percentile: Based on 30-day rolling HV
        """
        if not rows:
            return None

        # Get trade date from first row
        trade_date = rows[0].get("trade_date", "")
        if not trade_date:
            logger.warning(f"Geen trade_date gevonden voor {ticker}")
            return None

        # Parse date to YYYY-MM-DD - try multiple formats
        parsed_date = None
        trade_dt = None
        for date_format in ["%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
            try:
                trade_dt = datetime.strptime(trade_date, date_format)
                parsed_date = trade_dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        if not parsed_date or not trade_dt:
            logger.warning(f"Ongeldige datum voor {ticker}: {trade_date}")
            return None

        # Get spot price from first row
        try:
            spot_price = float(rows[0].get("stkPx", 0))
        except (ValueError, TypeError):
            logger.warning(f"Geen geldige spot prijs voor {ticker}")
            return None

        if spot_price <= 0:
            logger.warning(f"Ongeldige spot prijs voor {ticker}: {spot_price}")
            return None

        # ================================================================
        # STEP 1: Group rows by expiration and calculate DTE
        # ================================================================
        exp_groups: dict[str, list[dict[str, str]]] = {}
        exp_dte: dict[str, float] = {}

        for row in rows:
            exp_date = row.get("expirDate", "").strip()
            if not exp_date:
                continue

            # Parse expiration date
            exp_dt = None
            for date_format in ["%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    exp_dt = datetime.strptime(exp_date, date_format)
                    break
                except ValueError:
                    continue

            if not exp_dt:
                continue

            # Calculate DTE
            dte = (exp_dt - trade_dt).days
            if dte < 0:  # Skip expired options
                continue

            if exp_date not in exp_groups:
                exp_groups[exp_date] = []
                exp_dte[exp_date] = dte

            exp_groups[exp_date].append(row)

        if not exp_groups:
            logger.warning(f"Geen geldige expirations voor {ticker}")
            return None

        # ================================================================
        # STEP 1.5: Filter to only Third Friday expirations (matching Polygon)
        # ================================================================
        third_friday_groups = {}
        third_friday_dte = {}

        for exp_date, rows in exp_groups.items():
            # Parse expiration date to check if it's a third Friday
            for date_format in ["%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    exp_dt = datetime.strptime(exp_date, date_format).date()
                    if _is_third_friday(exp_dt):
                        third_friday_groups[exp_date] = rows
                        third_friday_dte[exp_date] = exp_dte[exp_date]
                    break
                except ValueError:
                    continue

        if not third_friday_groups:
            logger.warning(
                f"Geen Third Friday expirations voor {ticker} - alleen weeklies beschikbaar"
            )
            return None

        logger.info(
            f"Filtered {len(exp_groups)} expirations to {len(third_friday_groups)} Third Fridays"
        )

        # Use only third Friday expirations from here on
        exp_groups = third_friday_groups
        exp_dte = third_friday_dte

        # ================================================================
        # STEP 1.75: Deduplicate rows for each expiration (matching Polygon)
        # ================================================================
        for exp_date in exp_groups:
            original_count = len(exp_groups[exp_date])
            exp_groups[exp_date] = self._deduplicate_rows(exp_groups[exp_date])
            dedup_count = len(exp_groups[exp_date])
            if original_count != dedup_count:
                logger.info(
                    f"Deduplicated {exp_date}: {original_count} -> {dedup_count} rows"
                )

        # ================================================================
        # STEP 2: Select front month (13-48 DTE, like Polygon)
        # ================================================================
        front_month = None
        for exp_date in sorted(exp_groups.keys(), key=lambda x: exp_dte[x]):
            dte = exp_dte[exp_date]
            if 13 <= dte <= 48:
                front_month = exp_date
                break

        # Fallback: if no expiration in 13-48 DTE range, use nearest with DTE >= 7
        if not front_month:
            sorted_by_dte = sorted(exp_groups.keys(), key=lambda x: exp_dte[x])
            for exp_date in sorted_by_dte:
                dte = exp_dte[exp_date]
                if dte >= 7:  # Minimum 7 days to avoid very short-term noise
                    front_month = exp_date
                    logger.info(
                        f"Fallback: using {exp_date} ({dte} DTE) for {ticker} - "
                        f"geen expiration in standaard 13-48 DTE range"
                    )
                    break

        if not front_month:
            logger.warning(f"Geen bruikbare expiration gevonden voor {ticker}")
            return None

        # ================================================================
        # STEP 3: Select M2 and M3 (next two monthly expirations)
        # ================================================================
        sorted_exps = sorted(exp_groups.keys(), key=lambda x: exp_dte[x])
        front_idx = sorted_exps.index(front_month)

        month2 = sorted_exps[front_idx + 1] if front_idx + 1 < len(sorted_exps) else None
        month3 = sorted_exps[front_idx + 2] if front_idx + 2 < len(sorted_exps) else None

        # ================================================================
        # STEP 4: Extract ATM call from front month (like Polygon)
        # ================================================================
        atm_iv = self._extract_atm_call(exp_groups[front_month], spot_price)

        # ================================================================
        # STEP 5: Extract ATM calls from M2 and M3 for term structure
        # ================================================================
        iv_month2 = None
        iv_month3 = None

        if month2:
            iv_month2 = self._extract_atm_call(exp_groups[month2], spot_price)

        if month3:
            iv_month3 = self._extract_atm_call(exp_groups[month3], spot_price)

        # Term structure: M1-M2 and M1-M3 (matching Polygon formula)
        term_m1_m2 = None
        term_m1_m3 = None

        if atm_iv is not None and iv_month2 is not None:
            term_m1_m2 = round((atm_iv - iv_month2) * 100, 2)

        if atm_iv is not None and iv_month3 is not None:
            term_m1_m3 = round((atm_iv - iv_month3) * 100, 2)

        # ================================================================
        # STEP 6: Extract skew from FRONT MONTH ONLY (matching Polygon)
        # ================================================================
        skew = self._extract_skew(exp_groups[front_month], spot_price)

        # ================================================================
        # STEP 7: Calculate IV Rank and Percentile using historical IV
        # ================================================================
        iv_rank_value = None
        iv_percentile_value = None

        if atm_iv is not None:
            try:
                # Use historical IV series for rank/percentile (not HV)
                # parsed_date is already a string in YYYY-MM-DD format
                iv_series = get_historical_iv_series(ticker, exclude_date=parsed_date)
                if iv_series:
                    # Scale IV to percentage for comparison
                    scaled_iv = atm_iv * 100
                    iv_rank_value = iv_rank(scaled_iv, iv_series)
                    iv_percentile_value = iv_percentile(scaled_iv, iv_series)

                    # Convert to 0-100 scale (iv_rank and iv_percentile return 0-1)
                    if isinstance(iv_rank_value, (int, float)):
                        iv_rank_value *= 100
                    if isinstance(iv_percentile_value, (int, float)):
                        iv_percentile_value *= 100
                else:
                    logger.debug(f"Insufficient IV history for {ticker} on {parsed_date}")
            except Exception as exc:
                logger.warning(f"IV rank/percentile berekening mislukt voor {ticker}: {exc}")

        return OratsRecord(
            ticker=ticker,
            date=parsed_date,
            atm_iv=atm_iv,
            term_m1_m2=term_m1_m2,
            term_m1_m3=term_m1_m3,
            skew=skew,
            iv_rank=iv_rank_value,
            iv_percentile=iv_percentile_value,
        )

    def _extract_atm_call(
        self, rows: list[dict[str, str]], spot_price: float
    ) -> float | None:
        """Extract single ATM call IV (closest to spot, matching Polygon).

        Follows IVExtractor.extract_atm_call from polygon_iv.py:
        - Only call options
        - Find strike closest to spot
        - Filter out extreme deltas (< 0.05 or > 0.95)
        """
        atm_iv = None
        atm_err = float("inf")

        for row in rows:
            try:
                strike = float(row.get("strike", 0))
                c_mid_iv = row.get("cMidIv", "").strip()
                c_delta = row.get("cDelta", "").strip()

                if not c_mid_iv or c_mid_iv == "null":
                    continue

                iv_val = float(c_mid_iv)

                # Delta filtering (matching Polygon)
                if c_delta and c_delta != "null":
                    delta_val = float(c_delta)
                    if delta_val < 0.05 or delta_val > 0.95:
                        continue

                # Find closest strike to spot
                diff = abs(strike - spot_price)
                if diff < atm_err:
                    atm_err = diff
                    atm_iv = iv_val

            except (ValueError, TypeError):
                continue

        return atm_iv

    def _extract_skew(
        self, rows: list[dict[str, str]], spot_price: float
    ) -> float | None:
        """Extract skew from single expiration (matching Polygon).

        Follows IVExtractor.extract_skew from polygon_iv.py:
        - Primary: Delta-based (call δ ≈ 0.25, put δ ≈ -0.25)
        - Fallback: Strike-based (call 115%, put 85%)
        - Formula: (put_iv - call_iv) * 100
        """
        call_iv: float | None = None
        put_iv: float | None = None
        call_delta_err = float("inf")
        put_delta_err = float("inf")
        call_strike_err = float("inf")
        put_strike_err = float("inf")

        target_call = spot_price * 1.15
        target_put = spot_price * 0.85

        for row in rows:
            try:
                strike = float(row.get("strike", 0))
                p_mid_iv = row.get("pMidIv", "").strip()
                c_mid_iv = row.get("cMidIv", "").strip()
                p_delta = row.get("pDelta", "").strip()
                c_delta = row.get("cDelta", "").strip()

                # Delta-based selection (primary method)
                if p_delta and p_delta != "null" and p_mid_iv and p_mid_iv != "null":
                    try:
                        delta_val = float(p_delta)
                        iv_val = float(p_mid_iv)
                        # Target delta around -0.25
                        err = abs(delta_val + 0.25)
                        if err < put_delta_err:
                            put_delta_err = err
                            put_iv = iv_val
                    except ValueError:
                        pass

                if c_delta and c_delta != "null" and c_mid_iv and c_mid_iv != "null":
                    try:
                        delta_val = float(c_delta)
                        iv_val = float(c_mid_iv)
                        # Target delta around +0.25
                        err = abs(delta_val - 0.25)
                        if err < call_delta_err:
                            call_delta_err = err
                            call_iv = iv_val
                    except ValueError:
                        pass

                # Strike-based fallback
                if p_mid_iv and p_mid_iv != "null":
                    try:
                        iv_val = float(p_mid_iv)
                        diff = abs(strike - target_put)
                        if diff < put_strike_err:
                            put_strike_err = diff
                            # Only use fallback if no delta-based selection
                            if put_delta_err == float("inf"):
                                put_iv = iv_val
                    except ValueError:
                        pass

                if c_mid_iv and c_mid_iv != "null":
                    try:
                        iv_val = float(c_mid_iv)
                        diff = abs(strike - target_call)
                        if diff < call_strike_err:
                            call_strike_err = diff
                            # Only use fallback if no delta-based selection
                            if call_delta_err == float("inf"):
                                call_iv = iv_val
                    except ValueError:
                        pass

            except (ValueError, TypeError):
                continue

        if call_iv is not None and put_iv is not None:
            return round((put_iv - call_iv) * 100, 2)

        return None

    def _deduplicate_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        """Deduplicate rows by (strike, option_type) combination.

        When multiple rows exist for the same strike and type, keep the last one
        in the CSV (simulating Polygon's deduplication by latest timestamp).

        This matches Polygon's deduplication logic in polygon_iv.py:389-463.
        """
        seen: dict[tuple[float, str], dict[str, str]] = {}

        for row in rows:
            try:
                strike = float(row.get("strike", 0))

                # Determine option type based on which IV fields are populated
                c_mid_iv = row.get("cMidIv", "").strip()
                p_mid_iv = row.get("pMidIv", "").strip()

                # Create entries for both call and put if both exist
                if c_mid_iv and c_mid_iv != "null":
                    key = (strike, "call")
                    seen[key] = row

                if p_mid_iv and p_mid_iv != "null":
                    key = (strike, "put")
                    seen[key] = row

            except (ValueError, TypeError):
                # Skip rows with invalid strike prices
                continue

        # Return deduplicated rows
        return list(seen.values())

    def _merge_records(
        self, symbol: str, new_records: list[OratsRecord]
    ) -> tuple[list[dict[str, Any]], Path | None]:
        """Merge new records into existing JSON file."""
        summary_dir = Path(cfg.get("IV_SUMMARY_DIR", "tomic/data/iv_daily_summary")).expanduser()
        summary_file = summary_dir / f"{symbol}.json"

        # Load existing data
        existing = load_json(summary_file)
        if not isinstance(existing, list):
            existing = []

        # Build map of existing records
        merged: dict[str, dict[str, Any]] = {}
        for record in existing:
            if isinstance(record, dict) and "date" in record:
                merged[str(record["date"])] = dict(record)

        # Merge new records, tracking changes for validation
        for new_record in new_records:
            date = new_record.date
            old_record = merged.get(date, {})
            old_atm_iv = old_record.get("atm_iv")
            new_atm_iv = new_record.atm_iv

            # Track validation entry
            delta = None
            if old_atm_iv is not None and new_atm_iv is not None:
                delta = new_atm_iv - old_atm_iv

            self.validation_entries.append(
                ValidationEntry(
                    symbol=symbol,
                    date=date,
                    old_atm_iv=old_atm_iv,
                    new_atm_iv=new_atm_iv,
                    delta_atm_iv=delta,
                )
            )

            # Update record with all ORATS-calculated metrics
            # NOTE: Now includes IV rank/percentile (previously not calculated)
            base = old_record.copy()
            if new_record.atm_iv is not None:
                base["atm_iv"] = new_record.atm_iv
            if new_record.term_m1_m2 is not None:
                base["term_m1_m2"] = new_record.term_m1_m2
            if new_record.term_m1_m3 is not None:
                base["term_m1_m3"] = new_record.term_m1_m3
            if new_record.skew is not None:
                base["skew"] = new_record.skew
            if new_record.iv_rank is not None:
                base["iv_rank (IV)"] = new_record.iv_rank
            if new_record.iv_percentile is not None:
                base["iv_percentile (IV)"] = new_record.iv_percentile
            base["date"] = date
            merged[date] = base

        # Sort by date
        merged_list = sorted(merged.values(), key=lambda r: r.get("date", ""))

        # Write to temp file first, then atomic replace
        summary_dir.mkdir(parents=True, exist_ok=True)
        tmp = summary_file.with_name(f"temp_{summary_file.name}")
        dump_json(merged_list, tmp)
        self._safe_replace_file(tmp, summary_file)

        return merged_list, None

    def _generate_validation_report(self) -> Path:
        """Generate CSV validation report with old vs new comparisons."""
        logs_dir = Path("tomic/logs").expanduser()
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = logs_dir / f"orats_validation_{timestamp}.csv"

        with report_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["symbol", "date", "old_atm_iv", "new_atm_iv", "delta_atm_iv"])

            for entry in self.validation_entries:
                writer.writerow([
                    entry.symbol,
                    entry.date,
                    f"{entry.old_atm_iv:.6f}" if entry.old_atm_iv is not None else "",
                    f"{entry.new_atm_iv:.6f}" if entry.new_atm_iv is not None else "",
                    f"{entry.delta_atm_iv:+.6f}" if entry.delta_atm_iv is not None else "",
                ])

        logger.info(f"Validation rapport gegenereerd: {report_path}")
        return report_path

    def _safe_replace_file(self, src: Path, dst: Path, max_retries: int = 5) -> bool:
        """Safely replace a file with retry logic for Windows file locking.

        On Windows, file handles may not be immediately released after closing.
        This method retries replacement with exponential backoff.
        """
        for attempt in range(max_retries):
            try:
                src.replace(dst)
                return True
            except PermissionError:
                if attempt < max_retries - 1:
                    wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s, 4s, 8s
                    logger.debug(
                        f"Bestand nog in gebruik, retry {attempt + 1}/{max_retries} "
                        f"voor {dst.name} in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    # Last resort: try copy + delete instead of atomic replace
                    try:
                        shutil.copy2(src, dst)
                        self._safe_delete_file(src)
                        return True
                    except Exception as exc:
                        logger.error(
                            f"Kon bestand niet vervangen na {max_retries} pogingen: {dst} - {exc}"
                        )
                        return False
            except Exception as exc:
                logger.error(f"Onverwachte fout bij vervangen {dst}: {exc}")
                return False
        return False

    def _safe_delete_file(self, path: Path, max_retries: int = 5) -> bool:
        """Safely delete a file with retry logic for Windows file locking.

        On Windows, file handles may not be immediately released after closing.
        This method retries deletion with exponential backoff.
        """
        if not path.exists():
            return True

        for attempt in range(max_retries):
            try:
                path.unlink()
                return True
            except PermissionError:
                if attempt < max_retries - 1:
                    wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s, 4s, 8s
                    logger.debug(
                        f"Bestand nog in gebruik, retry {attempt + 1}/{max_retries} "
                        f"voor {path.name} in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.warning(
                        f"Kon bestand niet verwijderen na {max_retries} pogingen: {path}"
                    )
                    return False
            except Exception as exc:
                logger.warning(f"Onverwachte fout bij verwijderen {path}: {exc}")
                return False
        return False

    def _is_weekend(self, date: datetime) -> bool:
        """Check if date is weekend (Saturday=5, Sunday=6)."""
        return date.weekday() >= 5

    def _parse_date_input(self, date_str: str) -> datetime | None:
        """Parse dd/mm/yyyy format."""
        try:
            return datetime.strptime(date_str.strip(), "%d/%m/%Y")
        except ValueError:
            return None

    def _load_default_symbols(self) -> list[str]:
        """Load default symbols from config/symbols.yaml."""
        symbols_path = Path("config/symbols.yaml").expanduser()
        if not symbols_path.exists():
            logger.warning("symbols.yaml niet gevonden, gebruik lege lijst")
            return []

        try:
            with symbols_path.open("r") as f:
                symbols = yaml.safe_load(f)
                if isinstance(symbols, list):
                    # Remove duplicates and uppercase
                    return sorted(set(s.upper() for s in symbols if s))
                return []
        except Exception as exc:
            logger.error(f"Fout bij laden symbols.yaml: {exc}")
            return []

    def run(self) -> None:
        """Main interactive flow for ORATS backfill."""
        print("\n=== ORATS IV Backfill ===\n")

        # Get date range
        start_str = prompt("Startdatum (dd/mm/yyyy): ").strip()
        start_date = self._parse_date_input(start_str)
        if not start_date:
            print("❌ Ongeldige startdatum")
            return

        end_str = prompt("Einddatum (dd/mm/yyyy): ").strip()
        end_date = self._parse_date_input(end_str)
        if not end_date:
            print("❌ Ongeldige einddatum")
            return

        if start_date > end_date:
            print("❌ Startdatum moet voor einddatum liggen")
            return

        # Get symbols
        use_default = prompt_yes_no("Default symbols uit config/symbols.yaml gebruiken?", True)
        if use_default:
            symbols = self._load_default_symbols()
            if not symbols:
                print("❌ Geen symbols gevonden in config/symbols.yaml")
                return
            print(f"✓ {len(symbols)} symbols geladen uit config")
        else:
            symbols_input = prompt("Symbolen (komma-gescheiden): ").strip().upper()
            if not symbols_input:
                print("❌ Geen symbolen opgegeven")
                return
            symbols = [s.strip() for s in symbols_input.split(",") if s.strip()]

        symbols_set = set(symbols)

        # Calculate trading days (skip weekends)
        trading_days = []
        current = start_date
        while current <= end_date:
            if not self._is_weekend(current):
                trading_days.append(current)
            current += timedelta(days=1)

        # Determine which dates need processing (gap detection)
        print("\n🔍 Analyseren welke data nog ontbreekt...")
        dates_to_process, missing_by_symbol = self._get_dates_to_process(symbols, trading_days)

        # Count cache hits
        cached_count = sum(1 for d in dates_to_process if self._get_cache_path(d).exists())
        download_count = len(dates_to_process) - cached_count

        # Count total missing symbol-days
        total_missing = sum(len(dates) for dates in missing_by_symbol.values())
        symbols_with_gaps = len(missing_by_symbol)

        # Confirmation
        print(f"\n📊 Samenvatting:")
        print(f"   Periode: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        print(f"   Handelsdagen in periode: {len(trading_days)}")
        print(f"   Symbolen: {len(symbols)} ({symbols_with_gaps} met ontbrekende data)")

        # Show which symbols have missing data
        if missing_by_symbol:
            missing_symbols_list = sorted(missing_by_symbol.keys())
            if len(missing_symbols_list) <= 10:
                print(f"   Symbolen met gaps: {', '.join(missing_symbols_list)}")
            else:
                print(f"   Symbolen met gaps: {', '.join(missing_symbols_list[:10])}... (+{len(missing_symbols_list) - 10})")

        print(f"   Dagen te verwerken: {len(dates_to_process)} (van {len(trading_days)})")
        print(f"   Cache hits: {cached_count} | Te downloaden: {download_count}")
        print(f"   Totaal symbool-dagen te verwerken: {total_missing}")

        if not dates_to_process:
            print("\n✅ Alle data is al aanwezig, geen verwerking nodig!")
            return

        if not prompt_yes_no("\nDoorgaan met backfill?", True):
            print("Geannuleerd.")
            return

        # FTP connection will be created lazily when needed (if cache misses)
        ftp: ftplib.FTP | None = None

        processed_symbols: set[str] = set()
        failed_downloads = 0
        missing_symbols = 0
        cache_hits = 0

        try:
            for idx, date in enumerate(dates_to_process, 1):
                date_str = date.strftime("%Y%m%d")
                date_key = date.strftime("%Y-%m-%d")

                # Get symbols that need this date
                symbols_needing_date = [
                    s for s in symbols
                    if s in missing_by_symbol and date_key in missing_by_symbol[s]
                ]

                if not symbols_needing_date:
                    continue

                print(f"\n[{idx}/{len(dates_to_process)}] {date.strftime('%d/%m/%Y')} ({date_str}) - {len(symbols_needing_date)} symbols")

                # Get from cache or download
                zip_path, ftp = self._get_cached_or_download(ftp, date)

                if zip_path is None:
                    failed_downloads += 1
                    logger.warning(f"Kon ZIP niet ophalen voor {date_str}")
                    continue

                if self._get_cache_path(date).exists():
                    cache_hits += 1

                # Parse CSV - only request symbols that need this date
                symbols_for_date = set(symbols_needing_date)
                day_records = self._parse_orats_csv(zip_path, symbols_for_date)

                if not day_records:
                    # Show which symbols were not found (likely didn't exist yet)
                    not_found = sorted(symbols_for_date)
                    if len(not_found) <= 5:
                        symbols_str = ", ".join(not_found)
                    else:
                        symbols_str = f"{', '.join(not_found[:5])}... (+{len(not_found) - 5} meer)"
                    logger.warning(f"Symbolen niet gevonden in ORATS data voor {date_str}: {symbols_str}")
                    logger.info(f"  ℹ️  Deze symbolen bestonden mogelijk nog niet op deze datum")
                    missing_symbols += len(symbols_needing_date)
                    continue

                # Report symbols that were requested but not found
                found_symbols = set(day_records.keys())
                not_found_symbols = symbols_for_date - found_symbols
                if not_found_symbols:
                    if len(not_found_symbols) <= 3:
                        nf_str = ", ".join(sorted(not_found_symbols))
                    else:
                        nf_sorted = sorted(not_found_symbols)
                        nf_str = f"{', '.join(nf_sorted[:3])}... (+{len(not_found_symbols) - 3})"
                    print(f"  ⚠️  Niet gevonden: {nf_str} (bestond mogelijk nog niet)")

                # Update JSON files per symbol
                for symbol, records in day_records.items():
                    merged_records, backup_path = self._merge_records(symbol, records)
                    processed_symbols.add(symbol)
                    print(f"  ✓ {symbol}: {len(merged_records)} totaal records")

                # ZIP files blijven in cache - niet verwijderen!

        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    pass  # FTP connection may already be closed

        # Generate validation report
        if self.validation_entries:
            report_path = self._generate_validation_report()

            # Calculate statistics
            deltas = [e.delta_atm_iv for e in self.validation_entries if e.delta_atm_iv is not None]
            if deltas:
                mean_delta = sum(abs(d) for d in deltas) / len(deltas)
                max_delta = max(abs(d) for d in deltas)

                print(f"\n📈 Validation statistieken:")
                print(f"   Totaal updates: {len(self.validation_entries)}")
                print(f"   Met delta: {len(deltas)}")
                print(f"   Mean |delta|: {mean_delta:.6f}")
                print(f"   Max |delta|: {max_delta:.6f}")
                print(f"   Rapport: {report_path}")

        # Summary
        print(f"\n✅ ORATS backfill voltooid!")
        print(f"   Processed symbols: {len(processed_symbols)}/{len(symbols)}")
        print(f"   Cache hits: {cache_hits}")
        print(f"   Failed downloads: {failed_downloads}")
        print(f"   Cache locatie: {self.cache_dir}")

        if failed_downloads > 0:
            logger.warning(f"{failed_downloads} downloads mislukt, zie logs voor details")


def run_orats_backfill_flow() -> None:
    """Entry point for ORATS backfill flow."""
    flow = OratsBackfillFlow()
    flow.run()


def main() -> None:
    """CLI entrypoint for ``python -m tomic.cli.orats_backfill_flow``."""
    run_orats_backfill_flow()


if __name__ == "__main__":
    main()
