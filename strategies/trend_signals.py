import bisect

from bot.indicators import cmo, windowed_atr, windowed_average
from bot.models import RESOLUTIONS, Candle, Signal
from bot.settings import Settings


class TrendSignals:
    """Independent implementation of the user's EMA/CMO/ATR specification."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(self, candles: list[Candle], higher: list[Candle]) -> Signal | None:
        if not candles:
            return None
        return self.prepare(candles, higher).at(len(candles) - 1)

    def prepare(self, candles, higher):
        return PreparedTrend(self.settings, candles, higher)


class PreparedTrend:
    def __init__(self, settings, candles, higher):
        self.s, self.candles, self.higher = settings, candles, higher
        self.close = [c.close for c in candles]
        self.hclose = [c.close for c in higher]
        self.htimes = [c.time + RESOLUTIONS[settings.higher_timeframe] for c in higher]
        self.fast = windowed_average(self.close, settings.fast_ema, 2 / (settings.fast_ema + 1))
        self.slow = windowed_average(self.close, settings.slow_ema, 2 / (settings.slow_ema + 1))
        self.momentum = cmo(self.close, settings.cmo_length)
        self.volatility = windowed_atr(candles, settings.atr_length)
        self.hfast = windowed_average(self.hclose, settings.fast_ema, 2 / (settings.fast_ema + 1))
        self.hslow = windowed_average(self.hclose, settings.slow_ema, 2 / (settings.slow_ema + 1))
        self.macro = []
        running = 0.0
        for i, price in enumerate(self.hclose):
            running += price
            if settings.macro_sma and i >= settings.macro_sma:
                running -= self.hclose[i - settings.macro_sma]
            self.macro.append(running / settings.macro_sma if settings.macro_sma else price)

    def at(self, index):
        s = self.s
        if index + 1 < max(s.slow_ema, s.cmo_length + 2, s.atr_length):
            return None
        hindex = (
            bisect.bisect_right(self.htimes, self.candles[index].time + RESOLUTIONS[s.timeframe])
            - 1
        )
        if hindex + 1 < max(s.slow_ema, s.macro_sma):
            return None
        close, fast, slow = self.close[index], self.fast[index], self.slow[index]
        hclose, hfast, hslow = self.hclose[hindex], self.hfast[hindex], self.hslow[hindex]
        long_macro = not s.macro_sma or hclose > self.macro[hindex]
        short_macro = not s.macro_sma or hclose < self.macro[hindex]
        previous, current = self.momentum[index - 1], self.momentum[index]
        volatility = self.volatility[index]
        if volatility is None or volatility <= 0:
            return None
        if (
            close > fast > slow
            and hclose > hfast > hslow
            and long_macro
            and previous <= s.cmo_threshold < current
        ):
            return Signal(
                "buy", volatility, self.candles[index].time, "EMA cloud + CMO cross + HTF trend"
            )
        if (
            close < fast < slow
            and hclose < hfast < hslow
            and short_macro
            and previous >= -s.cmo_threshold > current
        ):
            return Signal(
                "sell", volatility, self.candles[index].time, "EMA cloud + CMO cross + HTF trend"
            )
        return None
