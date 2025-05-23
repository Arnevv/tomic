from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import *
from ibapi.account_summary_tags import *
from ibapi.ticktype import TickTypeEnum

from datetime import datetime
import json
import math
import statistics
from get_iv_rank import fetch_iv_metrics

import threading
import time


class IBApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

        self.positions_data = []
        self.open_orders = []
        self.account_values = {}
        self.req_id = 5000
        self.req_id_to_index = {}
        self.market_req_id = 8000
        self.market_req_map = {}
        self.spot_data = {}
        self.historical_data = []
        self.hist_event = threading.Event()
        self.hv_data = {}
        self.atr_data = {}
        self.iv_rank_data = {}

    # ... je overige methods hier (onPosition, onAccountValue, enz.) ...


if __name__ == "__main__":
    app = IBApp()
    app.connect("127.0.0.1", 7497, clientId=123)

    # Start client thread
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()

    # Wacht op ophalen van data
    time.sleep(5)

    # Vul eventueel app.iv_rank_data met lege waarden voor alle symbols in positions
    for pos in app.positions_data:
        sym = pos["symbol"]
        app.iv_rank_data[sym] = None
        app.iv_rank_data[f"{sym}_pct"] = None

    portfolio = {"Delta": 0.0, "Gamma": 0.0, "Vega": 0.0, "Theta": 0.0}
    for pos in app.positions_data:
        mult = float(pos.get("multiplier") or 1)
        qty = pos.get("position", 0)
        for greek in ["delta", "gamma", "vega", "theta"]:
            val = pos.get(greek)
            if val is not None:
                portfolio[greek.capitalize()] += val * qty * mult

    print("\n📊 Account Balans:")
    for tag, value in app.account_values.items():
        print(f"{tag}: {value}")

    print("\n📈 Portfolio Posities:")
    for pos in app.positions_data:
        sym = pos["symbol"]
        pos["HV30"] = app.hv_data.get(sym)
        pos["ATR14"] = app.atr_data.get(sym)
        pos["IV_Rank"] = app.iv_rank_data.get(sym)
        pos["IV_Percentile"] = app.iv_rank_data.get(f"{sym}_pct")
        print(pos)

    with open("positions.json", "w", encoding="utf-8") as f:
        json.dump(app.positions_data, f, ensure_ascii=False, indent=2)
    print("\n📦 Posities opgeslagen in positions.json")

    print("\n📐 Portfolio Greeks:")
    for k, v in portfolio.items():
        print(f"{k}: {round(v, 4)}")

    print("\n📋 Openstaande Orders:")
    for order in app.open_orders:
        print(order)

    app.disconnect()
