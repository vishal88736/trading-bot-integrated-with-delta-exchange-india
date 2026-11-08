import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot.models import RESOLUTIONS


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    mode: Literal["paper", "demo"] = "paper"
    symbol: str = "BTCUSD"
    timeframe: str = "5m"
    higher_timeframe: str = "1h"
    strategy: Literal[
        "trend_signals",
        "custom_strategy",
        "momentum_breakout",
        "ema_trend",
        "smc_price_action",
        "rsi_reversion",
    ] = "trend_signals"
    fast_ema: int = Field(default=9, ge=2, le=200)
    slow_ema: int = Field(default=21, ge=3, le=500)
    cmo_length: int = Field(default=14, ge=2, le=200)
    cmo_threshold: float = Field(default=0.0, ge=0, le=90)
    atr_length: int = Field(default=14, ge=2, le=200)
    macro_sma: int = Field(default=200, ge=0, le=500)
    sl_atr: float = Field(default=2.0, gt=0, le=20)
    tp_atr: list[float] = Field(default_factory=lambda: [1.0, 2.0, 4.0], min_length=3, max_length=3)
    contracts: int = Field(default=4, ge=4, le=10000)
    leverage: int = Field(default=1, ge=1, le=50)
    max_contracts: int = Field(default=4, ge=4, le=10000)
    max_notional_quote: float = Field(default=1000.0, gt=0, le=1000000)
    max_loss_quote: float = Field(default=50.0, gt=0, le=100000)
    max_entry_slippage_bps: float = Field(default=30.0, gt=0, le=500)
    paper_fee_bps: float = Field(default=5.0, ge=0, le=100)
    poll_seconds: int = Field(default=5, ge=2, le=60)
    trade_direction: Literal["both", "long_only", "short_only"] = "both"
    htf_filter: Literal["enabled", "disabled"] = "enabled"
    exit_mode: Literal["strategy_or_ladder", "ladder_only"] = "strategy_or_ladder"
    trend_fast_period: int = Field(default=50, ge=2, le=200)
    trend_slow_period: int = Field(default=200, ge=3, le=500)
    breakout_lookback: int = Field(default=20, ge=2, le=200)
    breakout_volume_length: int = Field(default=20, ge=2, le=200)
    breakout_volume_multiplier: float = Field(default=1.5, ge=0, le=20)
    breakout_buffer_atr: float = Field(default=0.0, ge=0, le=5)
    rsi_length: int = Field(default=14, ge=2, le=200)
    rsi_oversold: float = Field(default=30.0, gt=0, lt=50)
    rsi_overbought: float = Field(default=70.0, gt=50, lt=100)
    rsi_exit_level: float = Field(default=50.0, gt=0, lt=100)
    rsi_entry_mode: Literal["recovery", "extreme_cross"] = "recovery"
    rsi_range_filter: Literal["enabled", "disabled"] = "enabled"
    rsi_max_ema_gap_atr: float = Field(default=2.0, gt=0, le=20)
    smc_swing_length: int = Field(default=20, ge=2, le=100)
    smc_order_block_lookback: int = Field(default=20, ge=2, le=100)
    smc_zone_expiry: int = Field(default=60, ge=2, le=200)
    smc_zone_type: Literal["fvg", "order_block", "either"] = "fvg"
    smc_body_ratio: float = Field(default=0.6, gt=0, le=1)
    smc_min_gap_bps: float = Field(default=0.0, ge=0, le=1000)
    sizing_mode: Literal["fixed_contracts", "risk_percent"] = "fixed_contracts"
    risk_per_trade_percent: float = Field(default=1.0, ge=0.1, le=2.0)
    paper_capital_quote: float = Field(default=10000.0, gt=0, le=1000000000)

    @model_validator(mode="after")
    def validate_rules(self):
        if not re.fullmatch(r"[A-Z0-9_-]{3,60}", self.symbol):
            raise ValueError("Use an exchange symbol such as BTCUSD or ETHUSD")
        if self.timeframe not in RESOLUTIONS or self.higher_timeframe not in RESOLUTIONS:
            raise ValueError("Unsupported candle timeframe")
        if self.requires_higher_history() and (
            RESOLUTIONS[self.higher_timeframe] <= RESOLUTIONS[self.timeframe]
        ):
            raise ValueError("Higher timeframe must be larger than signal timeframe")
        if self.fast_ema >= self.slow_ema:
            raise ValueError("Fast EMA must be shorter than slow EMA")
        if self.trend_fast_period >= self.trend_slow_period:
            raise ValueError("Trend fast EMA must be shorter than trend slow EMA")
        if not self.rsi_oversold < self.rsi_exit_level < self.rsi_overbought:
            raise ValueError("RSI levels must satisfy oversold < exit < overbought")
        if not 0 < self.tp_atr[0] < self.tp_atr[1] < self.tp_atr[2] <= 50:
            raise ValueError("Targets must be positive, increasing ATR multiples (maximum 50)")
        if self.sizing_mode == "fixed_contracts" and self.contracts > self.max_contracts:
            raise ValueError("Trade contracts exceed the position limit")
        return self

    def signature(self):
        # New defaults must not invalidate an open trade saved by an older release.
        fields = list(type(self).model_fields)
        added = fields[fields.index("poll_seconds") + 1 :]
        unchanged_defaults = {
            key for key in added if getattr(self, key) == type(self).model_fields[key].default
        }
        return hashlib.sha256(
            self.model_dump_json(exclude=unchanged_defaults).encode()
        ).hexdigest()[:16]

    def requires_higher_history(self):
        return self.strategy in ("trend_signals", "custom_strategy") or self.htf_filter == "enabled"

    def warmup_requirements(self):
        if self.strategy in ("trend_signals", "custom_strategy"):
            return (
                max(self.slow_ema, self.cmo_length + 2, self.atr_length),
                max(self.slow_ema, self.macro_sma),
            )
        lower = self.atr_length + 1
        if self.strategy == "ema_trend":
            lower = max(lower, self.trend_slow_period + 1)
        elif self.strategy == "momentum_breakout":
            lower = max(lower, self.breakout_lookback + 1, self.breakout_volume_length + 1)
        elif self.strategy == "rsi_reversion":
            lower = max(
                lower,
                self.rsi_length + 2,
                self.trend_slow_period if self.rsi_range_filter == "enabled" else 0,
            )
        else:
            lower = max(lower, self.smc_swing_length + 3)
        return lower, self.trend_slow_period if self.requires_higher_history() else 0


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_settings(root: Path):
    path = root / "settings.json"
    return Settings.model_validate_json(path.read_text()) if path.exists() else Settings()
