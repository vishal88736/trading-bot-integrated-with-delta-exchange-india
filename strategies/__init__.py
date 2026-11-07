from typing import Protocol

from bot.models import Candle, Signal


class Strategy(Protocol):
    def evaluate(self, candles: list[Candle], higher: list[Candle]) -> Signal | None: ...
