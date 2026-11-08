"""Small, explicit indicator implementations; no opaque TA dependency."""

from collections import deque
from math import fsum

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
    gains, losses = deque(maxlen=length), deque(maxlen=length)
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if index < length:
            continue
        # A bounded accurate sum avoids residual +/-100 signals on flat prices.
        up, down = fsum(gains), fsum(losses)
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


def prior_extreme(values, length, highest=True):
    """Highest/lowest of the prior N bars, excluding the decision candle."""
    result, queue = [None] * len(values), deque()
    for index, value in enumerate(values):
        while queue and queue[0] < index - length:
            queue.popleft()
        if index >= length:
            result[index] = values[queue[0]]
        while queue and (values[queue[-1]] <= value if highest else values[queue[-1]] >= value):
            queue.pop()
        queue.append(index)
    return result


def prior_mean(values, length):
    result, queue = [None] * len(values), deque(maxlen=length)
    for index, value in enumerate(values):
        if len(queue) == length:
            result[index] = fsum(queue) / length
        queue.append(value)
    return result


def windowed_rsi(values, length):
    """Wilder RSI using exactly the runner's 600-price / 599-change window."""
    result = [None] * len(values)
    changes = [b - a for a, b in zip(values, values[1:], strict=False)]
    gains = windowed_average([max(v, 0) for v in changes], length, 1 / length, window=599)
    losses = windowed_average([max(-v, 0) for v in changes], length, 1 / length, window=599)
    magnitudes = [abs(v) for v in changes]
    flat = prior_extreme(magnitudes, 598)
    for index in range(length, len(values)):
        up, down = max(0, gains[index - 1]), max(0, losses[index - 1])
        entirely_flat = index >= 599 and flat[index - 1] == 0 and magnitudes[index - 1] == 0
        result[index] = 50.0 if entirely_flat or not up + down else 100 * up / (up + down)
    return result
