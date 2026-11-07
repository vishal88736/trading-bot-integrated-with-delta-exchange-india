from bot.models import Candle, Signal
from bot.settings import Settings


class CustomStrategy:
    """Replace evaluate() with your rules; the engine still manages exits and risk."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(self, candles: list[Candle], higher: list[Candle]) -> Signal | None:
        # Inputs contain only closed candles, oldest first. No signal by default.
        # Example return: Signal("buy", atr_value, candles[-1].time, "my entry rule")
        return None
