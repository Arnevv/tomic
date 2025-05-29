from tomic.api.getallmarkets import run, export_combined_csv
from datetime import datetime
import os
import time

if __name__ == "__main__":
    symbols = [
        "AAPL", "ASML", "CRM", "DIA", "EWG", "EWJ", "EWZ", "FEZ", "FXI",
        "GLD", "INDA", "NVDA", "QQQ", "RUT", "SPY", "TSLA", "VIX",
        "XLE", "XLF", "XLV"
    ]
    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    data_frames = []
    for sym in symbols:
        print(f"\n🔄 Ophalen voor {sym}...")
        df = run(sym)
        if df is not None:
            data_frames.append(df)
        time.sleep(2)

    unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
    if len(unique_markets) > 1:
        export_combined_csv(data_frames, export_dir)
