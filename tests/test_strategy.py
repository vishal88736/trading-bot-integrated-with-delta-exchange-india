import pytest

from bot.indicators import atr, cmo, ema, windowed_average, windowed_atr
from bot.models import Candle
from bot.settings import Settings
from strategies.trend_signals import TrendSignals


def candles(prices, interval=300, start=36000):
    return [Candle(start + i * interval, p, p + 1, p - 1, p) for i, p in enumerate(prices)]


def test_indicator_known_values():
    assert ema([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    assert cmo([5, 5, 5], 2)[-1] == 0
    assert cmo([1, 2, 3], 2)[-1] == 100
    assert cmo([3, 2, 1], 2)[-1] == -100
    assert atr(candles([10, 14, 12]), 2)[-1] == 3.25


@pytest.mark.parametrize("side,mirror", [("buy", False), ("sell", True)])
def test_closed_candle_cloud_momentum_signals(side, mirror):
    prices, higher = [100, 104, 103, 102, 108], [80, 82, 84, 86, 88]
    if mirror:
        prices, higher = [200 - p for p in prices], [200 - p for p in higher]
    strategy = TrendSignals(
        Settings(fast_ema=2, slow_ema=3, cmo_length=2, atr_length=2, macro_sma=0)
    )
    bars, hbars = candles(prices), candles(higher, interval=3600, start=0)
    signal = strategy.evaluate(bars, hbars)
    assert signal is not None and signal.side == side
    future = Candle(bars[-1].time, 1, 2, 0.5, 1)
    assert strategy.evaluate(bars, hbars + [future]) == signal


def test_no_signal_before_warmup():
    assert TrendSignals(Settings()).evaluate(candles([100, 101]), []) is None


@pytest.mark.parametrize("length", [9, 21, 200, 500])
def test_year_fast_path_matches_live_rolling_ema(length):
    import math

    prices = [100 + i * 0.05 + 10 * math.sin(i / 7) for i in range(1600)]
    fast = windowed_average(prices, length, 2 / (length + 1))
    for i in (599, 600, 999, 1599):
        assert fast[i] == pytest.approx(ema(prices[max(0, i - 599) : i + 1], length)[-1], abs=1e-9)


def test_year_fast_path_matches_live_atr_including_gaps_at_window_start():
    import math

    prices = [100 + 5 * math.sin(i) for i in range(1600)]
    bars = candles(prices)
    fast = windowed_atr(bars, 14)
    for i in (599, 600, 999, 1599):
        assert fast[i] == pytest.approx(atr(bars[max(0, i - 599) : i + 1], 14)[-1], abs=1e-9)


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "live"},
        {"fast_ema": 30},
        {"contracts": 3},
        {"contracts": 5},
        {"timeframe": "1h", "higher_timeframe": "5m"},
        {"tp_atr": [2.0, 1.0, 3.0]},
        {"sl_atr": float("nan")},
        {"symbol": "../private"},
        {"poll_seconds": 0},
    ],
)
def test_invalid_configuration_rejected(values):
    with pytest.raises(ValueError):
        Settings(**values)
