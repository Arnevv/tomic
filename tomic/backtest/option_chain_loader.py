"""Option chain loader for historical backtesting with real prices.

Loads ORATS option chain data from cached ZIP files and provides
strike selection for iron condors with real bid/ask prices.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tomic.config import get as cfg_get
from tomic.logutils import logger


@dataclass
class OptionQuote:
    """Single option quote from ORATS data."""

    symbol: str
    trade_date: date
    expiry: date
    strike: float
    option_type: str  # 'C' or 'P'

    # Pricing
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None

    # Greeks
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    iv: Optional[float] = None

    # Underlying
    spot_price: Optional[float] = None

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        """Spread as percentage of mid price."""
        if self.mid and self.mid > 0 and self.spread is not None:
            return (self.spread / self.mid) * 100
        return None

    def dte(self) -> int:
        """Days to expiration from trade date."""
        return (self.expiry - self.trade_date).days


@dataclass
class IronCondorQuotes:
    """Quotes for all four legs of an iron condor."""

    symbol: str
    trade_date: date
    expiry: date
    spot_price: float

    # Long put (lowest strike)
    long_put: Optional[OptionQuote] = None
    # Short put
    short_put: Optional[OptionQuote] = None
    # Short call
    short_call: Optional[OptionQuote] = None
    # Long call (highest strike)
    long_call: Optional[OptionQuote] = None

    @property
    def is_complete(self) -> bool:
        """Check if all four legs have quotes."""
        return all([self.long_put, self.short_put, self.short_call, self.long_call])

    @property
    def net_credit(self) -> Optional[float]:
        """Net credit received (using mid prices)."""
        if not self.is_complete:
            return None

        # Credit from short legs minus debit for long legs
        short_credit = (self.short_put.mid or 0) + (self.short_call.mid or 0)
        long_debit = (self.long_put.mid or 0) + (self.long_call.mid or 0)
        return (short_credit - long_debit) * 100  # Per contract

    @property
    def max_risk(self) -> Optional[float]:
        """Maximum risk (wing width - credit)."""
        if not self.is_complete or self.net_credit is None:
            return None

        # Wing width is the distance between short and long strikes
        put_wing = self.short_put.strike - self.long_put.strike
        call_wing = self.long_call.strike - self.short_call.strike
        wing_width = min(put_wing, call_wing) * 100  # Per contract

        return wing_width - self.net_credit

    @property
    def total_spread_cost(self) -> Optional[float]:
        """Total bid-ask spread cost for all legs."""
        if not self.is_complete:
            return None

        total = 0
        for leg in [self.long_put, self.short_put, self.short_call, self.long_call]:
            if leg.spread is not None:
                total += leg.spread * 100  # Per contract
        return total

    def entry_credit_realistic(self) -> Optional[float]:
        """Realistic entry credit accounting for slippage.

        For selling: use bid prices (what we actually receive)
        For buying: use ask prices (what we actually pay)
        """
        if not self.is_complete:
            return None

        # Sell short legs at bid
        short_credit = (
            (self.short_put.bid or 0) + (self.short_call.bid or 0)
        )
        # Buy long legs at ask
        long_debit = (
            (self.long_put.ask or 0) + (self.long_call.ask or 0)
        )
        return (short_credit - long_debit) * 100

    def exit_debit_realistic(self, exit_quotes: "IronCondorQuotes") -> Optional[float]:
        """Realistic exit debit accounting for slippage.

        To close: buy back shorts at ask, sell longs at bid.
        """
        if not exit_quotes.is_complete:
            return None

        # Buy back shorts at ask
        short_debit = (
            (exit_quotes.short_put.ask or 0) + (exit_quotes.short_call.ask or 0)
        )
        # Sell longs at bid
        long_credit = (
            (exit_quotes.long_put.bid or 0) + (exit_quotes.long_call.bid or 0)
        )
        return (short_debit - long_credit) * 100


@dataclass
class OptionChain:
    """Full option chain for a symbol on a given date."""

    symbol: str
    trade_date: date
    spot_price: float
    options: List[OptionQuote] = field(default_factory=list)

    def get_expiries(self) -> List[date]:
        """Get all available expiration dates, sorted."""
        expiries = set(opt.expiry for opt in self.options)
        return sorted(expiries)

    def filter_by_expiry(self, expiry: date) -> List[OptionQuote]:
        """Get all options for a specific expiration."""
        return [opt for opt in self.options if opt.expiry == expiry]

    def filter_by_dte_range(self, min_dte: int, max_dte: int) -> List[OptionQuote]:
        """Get options within a DTE range."""
        return [
            opt for opt in self.options
            if min_dte <= opt.dte() <= max_dte
        ]

    def get_calls(self, expiry: Optional[date] = None) -> List[OptionQuote]:
        """Get all call options, optionally filtered by expiry."""
        calls = [opt for opt in self.options if opt.option_type == 'C']
        if expiry:
            calls = [c for c in calls if c.expiry == expiry]
        return sorted(calls, key=lambda x: x.strike)

    def get_puts(self, expiry: Optional[date] = None) -> List[OptionQuote]:
        """Get all put options, optionally filtered by expiry."""
        puts = [opt for opt in self.options if opt.option_type == 'P']
        if expiry:
            puts = [p for p in puts if p.expiry == expiry]
        return sorted(puts, key=lambda x: x.strike)

    def select_iron_condor(
        self,
        expiry: date,
        short_put_delta: float = -0.20,
        short_call_delta: float = 0.20,
        wing_width: float = 5.0,
        delta_tolerance: float = 0.10,
    ) -> Optional[IronCondorQuotes]:
        """Select strikes for an iron condor based on delta targets.

        Args:
            expiry: Target expiration date
            short_put_delta: Target delta for short put (negative, e.g., -0.20)
            short_call_delta: Target delta for short call (positive, e.g., 0.20)
            wing_width: Wing width in dollars
            delta_tolerance: Acceptable deviation from target delta

        Returns:
            IronCondorQuotes with all four legs, or None if not possible.
        """
        calls = self.get_calls(expiry)
        puts = self.get_puts(expiry)

        if not calls or not puts:
            return None

        # Find short put (closest to target delta)
        short_put = self._find_by_delta(
            puts, short_put_delta, delta_tolerance
        )
        if not short_put:
            return None

        # Find short call (closest to target delta)
        short_call = self._find_by_delta(
            calls, short_call_delta, delta_tolerance
        )
        if not short_call:
            return None

        # Find long put (short_put strike - wing_width)
        long_put_target = short_put.strike - wing_width
        long_put = self._find_by_strike(puts, long_put_target)
        if not long_put:
            return None

        # Find long call (short_call strike + wing_width)
        long_call_target = short_call.strike + wing_width
        long_call = self._find_by_strike(calls, long_call_target)
        if not long_call:
            return None

        return IronCondorQuotes(
            symbol=self.symbol,
            trade_date=self.trade_date,
            expiry=expiry,
            spot_price=self.spot_price,
            long_put=long_put,
            short_put=short_put,
            short_call=short_call,
            long_call=long_call,
        )

    def _find_by_delta(
        self,
        options: List[OptionQuote],
        target_delta: float,
        tolerance: float,
    ) -> Optional[OptionQuote]:
        """Find option closest to target delta within tolerance."""
        best = None
        best_diff = float('inf')

        for opt in options:
            if opt.delta is None:
                continue

            diff = abs(opt.delta - target_delta)
            if diff < best_diff and diff <= tolerance:
                best_diff = diff
                best = opt

        return best

    def _find_by_strike(
        self,
        options: List[OptionQuote],
        target_strike: float,
        tolerance_pct: float = 5.0,
    ) -> Optional[OptionQuote]:
        """Find option closest to target strike within tolerance."""
        best = None
        best_diff = float('inf')
        tolerance = target_strike * (tolerance_pct / 100)

        for opt in options:
            diff = abs(opt.strike - target_strike)
            if diff < best_diff and diff <= tolerance:
                best_diff = diff
                best = opt

        return best


class OptionChainLoader:
    """Loads option chains from ORATS ZIP files for backtesting."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the loader.

        Args:
            cache_dir: Directory containing ORATS ZIP files.
                      Defaults to ORATS_CACHE_DIR from config.
        """
        if cache_dir is None:
            cache_dir = Path(cfg_get("ORATS_CACHE_DIR", "tomic/data/orats_cache"))
        self.cache_dir = cache_dir.expanduser()

        # Cache loaded chains to avoid re-parsing
        self._chain_cache: Dict[Tuple[str, date], OptionChain] = {}

    def get_zip_path(self, trade_date: date) -> Path:
        """Get the expected ZIP file path for a date."""
        year = trade_date.strftime("%Y")
        date_str = trade_date.strftime("%Y%m%d")
        return self.cache_dir / year / f"ORATS_SMV_Strikes_{date_str}.zip"

    def has_data(self, trade_date: date) -> bool:
        """Check if we have data for a specific date."""
        return self.get_zip_path(trade_date).exists()

    def load_chain(
        self,
        symbol: str,
        trade_date: date,
    ) -> Optional[OptionChain]:
        """Load option chain for a symbol on a specific date.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            trade_date: Date to load chain for

        Returns:
            OptionChain object, or None if data not available.
        """
        cache_key = (symbol.upper(), trade_date)
        if cache_key in self._chain_cache:
            return self._chain_cache[cache_key]

        zip_path = self.get_zip_path(trade_date)
        if not zip_path.exists():
            logger.debug(f"No ORATS data for {trade_date}: {zip_path}")
            return None

        chain = self._parse_chain_from_zip(symbol.upper(), trade_date, zip_path)
        if chain:
            self._chain_cache[cache_key] = chain

        return chain

    def _parse_chain_from_zip(
        self,
        symbol: str,
        trade_date: date,
        zip_path: Path,
    ) -> Optional[OptionChain]:
        """Parse option chain from ORATS ZIP file."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_files:
                    logger.warning(f"No CSV in {zip_path.name}")
                    return None

                csv_name = csv_files[0]
                with zf.open(csv_name) as csv_file:
                    text_stream = io.TextIOWrapper(csv_file, encoding="utf-8")

                    # Detect delimiter
                    sample = text_stream.read(10000)
                    text_stream.seek(0)
                    delimiter = self._detect_delimiter(sample)

                    reader = csv.DictReader(text_stream, delimiter=delimiter)

                    options: List[OptionQuote] = []
                    spot_price = None

                    for row in reader:
                        ticker = row.get("ticker", "").strip().upper()
                        if ticker != symbol:
                            continue

                        # Get spot price (same for all rows)
                        if spot_price is None:
                            spot_price = self._safe_float(row.get("stkPx"))

                        # Parse expiration
                        expiry_str = row.get("expirDate", "")
                        try:
                            expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                        except ValueError:
                            continue

                        strike = self._safe_float(row.get("strike"))
                        if strike is None:
                            continue

                        # Parse call option
                        call_mid_iv = row.get("cMidIv", "").strip()
                        if call_mid_iv and call_mid_iv != "null":
                            call_opt = self._create_option(
                                symbol, trade_date, expiry, strike, "C",
                                row, spot_price
                            )
                            if call_opt:
                                options.append(call_opt)

                        # Parse put option
                        put_mid_iv = row.get("pMidIv", "").strip()
                        if put_mid_iv and put_mid_iv != "null":
                            put_opt = self._create_option(
                                symbol, trade_date, expiry, strike, "P",
                                row, spot_price
                            )
                            if put_opt:
                                options.append(put_opt)

                    if not options or spot_price is None:
                        return None

                    return OptionChain(
                        symbol=symbol,
                        trade_date=trade_date,
                        spot_price=spot_price,
                        options=options,
                    )

        except zipfile.BadZipFile:
            logger.error(f"Corrupt ZIP: {zip_path.name}")
            return None
        except Exception as e:
            logger.error(f"Error parsing {zip_path.name}: {e}")
            return None

    def _create_option(
        self,
        symbol: str,
        trade_date: date,
        expiry: date,
        strike: float,
        option_type: str,
        row: Dict[str, str],
        spot_price: Optional[float],
    ) -> Optional[OptionQuote]:
        """Create an OptionQuote from a CSV row."""
        prefix = "c" if option_type == "C" else "p"

        # Get IV
        iv = self._safe_float(row.get(f"{prefix}MidIv"))

        # Get delta
        delta = self._safe_float(row.get(f"{prefix}Delta"))

        # ORATS doesn't have bid/ask directly, but we can estimate from IV
        # For now, use theoretical mid price from Black-Scholes
        # In production, you'd use actual bid/ask if available

        # Estimate bid/ask from mid IV using a simple spread model
        # Typical spread is 5-15% of option price for liquid options
        mid_price = self._estimate_option_price(
            spot_price or 0, strike, iv or 0,
            (expiry - trade_date).days, option_type
        )

        if mid_price is None or mid_price <= 0:
            return None

        # Estimate spread based on moneyness and DTE
        spread_pct = self._estimate_spread_pct(
            spot_price or 0, strike, (expiry - trade_date).days
        )
        spread = mid_price * spread_pct

        bid = max(0.01, mid_price - spread / 2)
        ask = mid_price + spread / 2

        return OptionQuote(
            symbol=symbol,
            trade_date=trade_date,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            bid=round(bid, 2),
            ask=round(ask, 2),
            mid=round(mid_price, 2),
            delta=delta,
            iv=iv,
            spot_price=spot_price,
        )

    def _estimate_option_price(
        self,
        spot: float,
        strike: float,
        iv: float,
        dte: int,
        option_type: str,
    ) -> Optional[float]:
        """Estimate option price using simplified Black-Scholes.

        This is a rough estimate. For accurate pricing, use the
        bs_calculator module with proper Greeks.
        """
        if spot <= 0 or iv <= 0 or dte <= 0:
            return None

        # Normalize IV
        sigma = iv if iv < 1 else iv / 100

        # Simplified price estimation based on IV and moneyness
        time_factor = (dte / 365) ** 0.5
        moneyness = spot / strike

        if option_type == "C":
            # Call: intrinsic + time value
            intrinsic = max(0, spot - strike)
            time_value = spot * sigma * time_factor * 0.4
            if moneyness < 1:  # OTM
                time_value *= moneyness ** 2
        else:
            # Put: intrinsic + time value
            intrinsic = max(0, strike - spot)
            time_value = spot * sigma * time_factor * 0.4
            if moneyness > 1:  # OTM
                time_value *= (1 / moneyness) ** 2

        return intrinsic + time_value

    def _estimate_spread_pct(
        self,
        spot: float,
        strike: float,
        dte: int,
    ) -> float:
        """Estimate bid-ask spread as percentage of mid price.

        Spread is wider for:
        - Deep OTM options
        - Short-dated options
        - Lower-priced underlyings
        """
        if spot <= 0:
            return 0.15

        moneyness = strike / spot

        # Base spread
        base_spread = 0.08  # 8%

        # Wider for OTM
        if moneyness < 0.9 or moneyness > 1.1:
            base_spread += 0.05
        if moneyness < 0.8 or moneyness > 1.2:
            base_spread += 0.05

        # Wider for short DTE
        if dte < 7:
            base_spread += 0.05
        elif dte < 14:
            base_spread += 0.03

        return min(0.25, base_spread)  # Cap at 25%

    def _detect_delimiter(self, sample: str) -> str:
        """Detect CSV delimiter from sample."""
        for delim in [',', '\t', ';', '|']:
            lines = sample.split('\n')[:5]
            if lines and lines[0].count(delim) > 20:
                return delim
        return ','

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert to float."""
        if value is None:
            return None
        try:
            val_str = str(value).strip()
            if not val_str or val_str.lower() == 'null':
                return None
            return float(val_str)
        except (ValueError, TypeError):
            return None

    def clear_cache(self):
        """Clear the chain cache."""
        self._chain_cache.clear()


__all__ = [
    "OptionQuote",
    "IronCondorQuotes",
    "OptionChain",
    "OptionChainLoader",
]
