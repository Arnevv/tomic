"""Interactive flow for ORATS IV backfill from FTP."""

from __future__ import annotations

import csv
import ftplib
import io
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import yaml

from tomic import config as cfg
from tomic.cli.common import prompt, prompt_yes_no
from tomic.helpers.json_utils import dump_json
from tomic.journal.utils import load_json
from tomic.logutils import logger

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
    """Single row from ORATS CSV with calculated metrics."""

    ticker: str
    date: str
    atm_iv: float | None
    term_m1_m2: float | None
    term_m1_m3: float | None
    skew: float | None


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

    def __init__(self):
        # Strip any trailing slashes and paths from hostname (FTP expects hostname only)
        raw_host = os.getenv("ORATS_FTP_HOST", "de1.hostedftp.com")
        self.ftp_host = raw_host.split("/")[0] if "/" in raw_host else raw_host
        self.ftp_user = os.getenv("ORATS_FTP_USER", "")
        self.ftp_password = os.getenv("ORATS_FTP_PASSWORD", "")
        self.ftp_path = os.getenv("ORATS_FTP_PATH", "smvstrikes")
        self.validation_entries: list[ValidationEntry] = []

    def _connect_ftp(self) -> ftplib.FTP:
        """Connect to ORATS FTP server."""
        if not self.ftp_user or not self.ftp_password:
            raise ValueError(
                "ORATS FTP credentials niet gevonden. "
                "Zet ORATS_FTP_USER en ORATS_FTP_PASSWORD in .env file."
            )

        try:
            ftp = ftplib.FTP(self.ftp_host)
            ftp.login(self.ftp_user, self.ftp_password)
            logger.info(f"FTP verbinding gemaakt met {self.ftp_host}")
            return ftp
        except Exception as exc:
            logger.error(f"FTP verbinding mislukt: {exc}")
            raise

    def _download_file(
        self, ftp: ftplib.FTP, remote_path: str, local_path: Path
    ) -> bool:
        """Download file from FTP with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with local_path.open("wb") as f:
                    ftp.retrbinary(f"RETR {remote_path}", f.write)
                logger.info(f"Downloaded: {remote_path}")
                return True
            except Exception as exc:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Download poging {attempt + 1} mislukt voor {remote_path}: {exc}. "
                        f"Retry in {wait}s..."
                    )
                    import time
                    time.sleep(wait)
                else:
                    logger.error(f"Download definitief mislukt na {max_retries} pogingen: {remote_path}")
                    return False
        return False

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

        Calculations aligned with Polygon methodology (compute_volstats_polygon.py):
        - ATM IV: ±3% tolerance (was ±2%)
        - Term structure: Expiration-based grouping with (M1-M2) sign convention
        - Skew: Delta-based selection (δ ≈ ±0.25) with strike-based fallback
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
        for date_format in ["%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
            try:
                parsed_date = datetime.strptime(trade_date, date_format).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

        if not parsed_date:
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

        # Calculate ATM IV (±3% moneyness to match Polygon)
        # Group by expiration date and average ATM strikes per expiration
        exp_atm_ivs: dict[str, list[float]] = {}
        tolerance = max(spot_price * 0.03, 2.0)

        for row in rows:
            try:
                strike = float(row.get("strike", 0))
                yte = float(row.get("yte", 0))
                smv_vol = row.get("smoothSmvVol", "").strip()
                exp_date = row.get("expirDate", "").strip()

                if not smv_vol or smv_vol == "" or smv_vol == "null":
                    continue
                if not exp_date:
                    continue

                iv = float(smv_vol)
                dte = yte * 365

                # ATM criteria: ±3% tolerance (matching Polygon)
                if abs(strike - spot_price) <= tolerance:
                    if exp_date not in exp_atm_ivs:
                        exp_atm_ivs[exp_date] = []
                    exp_atm_ivs[exp_date].append(iv)
            except (ValueError, TypeError):
                continue

        # Average all ATM IVs across all expirations for overall ATM IV
        all_atm_ivs = [iv for ivs in exp_atm_ivs.values() for iv in ivs]
        atm_iv = sum(all_atm_ivs) / len(all_atm_ivs) if all_atm_ivs else None

        # Calculate term structure using expiration-based grouping (matching Polygon)
        # Use the same exp_atm_ivs we already calculated above, or rebuild if needed
        if not exp_atm_ivs:
            # Rebuild if ATM IV calculation was skipped
            for row in rows:
                try:
                    strike = float(row.get("strike", 0))
                    smv_vol = row.get("smoothSmvVol", "").strip()
                    exp_date = row.get("expirDate", "").strip()

                    if not smv_vol or smv_vol == "" or smv_vol == "null":
                        continue
                    if not exp_date:
                        continue

                    iv = float(smv_vol)

                    # ATM criteria: ±3% tolerance
                    if abs(strike - spot_price) <= tolerance:
                        if exp_date not in exp_atm_ivs:
                            exp_atm_ivs[exp_date] = []
                        exp_atm_ivs[exp_date].append(iv)
                except (ValueError, TypeError):
                    continue

        # Sort expirations and take first 3
        sorted_exps = sorted(exp_atm_ivs.keys())
        exp_avgs: list[float] = []
        for exp in sorted_exps[:3]:
            ivs = exp_atm_ivs[exp]
            if ivs:
                exp_avgs.append(sum(ivs) / len(ivs))

        # Term structure: (first - second) matching Polygon's sign convention
        term_m1_m2 = round((exp_avgs[0] - exp_avgs[1]) * 100, 2) if len(exp_avgs) >= 2 else None
        term_m1_m3 = round((exp_avgs[0] - exp_avgs[2]) * 100, 2) if len(exp_avgs) >= 3 else None

        # Calculate skew using delta-based selection (matching Polygon)
        # Primary: Delta-based (target δ ≈ ±0.25)
        # Fallback: Strike-based (Puts 85%, Calls 115%)
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

                # Try delta-based selection first
                if p_delta and p_delta != "null" and p_mid_iv and p_mid_iv != "null":
                    try:
                        delta_val = float(p_delta)
                        iv_val = float(p_mid_iv)
                        # Target delta around -0.25 (range -0.30 to -0.20)
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
                        # Target delta around +0.25 (range 0.20 to 0.30)
                        err = abs(delta_val - 0.25)
                        if err < call_delta_err:
                            call_delta_err = err
                            call_iv = iv_val
                    except ValueError:
                        pass

                # Fallback: Strike-based selection
                if p_mid_iv and p_mid_iv != "null":
                    try:
                        iv_val = float(p_mid_iv)
                        diff = abs(strike - target_put)
                        if diff < put_strike_err:
                            put_strike_err = diff
                            # Only update if we don't have delta-based selection
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
                            # Only update if we don't have delta-based selection
                            if call_delta_err == float("inf"):
                                call_iv = iv_val
                    except ValueError:
                        pass

            except (ValueError, TypeError):
                continue

        skew = round((put_iv - call_iv) * 100, 2) if put_iv and call_iv else None

        return OratsRecord(
            ticker=ticker,
            date=parsed_date,
            atm_iv=atm_iv,
            term_m1_m2=term_m1_m2,
            term_m1_m3=term_m1_m3,
            skew=skew,
        )

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

            # Update record (don't overwrite HV-based metrics)
            base = old_record.copy()
            if new_record.atm_iv is not None:
                base["atm_iv"] = new_record.atm_iv
            if new_record.term_m1_m2 is not None:
                base["term_m1_m2"] = new_record.term_m1_m2
            if new_record.term_m1_m3 is not None:
                base["term_m1_m3"] = new_record.term_m1_m3
            if new_record.skew is not None:
                base["skew"] = new_record.skew
            base["date"] = date
            merged[date] = base

        # Sort by date
        merged_list = sorted(merged.values(), key=lambda r: r.get("date", ""))

        # Backup existing file
        backup_path: Path | None = None
        if summary_file.exists():
            backup_path = summary_file.with_suffix(summary_file.suffix + ".bak")
            shutil.copy2(summary_file, backup_path)

        # Write to temp file first, then atomic replace
        summary_dir.mkdir(parents=True, exist_ok=True)
        tmp = summary_file.with_name(f"temp_{summary_file.name}")
        dump_json(merged_list, tmp)
        tmp.replace(summary_file)

        return merged_list, backup_path

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

        # Confirmation
        print(f"\n📊 Samenvatting:")
        print(f"   Periode: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        print(f"   Handelsdagen: {len(trading_days)}")
        print(f"   Symbolen: {len(symbols)}")
        print(f"   Totaal: {len(trading_days) * len(symbols)} symbool-dagen")

        if not prompt_yes_no("\nDoorgaan met backfill?", True):
            print("Geannuleerd.")
            return

        # Connect to FTP
        print("\n🔗 Verbinden met ORATS FTP server...")
        try:
            ftp = self._connect_ftp()
        except Exception as exc:
            print(f"❌ FTP verbinding mislukt: {exc}")
            return

        # Process each day
        temp_dir = Path("temp_orats")
        temp_dir.mkdir(exist_ok=True)

        processed_symbols: set[str] = set()
        failed_downloads = 0
        missing_symbols = 0

        try:
            for idx, date in enumerate(trading_days, 1):
                date_str = date.strftime("%Y%m%d")
                year = date.strftime("%Y")

                # ORATS path: smvstrikes/{YEAR}/ORATS_SMV_Strikes_{YYYYMMDD}.zip
                remote_path = f"{self.ftp_path}/{year}/ORATS_SMV_Strikes_{date_str}.zip"
                local_path = temp_dir / f"ORATS_SMV_Strikes_{date_str}.zip"

                print(f"\n[{idx}/{len(trading_days)}] {date.strftime('%d/%m/%Y')} ({date_str})")

                # Download
                if not self._download_file(ftp, remote_path, local_path):
                    failed_downloads += 1
                    logger.warning(f"Download mislukt: {remote_path}")
                    continue

                # Parse CSV
                day_records = self._parse_orats_csv(local_path, symbols_set)

                if not day_records:
                    logger.warning(f"Geen data gevonden voor {date_str}")
                    missing_symbols += len(symbols)
                    continue

                # Update JSON files per symbol
                for symbol, records in day_records.items():
                    merged_records, backup_path = self._merge_records(symbol, records)
                    processed_symbols.add(symbol)
                    print(f"  ✓ {symbol}: {len(merged_records)} totaal records")

                # Cleanup
                local_path.unlink(missing_ok=True)

        finally:
            ftp.quit()
            # Cleanup temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

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
        print(f"   Failed downloads: {failed_downloads}")

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
