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
    up = down = 0.0
    for index in range(length, len(values)):
        if index == length or index % 1024 == 0:
            changes = [values[j] - values[j - 1] for j in range(index - length + 1, index + 1)]
            up = sum(max(change, 0) for change in changes)
            down = sum(max(-change, 0) for change in changes)
        else:
            old = values[index - length] - values[index - length - 1]
            new = values[index] - values[index - 1]
            up = max(0.0, up + max(new, 0) - max(old, 0))
            down = max(0.0, down + max(-new, 0) - max(-old, 0))
        result[index] = 100 * (up - down) / (up + down) if up + down else 0.0
    return result


def windowed_average(values, length, alpha, window=600, adjustments=None):
    """O(n) seeded EMA/RMA for exactly the live runner's rolling history window.

    A global exponential average is corrected by the difference between its
    value at the window seed and the window's own SMA seed. This avoids replaying
    600 indicator bars for every candle in a year-long backtest.
    """
    result = [None] * len(values)
    if len(values) < length:
        return result
    global_values = [None] * len(values)
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    running = sum(values[:length]) / length
    for index in range(length - 1, len(values)):
        if index >= length:
            running += alpha * (values[index] - running)
        global_values[index] = running
        start = max(0, index - window + 1)
        seed_index = start + length - 1
        seed = (prefix[seed_index + 1] - prefix[start]) / length
        if adjustments:
            seed += adjustments[start] / length
        result[index] = running + (seed - global_values[seed_index]) * (1 - alpha) ** (
            index - seed_index
        )
    return result


def windowed_atr(candles, length, window=600):
    ranges = [
        max(c.high - c.low, abs(c.high - candles[i - 1].close), abs(c.low - candles[i - 1].close))
        if i
        else c.high - c.low
        for i, c in enumerate(candles)
    ]
    # The first candle in a live window has no prior close inside that window.
    adjustments = [c.high - c.low - ranges[i] for i, c in enumerate(candles)]
    return windowed_average(ranges, length, 1 / length, window, adjustments)


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
