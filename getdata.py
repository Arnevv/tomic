import os
import csv
from datetime import datetime

def main():
    symbol = input("📈 Welk symbool wil je analyseren? (bijv. SPY, QQQ, TSLA): ").strip().upper()
    if not symbol:
        print("❌ Geen symbool opgegeven.")
        return

    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    os.makedirs(export_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"other_data_{symbol}_{timestamp}.csv"
    filepath = os.path.join(export_dir, filename)

    try:
        spot_price = float(input(f"Ga naar https://marketchameleon.com/Overview/{symbol}/Summary/ en voer de {symbol} spotprijs in: "))
        iv_30 = float(input("Voer de 30-day IV in: "))
        iv_rank = float(input("Voer de IV Rank in: "))
        hv_30 = float(input(f"Ga naar https://www.alphaquery.com/stock/{symbol}/volatility-option-statistics/30-day/historical-volatility en voer de 30-day Historical Volatility (HV30) in: "))
        vix = float(input("Ga naar https://www.barchart.com/stocks/quotes/$VIX/technical-analysis en voer de huidige VIX in: "))
        atr_14 = float(input(f"Ga naar https://www.barchart.com/etfs-funds/quotes/{symbol}/technical-analysis en voer de ATR(14) in: "))
        iv_call_25d = float(input("Ga naar TWS, ga naar monthly die dichtste bij de 30d zit en zoek de IV van de OTM 25-delta CALL: "))
        iv_put_25d = float(input("Voer de IV in van de OTM 25-delta PUT: "))
        skew = round(iv_call_25d - iv_put_25d, 2)
    except ValueError:
        print("❌ Ongeldige invoer. Gebruik numerieke waarden met puntnotatie (bijv. 21.4)")
        return

    headers = [
        "Symbol", "Spotprice", "IV30", "IV_Rank",
        "HV_30", "VIX", "ATR_14", "Skew"
    ]
    values = [
        symbol, spot_price, iv_30, iv_rank,
        hv_30, vix, atr_14, skew
    ]

    with open(filepath, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerow(values)

    print(f"✅ CSV opgeslagen als: {filepath}")

if __name__ == "__main__":
    main()
