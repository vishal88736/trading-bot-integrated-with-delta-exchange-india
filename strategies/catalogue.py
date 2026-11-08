"""Deterministic closed-candle strategy families, independent of article return claims."""

import bisect
from dataclasses import dataclass

from bot.indicators import prior_extreme, prior_mean, windowed_atr, windowed_average, windowed_rsi
from bot.models import RESOLUTIONS, Signal
from strategies.custom_strategy import CustomStrategy
from strategies.trend_signals import TrendSignals


def direction_allowed(settings, side):
    return settings.trade_direction == "both" or settings.trade_direction == (
        "long_only" if side == "buy" else "short_only"
    )


def parameter_keys(settings):
    common = {"atr_length", "sl_atr", "tp0", "tp1", "tp2"}
    if settings.sizing_mode == "risk_percent":
        common.add("risk_per_trade_percent")
    if settings.strategy == "custom_strategy":
        from bot.research import PARAMETERS

        return set(PARAMETERS)
    if settings.strategy == "trend_signals":
        return common | {"fast_ema", "slow_ema", "cmo_length", "cmo_threshold", "macro_sma"}
    if (
        settings.requires_higher_history()
        or settings.strategy == "ema_trend"
        or settings.strategy == "rsi_reversion"
        and settings.rsi_range_filter == "enabled"
    ):
        common |= {"trend_fast_period", "trend_slow_period"}
    if settings.strategy == "momentum_breakout":
        common |= {
            "breakout_lookback",
            "breakout_volume_length",
            "breakout_volume_multiplier",
            "breakout_buffer_atr",
        }
    elif settings.strategy == "rsi_reversion":
        common |= {"rsi_length", "rsi_oversold", "rsi_overbought", "rsi_exit_level"}
        if settings.rsi_range_filter == "enabled":
            common.add("rsi_max_ema_gap_atr")
    elif settings.strategy == "smc_price_action":
        common |= {"smc_swing_length", "smc_zone_expiry", "smc_body_ratio"}
        if settings.smc_zone_type != "fvg":
            common.add("smc_order_block_lookback")
        if settings.smc_zone_type != "order_block":
            common.add("smc_min_gap_bps")
    return common


class RuleStrategy:
    def __init__(self, settings):
        self.settings = settings

    def prepare(self, candles, higher):
        return PreparedRules(self.settings, candles, higher)

    def evaluate(self, candles, higher):
        return self.prepare(candles, higher).at(len(candles) - 1) if candles else None

    def exit_reason(self, side, candles, higher):
        return self.prepare(candles, higher).exit_at(len(candles) - 1, side) if candles else None


@dataclass
class Zone:
    setup: int
    side: str
    lower: float
    upper: float
    created: int
    kind: str
    origin: int


def smc_retests(settings, candles, highs, lows):
    """BOS/displacement first; zones become actionable on subsequent closed candles."""
    result = [None] * len(candles)
    zones, consumed, last_bos, used_zones = [], {}, {}, {}
    for i, candle in enumerate(candles):
        zones = [
            z
            for z in zones
            if i - z.created <= settings.smc_zone_expiry
            and not (candle.close < z.lower if z.side == "buy" else candle.close > z.upper)
        ]
        for zone in reversed(zones):
            touches = candle.low <= zone.upper and candle.high >= zone.lower
            rejection = (
                candle.close > zone.upper and candle.close > candle.open
                if zone.side == "buy"
                else candle.close < zone.lower and candle.close < candle.open
            )
            if touches and rejection and zone.setup not in consumed:
                result[i] = (zone.side, f"BOS + {zone.kind} first confirmed retest")
                consumed[zone.setup] = i
                used_zones[(zone.side, zone.kind, zone.origin)] = i
                break
        zones = [
            z
            for z in zones
            if z.setup not in consumed and (z.side, z.kind, z.origin) not in used_zones
        ]
        consumed = {
            key: value for key, value in consumed.items() if i - key <= settings.smc_zone_expiry + 3
        }
        used_zones = {
            key: value
            for key, value in used_zones.items()
            if i - key[2] <= settings.smc_zone_expiry + settings.smc_order_block_lookback + 3
        }
        body = (
            abs(candle.close - candle.open) / (candle.high - candle.low)
            if candle.high > candle.low
            else 0
        )
        if highs[i] is not None and body >= settings.smc_body_ratio:
            side = (
                "buy"
                if candle.close > highs[i] and candle.close > candle.open
                else "sell"
                if candle.close < lows[i] and candle.close < candle.open
                else None
            )
            if side:
                last_bos[side] = i
                if settings.smc_zone_type in ("order_block", "either"):
                    for j in range(i - 1, max(-1, i - settings.smc_order_block_lookback - 1), -1):
                        other = candles[j]
                        opposite = (
                            other.close < other.open if side == "buy" else other.close > other.open
                        )
                        if opposite:
                            identity = (side, "order block", j)
                            if identity not in used_zones and not any(
                                (z.side, z.kind, z.origin) == identity for z in zones
                            ):
                                zones.append(
                                    Zone(i, side, other.low, other.high, i, "order block", j)
                                )
                            break
        if i >= 2 and settings.smc_zone_type in ("fvg", "either"):
            for side, bottom, top in [
                ("buy", candles[i - 2].high, candle.low),
                ("sell", candle.high, candles[i - 2].low),
            ]:
                setup = last_bos.get(side)
                if (
                    setup is not None
                    and i - setup <= 2
                    and setup not in consumed
                    and top > bottom
                    and (top - bottom) / candle.close * 10000 >= settings.smc_min_gap_bps
                ):
                    zones.append(Zone(setup, side, bottom, top, i, "fair value gap", i))
        zones = zones[-16:]
    return result


class PreparedRules:
    def __init__(self, settings, candles, higher):
        self.s, self.candles = settings, candles
        self.close = [c.close for c in candles]
        self.volatility = windowed_atr(candles, settings.atr_length)
        self.fast = windowed_average(
            self.close, settings.trend_fast_period, 2 / (settings.trend_fast_period + 1)
        )
        self.slow = windowed_average(
            self.close, settings.trend_slow_period, 2 / (settings.trend_slow_period + 1)
        )
        self.htimes = [c.time + RESOLUTIONS[settings.higher_timeframe] for c in higher]
        self.hclose = [c.close for c in higher]
        self.hfast = windowed_average(
            self.hclose, settings.trend_fast_period, 2 / (settings.trend_fast_period + 1)
        )
        self.hslow = windowed_average(
            self.hclose, settings.trend_slow_period, 2 / (settings.trend_slow_period + 1)
        )
        length = (
            settings.smc_swing_length
            if settings.strategy == "smc_price_action"
            else settings.breakout_lookback
        )
        self.highs = prior_extreme([c.high for c in candles], length)
        self.lows = prior_extreme([c.low for c in candles], length, highest=False)
        self.volumes = prior_mean([c.volume for c in candles], settings.breakout_volume_length)
        self.rsi = windowed_rsi(self.close, settings.rsi_length)
        self.smc = (
            smc_retests(settings, candles, self.highs, self.lows)
            if settings.strategy == "smc_price_action"
            else []
        )

    def macro_allows(self, index, side):
        if not self.s.requires_higher_history():
            return True
        h = (
            bisect.bisect_right(
                self.htimes, self.candles[index].time + RESOLUTIONS[self.s.timeframe]
            )
            - 1
        )
        if h + 1 < self.s.trend_slow_period:
            return False
        return (
            self.hclose[h] > self.hfast[h] > self.hslow[h]
            if side == "buy"
            else self.hclose[h] < self.hfast[h] < self.hslow[h]
        )

    def at(self, index):
        s = self.s
        if index < 0 or index + 1 < s.warmup_requirements()[0]:
            return None
        candle, volatility = self.candles[index], self.volatility[index]
        if volatility is None or volatility <= 0:
            return None
        side, reason = None, ""
        if s.strategy == "momentum_breakout":
            average = self.volumes[index]
            if s.breakout_volume_multiplier and (
                average is None
                or average <= 0
                or candle.volume < average * s.breakout_volume_multiplier
            ):
                return None
            if candle.close > self.highs[index] + s.breakout_buffer_atr * volatility:
                side = "buy"
            elif candle.close < self.lows[index] - s.breakout_buffer_atr * volatility:
                side = "sell"
            reason = "Prior-range close breakout + configured volume/HTF confirmation"
        elif s.strategy == "ema_trend":
            a, b = self.fast[index - 1], self.slow[index - 1]
            if a is None or b is None:
                return None
            if a <= b and self.fast[index] > self.slow[index] and candle.close > self.fast[index]:
                side = "buy"
            elif a >= b and self.fast[index] < self.slow[index] and candle.close < self.fast[index]:
                side = "sell"
            reason = "EMA trend crossover + close confirmation"
        elif s.strategy == "rsi_reversion":
            previous, current = self.rsi[index - 1], self.rsi[index]
            if previous is None or current is None:
                return None
            if s.rsi_range_filter == "enabled" and (
                self.fast[index] is None
                or self.slow[index] is None
                or abs(self.fast[index] - self.slow[index]) / volatility > s.rsi_max_ema_gap_atr
            ):
                return None
            if s.rsi_entry_mode == "recovery":
                side = (
                    "buy"
                    if previous <= s.rsi_oversold < current < s.rsi_exit_level
                    else "sell"
                    if previous >= s.rsi_overbought > current > s.rsi_exit_level
                    else None
                )
            else:
                side = (
                    "buy"
                    if previous >= s.rsi_oversold > current
                    else "sell"
                    if previous <= s.rsi_overbought < current
                    else None
                )
            reason = f"RSI {s.rsi_entry_mode} + configured range/HTF filters"
        elif self.smc[index]:
            side, reason = self.smc[index]
        if side and direction_allowed(s, side) and self.macro_allows(index, side):
            return Signal(side, volatility, candle.time, reason)
        return None

    def exit_at(self, index, side):
        s = self.s
        if index < 0 or s.exit_mode == "ladder_only":
            return None
        if s.strategy == "rsi_reversion":
            value = self.rsi[index]
            if value is not None and (
                value >= s.rsi_exit_level if side == "buy" else value <= s.rsi_exit_level
            ):
                return "strategy_rsi_midline"
        elif s.strategy == "ema_trend":
            fast, slow = self.fast[index], self.slow[index]
            if (
                fast is not None
                and slow is not None
                and (fast < slow if side == "buy" else fast > slow)
            ):
                return "strategy_ema_reversal"
        elif self.highs[index] is not None:
            if (
                self.close[index] < self.lows[index]
                if side == "buy"
                else self.close[index] > self.highs[index]
            ):
                return (
                    "strategy_structure_break"
                    if s.strategy == "smc_price_action"
                    else "strategy_range_exit"
                )
        return None


STRATEGIES = {
    "trend_signals": TrendSignals,
    "custom_strategy": CustomStrategy,
    "momentum_breakout": RuleStrategy,
    "ema_trend": RuleStrategy,
    "smc_price_action": RuleStrategy,
    "rsi_reversion": RuleStrategy,
}


def strategy_type(name):
    return STRATEGIES[name]


def create_strategy(settings):
    return strategy_type(settings.strategy)(settings)
