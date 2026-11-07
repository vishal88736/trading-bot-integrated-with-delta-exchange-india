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
    strategy: Literal["trend_signals", "custom_strategy"] = "trend_signals"
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

    @model_validator(mode="after")
    def validate_rules(self):
        if not re.fullmatch(r"[A-Z0-9_-]{3,60}", self.symbol):
            raise ValueError("Use an exchange symbol such as BTCUSD or ETHUSD")
        if self.timeframe not in RESOLUTIONS or self.higher_timeframe not in RESOLUTIONS:
            raise ValueError("Unsupported candle timeframe")
        if RESOLUTIONS[self.higher_timeframe] <= RESOLUTIONS[self.timeframe]:
            raise ValueError("Higher timeframe must be larger than signal timeframe")
        if self.fast_ema >= self.slow_ema:
            raise ValueError("Fast EMA must be shorter than slow EMA")
        if not 0 < self.tp_atr[0] < self.tp_atr[1] < self.tp_atr[2] <= 50:
            raise ValueError("Targets must be positive, increasing ATR multiples (maximum 50)")
        if self.contracts > self.max_contracts:
            raise ValueError("Trade contracts exceed the position limit")
        return self

    def signature(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


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
