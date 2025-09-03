"""Pydantic models for strategy configurations."""

from __future__ import annotations

from typing import List, Tuple

from pydantic import BaseModel, ConfigDict, model_validator


class _BaseStrikeConfig(BaseModel):
    """Common fields shared by multiple strategies."""

    use_ATR: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_xor_fields(self):
        """Ensure mutually exclusive strike parameters."""
        lp = getattr(self, "long_leg_distance_points", None)
        la = getattr(self, "long_leg_atr_multiple", None)
        if lp is not None and la is not None:
            raise ValueError(
                "long_leg_distance_points and long_leg_atr_multiple are mutually exclusive"
            )

        sp = getattr(self, "short_leg_width_points", None)
        sr = getattr(self, "short_leg_width_ratio", None)
        if sp is not None and sr is not None:
            raise ValueError(
                "short_leg_width_points and short_leg_width_ratio are mutually exclusive"
            )
        return self


class _BaseConfig(BaseModel):
    """Top-level strategy config wrapper."""

    min_risk_reward: float | None = None

    model_config = ConfigDict(extra="allow")


class ShortPutSpreadStrikeConfig(_BaseStrikeConfig):
    short_put_delta_range: Tuple[float, float]
    long_leg_distance_points: float | None = None
    long_leg_atr_multiple: float | None = None


class ShortPutSpreadConfig(_BaseConfig):
    strike_to_strategy_config: ShortPutSpreadStrikeConfig


class ShortCallSpreadStrikeConfig(_BaseStrikeConfig):
    short_call_delta_range: Tuple[float, float]
    long_leg_distance_points: float | None = None
    long_leg_atr_multiple: float | None = None


class ShortCallSpreadConfig(_BaseConfig):
    strike_to_strategy_config: ShortCallSpreadStrikeConfig


class NakedPutStrikeConfig(_BaseStrikeConfig):
    short_put_delta_range: Tuple[float, float]


class NakedPutConfig(_BaseConfig):
    strike_to_strategy_config: NakedPutStrikeConfig


class CalendarStrikeConfig(_BaseStrikeConfig):
    base_strikes_relative_to_spot: List[float]
    expiry_gap_min_days: int


class CalendarConfig(_BaseConfig):
    strike_to_strategy_config: CalendarStrikeConfig


class IronCondorStrikeConfig(_BaseStrikeConfig):
    short_call_delta_range: Tuple[float, float]
    short_put_delta_range: Tuple[float, float]
    wing_sigma_multiple: float | None = None
    short_leg_width_points: float | None = None
    short_leg_width_ratio: float | None = None


class IronCondorConfig(_BaseConfig):
    strike_to_strategy_config: IronCondorStrikeConfig


class AtmIronButterflyStrikeConfig(_BaseStrikeConfig):
    center_strike_relative_to_spot: List[float]
    wing_sigma_multiple: float | None = None


class AtmIronButterflyConfig(_BaseConfig):
    strike_to_strategy_config: AtmIronButterflyStrikeConfig


class RatioSpreadStrikeConfig(_BaseStrikeConfig):
    short_leg_delta_range: Tuple[float, float]
    long_leg_distance_points: float | None = None
    long_leg_atr_multiple: float | None = None


class RatioSpreadConfig(_BaseConfig):
    strike_to_strategy_config: RatioSpreadStrikeConfig


class BackspreadPutStrikeConfig(_BaseStrikeConfig):
    short_put_delta_range: Tuple[float, float]
    long_leg_distance_points: float | None = None
    long_leg_atr_multiple: float | None = None
    expiry_gap_min_days: int | None = None


class BackspreadPutConfig(_BaseConfig):
    strike_to_strategy_config: BackspreadPutStrikeConfig


CONFIG_MODELS = {
    "short_put_spread": ShortPutSpreadConfig,
    "short_call_spread": ShortCallSpreadConfig,
    "naked_put": NakedPutConfig,
    "calendar": CalendarConfig,
    "iron_condor": IronCondorConfig,
    "atm_iron_butterfly": AtmIronButterflyConfig,
    "ratio_spread": RatioSpreadConfig,
    "backspread_put": BackspreadPutConfig,
}

__all__ = ["CONFIG_MODELS"]
