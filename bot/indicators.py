"""Small, explicit indicator implementations; no opaque TA dependency."""

from bot.models import Candle


def ema(values: list[float], length: int) -> list[float | None]:
    result = [None] * len(values)
    if len(values) < length:
        return result
    value = sum(values[:length]) / length
    result[length - 1] = value
    alpha = 2 / (length + 1)
    for index in range(length, len(values)):
        value += alpha * (values[index] - value)
        result[index] = value
    return result


def cmo(values: list[float], length: int) -> list[float | None]:
    result = [None] * len(values)
    for index in range(length, len(values)):
        changes = [values[j] - values[j - 1] for j in range(index - length + 1, index + 1)]
        up = sum(max(change, 0) for change in changes)
        down = sum(max(-change, 0) for change in changes)
        result[index] = 100 * (up - down) / (up + down) if up + down else 0.0
    return result


def atr(candles: list[Candle], length: int) -> list[float | None]:
    result = [None] * len(candles)
    ranges = [
        max(c.high - c.low, abs(c.high - candles[i - 1].close), abs(c.low - candles[i - 1].close))
        if i
        else c.high - c.low
        for i, c in enumerate(candles)
    ]
    if len(ranges) < length:
        return result
    value = sum(ranges[:length]) / length
    result[length - 1] = value
    for index in range(length, len(ranges)):
        value = (value * (length - 1) + ranges[index]) / length
        result[index] = value
    return result
