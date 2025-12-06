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

    # Pricing (from ORATS: cBidPx, cAskPx, pBidPx, pAskPx, cValue, pValue)
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    theoretical_value: Optional[float] = None  # cValue/pValue from ORATS

    # Greeks (from ORATS: delta, gamma, theta, vega, rho, phi)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    rho: Optional[float] = None
    phi: Optional[float] = None
    iv: Optional[float] = None

    # Underlying
    spot_price: Optional[float] = None

    # Liquidity metrics (from ORATS cVolu, cOi, pVolu, pOi)
    volume: Optional[int] = None
    open_interest: Optional[int] = None

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

    @property
    def liquidity_score(self) -> float:
        """Calculate liquidity score (0-100) based on volume, OI, and spread.

        Higher score = better liquidity.
        Components:
        - Volume: 0-40 points (>1000 = max)
        - Open Interest: 0-40 points (>5000 = max)
        - Spread: 0-20 points (<5% = max, >20% = 0)
        """
        score = 0.0

        # Volume component (0-40 points)
        if self.volume is not None:
            vol_score = min(40, (self.volume / 1000) * 40)
            score += vol_score

        # Open Interest component (0-40 points)
        if self.open_interest is not None:
            oi_score = min(40, (self.open_interest / 5000) * 40)
            score += oi_score

        # Spread component (0-20 points, inverted - tighter = better)
        if self.spread_pct is not None:
            if self.spread_pct <= 5:
                spread_score = 20
            elif self.spread_pct >= 20:
                spread_score = 0
            else:
                # Linear interpolation: 5% = 20 points, 20% = 0 points
                spread_score = 20 * (1 - (self.spread_pct - 5) / 15)
            score += spread_score

        return round(score, 1)

    def dte(self) -> int:
        """Days to expiration from trade date."""
        return (self.expiry - self.trade_date).days

    def passes_liquidity_threshold(
        self,
        min_volume: int = 0,
        min_oi: int = 0,
        max_spread_pct: float = 100.0,
    ) -> bool:
        """Check if option meets minimum liquidity requirements."""
        if min_volume > 0 and (self.volume is None or self.volume < min_volume):
            return False
        if min_oi > 0 and (self.open_interest is None or self.open_interest < min_oi):
            return False
        if max_spread_pct < 100 and self.spread_pct is not None:
            if self.spread_pct > max_spread_pct:
                return False
        return True


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

    @property
    def min_liquidity_score(self) -> float:
        """Minimum liquidity score across all legs (weakest link)."""
        if not self.is_complete:
            return 0.0
        scores = [
            self.long_put.liquidity_score,
            self.short_put.liquidity_score,
            self.short_call.liquidity_score,
            self.long_call.liquidity_score,
        ]
        return min(scores)

    @property
    def avg_liquidity_score(self) -> float:
        """Average liquidity score across all legs."""
        if not self.is_complete:
            return 0.0
        scores = [
            self.long_put.liquidity_score,
            self.short_put.liquidity_score,
            self.short_call.liquidity_score,
            self.long_call.liquidity_score,
        ]
        return sum(scores) / len(scores)

    @property
    def min_volume(self) -> int:
        """Minimum volume across all legs."""
        if not self.is_complete:
            return 0
        volumes = [
            leg.volume or 0
            for leg in [self.long_put, self.short_put, self.short_call, self.long_call]
        ]
        return min(volumes)

    @property
    def min_open_interest(self) -> int:
        """Minimum open interest across all legs."""
        if not self.is_complete:
            return 0
        ois = [
            leg.open_interest or 0
            for leg in [self.long_put, self.short_put, self.short_call, self.long_call]
        ]
        return min(ois)

    @property
    def max_spread_pct(self) -> float:
        """Maximum spread percentage across all legs (worst liquidity indicator)."""
        if not self.is_complete:
            return 100.0
        spreads = []
        for leg in [self.long_put, self.short_put, self.short_call, self.long_call]:
            if leg.spread_pct is not None:
                spreads.append(leg.spread_pct)
        return max(spreads) if spreads else 100.0

    def passes_liquidity_check(
        self,
        min_volume: int = 0,
        min_oi: int = 0,
        max_spread_pct: float = 100.0,
        min_liquidity_score: float = 0.0,
    ) -> tuple[bool, list[str]]:
        """Check if all legs meet minimum liquidity requirements.

        Returns:
            Tuple of (passes, list of rejection reasons)
        """
        if not self.is_complete:
            return False, ["Incomplete iron condor - missing legs"]

        reasons = []

        for name, leg in [
            ("long_put", self.long_put),
            ("short_put", self.short_put),
            ("short_call", self.short_call),
            ("long_call", self.long_call),
        ]:
            if not leg.passes_liquidity_threshold(min_volume, min_oi, max_spread_pct):
                vol = leg.volume or 0
                oi = leg.open_interest or 0
                spread = leg.spread_pct or 0
                reasons.append(
                    f"{name} ${leg.strike}: vol={vol}, OI={oi}, spread={spread:.1f}%"
                )

        if min_liquidity_score > 0 and self.min_liquidity_score < min_liquidity_score:
            reasons.append(
                f"Min liquidity score {self.min_liquidity_score:.1f} < {min_liquidity_score}"
            )

        return len(reasons) == 0, reasons


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

    def filter_by_liquidity(
        self,
        min_volume: int = 0,
        min_open_interest: int = 10,
    ) -> List[OptionQuote]:
        """Filter options by liquidity criteria.

        Args:
            min_volume: Minimum daily volume (0 = no filter)
            min_open_interest: Minimum open interest (default 10)

        Returns:
            List of options meeting liquidity criteria.
        """
        return [
            opt for opt in self.options
            if (opt.volume is None or opt.volume >= min_volume)
            and (opt.open_interest is None or opt.open_interest >= min_open_interest)
        ]

    def filter_by_spread(
        self,
        max_spread_pct: float = 20.0,
    ) -> List[OptionQuote]:
        """Filter options by bid-ask spread.

        Args:
            max_spread_pct: Maximum spread as percentage of mid price

        Returns:
            List of options with acceptable spreads.
        """
        result = []
        for opt in self.options:
            if opt.spread_pct is None:
                # Include if we can't calculate spread
                result.append(opt)
            elif opt.spread_pct <= max_spread_pct:
                result.append(opt)
        return result

    def get_liquid_options(
        self,
        min_open_interest: int = 10,
        max_spread_pct: float = 20.0,
    ) -> List[OptionQuote]:
        """Get options that meet liquidity and spread criteria.

        Args:
            min_open_interest: Minimum open interest
            max_spread_pct: Maximum spread as percentage of mid

        Returns:
            List of liquid options with reasonable spreads.
        """
        return [
            opt for opt in self.options
            if (opt.open_interest is None or opt.open_interest >= min_open_interest)
            and (opt.spread_pct is None or opt.spread_pct <= max_spread_pct)
        ]

    def liquidity_stats(self) -> Dict[str, Any]:
        """Get statistics about data quality and liquidity.

        Returns:
            Dict with stats about real prices, spreads, volume, etc.
        """
        if not self.options:
            return {}

        real_prices_count = sum(1 for o in self.options if o.has_real_prices)
        spreads = [o.spread_pct for o in self.options if o.spread_pct is not None]
        volumes = [o.volume for o in self.options if o.volume is not None]
        oi_values = [o.open_interest for o in self.options if o.open_interest is not None]

        return {
            "total_options": len(self.options),
            "real_prices_count": real_prices_count,
            "real_prices_pct": round(100 * real_prices_count / len(self.options), 1),
            "avg_spread_pct": round(sum(spreads) / len(spreads), 2) if spreads else None,
            "median_spread_pct": round(sorted(spreads)[len(spreads) // 2], 2) if spreads else None,
            "avg_volume": round(sum(volumes) / len(volumes)) if volumes else None,
            "avg_open_interest": round(sum(oi_values) / len(oi_values)) if oi_values else None,
        }

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
        """Create an OptionQuote from a CSV row.

        Uses real ORATS data when available:
        - cBidPx/pBidPx, cAskPx/pAskPx: Real bid/ask prices
        - cValue/pValue: Theoretical mid price
        - cVolu/pVolu: Trading volume
        - cOi/pOi: Open interest
        - delta, gamma, vega, theta: Greeks from ORATS 'delta', 'gamma', etc.
        """
        prefix = "c" if option_type == "C" else "p"

        # Get IV (mid, bid, ask)
        iv = self._safe_float(row.get(f"{prefix}MidIv"))

        # Get real bid/ask prices from ORATS (cBidPx, cAskPx, pBidPx, pAskPx)
        bid = self._safe_float(row.get(f"{prefix}BidPx"))
        ask = self._safe_float(row.get(f"{prefix}AskPx"))
        mid = self._safe_float(row.get(f"{prefix}Value"))

        # Get volume and open interest (cVolu, pVolu, cOi, pOi)
        volume = self._safe_int(row.get(f"{prefix}Volu"))
        open_interest = self._safe_int(row.get(f"{prefix}Oi"))

        # Get Greeks - ORATS uses single columns (delta, gamma, theta, vega)
        # which are for the call; for puts we need to adjust or get from pDelta etc.
        delta = self._safe_float(row.get(f"{prefix}Delta"))
        if delta is None:
            # Fallback to single 'delta' column (call delta)
            delta = self._safe_float(row.get("delta"))
            if delta is not None and option_type == "P":
                delta = delta - 1  # Put delta = call delta - 1

        gamma = self._safe_float(row.get("gamma"))
        vega = self._safe_float(row.get("vega"))
        theta = self._safe_float(row.get("theta"))

        # If no real prices, fall back to estimation
        if mid is None or mid <= 0:
            mid = self._estimate_option_price(
                spot_price or 0, strike, iv or 0,
                (expiry - trade_date).days, option_type
            )

        if mid is None or mid <= 0:
            return None

        # If no real bid/ask, estimate from mid
        if bid is None or ask is None:
            spread_pct = self._estimate_spread_pct(
                spot_price or 0, strike, (expiry - trade_date).days
            )
            spread = mid * spread_pct
            bid = max(0.01, mid - spread / 2) if bid is None else bid
            ask = mid + spread / 2 if ask is None else ask

        return OptionQuote(
            symbol=symbol,
            trade_date=trade_date,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            bid=round(bid, 2),
            ask=round(ask, 2),
            mid=round(mid, 2),
            delta=delta,
            gamma=gamma,
            vega=vega,
            theta=theta,
            iv=iv,
            spot_price=spot_price,
            volume=volume,
            open_interest=open_interest,
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
        # Use threshold of 2 to handle high-IV stocks (IV > 200% is unrealistic)
        sigma = iv if iv <= 2 else iv / 100

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

    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert to int (for volume/OI)."""
        if value is None:
            return None
        try:
            val_str = str(value).strip()
            if not val_str or val_str.lower() == 'null':
                return None
            # Handle floats like "1234.0"
            return int(float(val_str))
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
