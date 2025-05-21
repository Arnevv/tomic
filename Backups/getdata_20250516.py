import os
import csv
from datetime import datetime

def main():
    today_str = datetime.now().strftime("%y%m%d")
    export_dir = os.path.join("exports", today_str)
    os.makedirs(export_dir, exist_ok=True)

    filename = f"{today_str}_otherdata.csv"
    filepath = os.path.join(export_dir, filename)

    symbol = "SPY"
    try:
        spot_price = float(input("Ga naar https://marketchameleon.com/Overview/SPY/Summary/ en voer de SPY spotprijs in: "))
        iv_30 = float(input("Voer de 30-day IV in: "))
        iv_rank = float(input("Voer de IV Rank in: "))
        hv_30 = float(input("Ga naar https://www.alphaquery.com/stock/SPY/volatility-option-statistics/30-day/historical-volatility en voer de 30-day Historical Volatility (HV30) in: "))
        vix = float(input("Ga naar https://www.barchart.com/stocks/quotes/$VIX/technical-analysis en voer de huidige VIX in: "))
        atr_14 = float(input("Ga naar https://www.barchart.com/etfs-funds/quotes/SPY/technical-analysis en voer de ATR(14) in: "))
        iv_call_25d = float(input("Ga naar TWS, ga naar monthly die dichtste bij de 30d zit en zoek de IV van de OTM 25-delta CALL: "))
        iv_put_25d = float(input("Voer de IV in van de OTM 25-delta PUT: "))
        skew = round(iv_call_25d - iv_put_25d,1)
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
