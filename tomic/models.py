from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from tomic.logutils import logger

try:
    from ibapi.contract import Contract
except Exception:  # pragma: no cover - optional during testing
    Contract = object  # type: ignore


@dataclass
class OptionContract:
    """Basic option contract information."""

    symbol: str
    expiry: str
    strike: float
    right: str
    exchange: str = "SMART"
    currency: str = "USD"
    multiplier: str = "100"
    trading_class: Optional[str] = None
    primary_exchange: Optional[str] = None
    con_id: Optional[int] = None

    def to_ib(self) -> Contract:
        """Create an IB ``Contract`` object."""
        contract = Contract()
        contract.symbol = self.symbol
        contract.secType = "OPT"
        contract.exchange = self.exchange
        contract.primaryExchange = self.primary_exchange or ""
        contract.currency = self.currency
        contract.lastTradeDateOrContractMonth = self.expiry
        contract.strike = self.strike
        contract.right = self.right
        contract.multiplier = self.multiplier
        contract.conId = self.con_id or 0
        if not self.trading_class:
            logger.warning(
                f"⚠️ tradingClass ontbreekt voor {self.symbol} - fallback naar {self.symbol.upper()}"
            )
            contract.tradingClass = self.symbol.upper()
        else:
            contract.tradingClass = self.trading_class

        logger.debug(
            f"IB contract built: symbol={contract.symbol} "
            f"secType={contract.secType} exchange={contract.exchange} "
            f"primaryExchange={getattr(contract, 'primaryExchange', '')} currency={contract.currency} "
            f"expiry={contract.lastTradeDateOrContractMonth} strike={contract.strike} "
            f"right={contract.right} multiplier={contract.multiplier} "
            f"tradingClass={contract.tradingClass}"
        )

        return contract

    @classmethod
    def from_ib(cls, contract: Contract) -> "OptionContract":
        """Construct from an IB ``Contract`` object."""
        return cls(
            symbol=contract.symbol,
            expiry=contract.lastTradeDateOrContractMonth,
            strike=float(getattr(contract, "strike", 0.0)),
            right=contract.right,
            exchange=getattr(contract, "exchange", "SMART"),
            currency=getattr(contract, "currency", "USD"),
            multiplier=getattr(contract, "multiplier", "100"),
            trading_class=getattr(contract, "tradingClass", None),
            primary_exchange=getattr(
                contract,
                "primaryExchange",
                getattr(contract, "exchange", "SMART"),
            ),
            con_id=getattr(contract, "conId", None),
        )


@dataclass
class MarketMetrics:
    """Key market metrics for a symbol."""

    spot_price: Optional[float] = None
    hv30: Optional[float] = None
    atr14: Optional[float] = None
    vix: Optional[float] = None
    skew: Optional[float] = None
    term_m1_m2: Optional[float] = None
    term_m1_m3: Optional[float] = None
    iv_rank: Optional[float] = None
    implied_volatility: Optional[float] = None
    iv_percentile: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketMetrics":
        """Create ``MarketMetrics`` from a mapping."""
        return cls(
            spot_price=data.get("spot_price"),
            hv30=data.get("hv30"),
            atr14=data.get("atr14"),
            vix=data.get("vix"),
            skew=data.get("skew"),
            term_m1_m2=data.get("term_m1_m2"),
            term_m1_m3=data.get("term_m1_m3"),
            iv_rank=data.get("iv_rank"),
            implied_volatility=data.get("implied_volatility"),
            iv_percentile=data.get("iv_percentile"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return this record as a plain dictionary."""
        return {
            "spot_price": self.spot_price,
            "hv30": self.hv30,
            "atr14": self.atr14,
            "vix": self.vix,
            "skew": self.skew,
            "term_m1_m2": self.term_m1_m2,
            "term_m1_m3": self.term_m1_m3,
            "iv_rank": self.iv_rank,
            "implied_volatility": self.implied_volatility,
            "iv_percentile": self.iv_percentile,
        }


@dataclass
class OptionMetrics:
    """Basic metrics for a single option contract."""

    spot_price: Optional[float]
    volume: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OptionMetrics":
        return cls(
            spot_price=data.get("spot_price"),
            volume=int(data.get("volume", 0) or 0),
        )

