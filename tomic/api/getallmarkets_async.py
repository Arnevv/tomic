import asyncio
from datetime import datetime
import os
from typing import Iterable, List

from .getallmarkets import run, export_combined_csv


async def run_async(symbol: str):
    """Run the blocking ``run`` function in a thread."""
    return await asyncio.to_thread(run, symbol)


async def gather_markets(symbols: Iterable[str]):
    """Fetch market data for multiple symbols concurrently."""
    tasks = [run_async(sym) for sym in symbols]
    results: List = await asyncio.gather(*tasks)
    today_str = datetime.now().strftime("%Y%m%d")
    export_dir = os.path.join("exports", today_str)
    data_frames = [df for df in results if df is not None]
    if data_frames:
        unique_markets = {df["Symbol"].iloc[0] for df in data_frames}
        if len(unique_markets) > 1:
            export_combined_csv(data_frames, export_dir)
    return data_frames

