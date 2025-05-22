import subprocess

markets = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VIX",
    "AAPL",
    "MSFT",
    "GOOG",
    "AMZN",
    "TSLA",
]


def run():
    for sym in markets:
        print(f"▶ Exporteren: {sym}")
        subprocess.run(
            ["python", "getonemarket.py"],
            check=True,
            text=True,
            input=sym + "\n",
        )


if __name__ == "__main__":
    run()

