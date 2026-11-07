from bot.indicators import atr, cmo, ema
from bot.models import Candle, RESOLUTIONS, Signal
from bot.settings import Settings


class TrendSignals:
    """Independent implementation of the user's EMA/CMO/ATR specification."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(self, candles: list[Candle], higher: list[Candle]) -> Signal | None:
        s = self.settings
        if len(candles) < max(s.slow_ema, s.cmo_length + 2, s.atr_length):
            return None
        close_time = candles[-1].time + RESOLUTIONS[s.timeframe]
        higher = [c for c in higher if c.time + RESOLUTIONS[s.higher_timeframe] <= close_time]
        if len(higher) < max(s.slow_ema, s.macro_sma):
            return None
        closes = [c.close for c in candles]
        fast, slow = ema(closes, s.fast_ema)[-1], ema(closes, s.slow_ema)[-1]
        momentum = cmo(closes, s.cmo_length)
        volatility = atr(candles, s.atr_length)[-1]
        hcloses = [c.close for c in higher]
        hfast, hslow = ema(hcloses, s.fast_ema)[-1], ema(hcloses, s.slow_ema)[-1]
        macro = sum(hcloses[-s.macro_sma :]) / s.macro_sma if s.macro_sma else hcloses[-1]
        long_macro = not s.macro_sma or hcloses[-1] > macro
        short_macro = not s.macro_sma or hcloses[-1] < macro
        previous, current = momentum[-2:]
        if volatility is None or volatility <= 0:
            return None
        if (
            closes[-1] > fast > slow
            and hcloses[-1] > hfast > hslow
            and long_macro
            and previous <= s.cmo_threshold < current
        ):
            return Signal("buy", volatility, candles[-1].time, "EMA cloud + CMO cross + HTF trend")
        if (
            closes[-1] < fast < slow
            and hcloses[-1] < hfast < hslow
            and short_macro
            and previous >= -s.cmo_threshold > current
        ):
            return Signal("sell", volatility, candles[-1].time, "EMA cloud + CMO cross + HTF trend")
        return None
