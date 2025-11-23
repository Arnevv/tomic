#!/usr/bin/env python3
"""
Diagnose script voor ORATS IV backfill troubleshooting.
Gebruik dit script om te inspecteren wat er in een ORATS ZIP file zit.
"""

import csv
import ftplib
import io
import os
import sys
import zipfile
from pathlib import Path
from collections import Counter

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, will use environment variables directly
    pass


def download_orats_file(date_str: str, output_path: Path) -> bool:
    """Download ORATS ZIP file voor een specifieke datum."""
    # Get FTP credentials
    ftp_host = os.getenv("ORATS_FTP_HOST", "de1.hostedftp.com")
    # Sanitize hostname (remove any path components)
    ftp_host = ftp_host.split("/")[0] if "/" in ftp_host else ftp_host

    ftp_user = os.getenv("ORATS_FTP_USER")
    ftp_password = os.getenv("ORATS_FTP_PASSWORD")
    ftp_path = os.getenv("ORATS_FTP_PATH", "smvstrikes")

    if not ftp_user or not ftp_password:
        print("❌ ORATS_FTP_USER en ORATS_FTP_PASSWORD moeten ingesteld zijn in .env")
        return False

    # Extract year from date string (format: YYYYMMDD)
    year = date_str[:4]

    # Remote path: smvstrikes/{YEAR}/ORATS_SMV_Strikes_{YYYYMMDD}.zip
    remote_path = f"{ftp_path}/{year}/ORATS_SMV_Strikes_{date_str}.zip"

    print(f"🔗 Verbinden met {ftp_host}...")
    try:
        ftp = ftplib.FTP(ftp_host)
        ftp.login(ftp_user, ftp_password)
        print(f"✓ Verbonden met {ftp_host}")

        print(f"📥 Downloaden van {remote_path}...")
        with output_path.open("wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)

        ftp.quit()
        print(f"✓ Gedownload naar {output_path}")
        return True

    except Exception as exc:
        print(f"❌ Download mislukt: {exc}")
        return False


def inspect_zip(zip_path: Path, target_symbol: str | None = None) -> None:
    """Inspecteer de inhoud van een ORATS ZIP file."""
    print(f"\n📊 Inspectie van {zip_path.name}")
    print("=" * 80)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # List files in ZIP
            print(f"\n📁 Bestanden in ZIP:")
            for name in zf.namelist():
                info = zf.getinfo(name)
                print(f"  - {name} ({info.file_size:,} bytes)")

            # Find CSV files
            csv_files = [name for name in zf.namelist() if name.endswith(".csv")]

            if not csv_files:
                print("\n❌ Geen CSV bestanden gevonden in ZIP")
                return

            # Process first CSV
            csv_name = csv_files[0]
            print(f"\n📄 Analyse van {csv_name}:")

            with zf.open(csv_name) as csv_file:
                text_stream = io.TextIOWrapper(csv_file, encoding="utf-8")
                reader = csv.DictReader(text_stream, delimiter="\t")

                # Get headers
                headers = reader.fieldnames
                print(f"\n📋 Kolommen ({len(headers)}):")
                for i, header in enumerate(headers, 1):
                    print(f"  {i:2d}. {header}")

                # Collect statistics
                ticker_count = Counter()
                target_rows = []
                total_rows = 0

                for row in reader:
                    total_rows += 1
                    ticker = row.get("ticker", "").strip().upper()
                    if ticker:
                        ticker_count[ticker] += 1

                        # Collect rows for target symbol
                        if target_symbol and ticker == target_symbol.upper():
                            target_rows.append(row)

                print(f"\n📊 Statistieken:")
                print(f"  Totaal rijen: {total_rows:,}")
                print(f"  Unieke symbolen: {len(ticker_count)}")

                # Top 10 symbols
                print(f"\n🔝 Top 10 symbolen (meeste opties):")
                for symbol, count in ticker_count.most_common(10):
                    print(f"  {symbol:6s}: {count:4d} rijen")

                # Check for target symbol
                if target_symbol:
                    target_upper = target_symbol.upper()
                    if target_upper in ticker_count:
                        print(f"\n✓ Symbool '{target_upper}' gevonden: {ticker_count[target_upper]} rijen")

                        # Show sample rows
                        print(f"\n📝 Eerste 5 rijen voor {target_upper}:")
                        for i, row in enumerate(target_rows[:5], 1):
                            print(f"\n  Rij {i}:")
                            # Show key fields
                            key_fields = [
                                "ticker", "trade_date", "stkPx", "strike",
                                "yte", "smoothSmvVol", "pMidIv", "cMidIv"
                            ]
                            for field in key_fields:
                                value = row.get(field, "N/A")
                                print(f"    {field:15s}: {value}")
                    else:
                        print(f"\n❌ Symbool '{target_upper}' NIET gevonden in data")
                        print(f"\n💡 Mogelijk vergelijkbare symbolen:")
                        similar = [s for s in ticker_count.keys() if target_upper in s or s in target_upper]
                        if similar:
                            for s in similar[:10]:
                                print(f"  - {s} ({ticker_count[s]} rijen)")
                        else:
                            print("  Geen vergelijkbare symbolen gevonden")

    except zipfile.BadZipFile:
        print(f"❌ Corrupt ZIP bestand: {zip_path}")
    except Exception as exc:
        print(f"❌ Fout bij inspectie: {exc}")
        import traceback
        traceback.print_exc()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Gebruik: python diagnose_orats.py <datum> [symbool]")
        print("")
        print("Argumenten:")
        print("  datum    - Datum in YYYYMMDD formaat (bijv. 20251121)")
        print("  symbool  - Optioneel: symbool om te zoeken (bijv. CRM)")
        print("")
        print("Voorbeeld:")
        print("  python diagnose_orats.py 20251121 CRM")
        sys.exit(1)

    date_str = sys.argv[1]
    target_symbol = sys.argv[2] if len(sys.argv) > 2 else None

    # Validate date format
    if len(date_str) != 8 or not date_str.isdigit():
        print("❌ Datum moet in YYYYMMDD formaat zijn (bijv. 20251121)")
        sys.exit(1)

    # Create temp directory
    temp_dir = Path("temp_diagnose")
    temp_dir.mkdir(exist_ok=True)

    zip_path = temp_dir / f"ORATS_SMV_Strikes_{date_str}.zip"

    try:
        # Download file
        if not download_orats_file(date_str, zip_path):
            sys.exit(1)

        # Inspect ZIP
        inspect_zip(zip_path, target_symbol)

        print(f"\n💾 ZIP bestand bewaard in: {zip_path}")
        print(f"   Je kunt dit handmatig inspecteren of verwijderen.")

    except KeyboardInterrupt:
        print("\n\n⚠️  Onderbroken door gebruiker")
        sys.exit(1)


if __name__ == "__main__":
    main()
