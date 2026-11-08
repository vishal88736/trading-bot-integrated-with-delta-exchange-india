import hashlib
import json
import math
from types import SimpleNamespace

import pytest

from bot.backtest import BacktestRequest, Backtests, simulate
from bot.engine import Engine
from bot.indicators import prior_extreme, windowed_rsi
from bot.models import Candle, Position, Signal, State
from bot.risk import entry_size, trade_plan
from bot.settings import Settings, atomic_json, read_settings
from bot.strategy_checks import lookahead_check
from clients.delta import DeltaError
from strategies.catalogue import STRATEGIES, create_strategy

BASE = 1700006400
PRODUCT = {
    "id": 84,
    "contract_value": "1",
    "tick_size": "0.1",
    "quoting_asset": {"symbol": "USD"},
    "settling_asset": {"symbol": "USD"},
}
NEW = ["momentum_breakout", "ema_trend", "smc_price_action", "rsi_reversion"]


def settings(kind, **changes):
    return Settings(
        strategy=kind,
        htf_filter="disabled",
        atr_length=2,
        trend_fast_period=2,
        trend_slow_period=3,
        **changes,
    )


def bars(prices):
    return [
        Candle(BASE + i * 300, price, price + 1, price - 1, price, 10)
        for i, price in enumerate(prices)
    ]


def mirror(candles):
    return [
        Candle(c.time, 200 - c.open, 200 - c.low, 200 - c.high, 200 - c.close, c.volume)
        for c in candles
    ]


def breakout_bars():
    result = [Candle(BASE + i * 300, 95, 100, 90, 95, 10) for i in range(5)]
    return result + [Candle(BASE + 1500, 95, 110, 94, 108, 30)]


def smc_bars(order_block=False):
    result = [Candle(BASE + i * 300, 95, 100, 90, 95) for i in range(5)]
    rows = [
        (99, 100, 94, 95),
        (95, 106, 94, 105),
        (105, 109, 103, 108),
        (100, 102, 96, 101) if order_block else (104, 106, 101, 105),
    ]
    return result + [Candle(BASE + (5 + i) * 300, *row) for i, row in enumerate(rows)]


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_breakout_requires_a_prior_range_close_and_volume(side):
    candles = breakout_bars()
    if side == "sell":
        candles = mirror(candles)
    strategy = create_strategy(
        settings("momentum_breakout", breakout_lookback=3, breakout_volume_length=3)
    )
    signal = strategy.evaluate(candles, [])
    assert signal and signal.side == side and signal.time == candles[-1].time
    last = candles[-1]
    low_volume = candles[:-1] + [Candle(last.time, last.open, last.high, last.low, last.close, 2)]
    assert strategy.evaluate(low_volume, []) is None
    inside = 99 if side == "buy" else 101
    wick = candles[:-1] + [Candle(last.time, last.open, last.high, last.low, inside, 30)]
    assert strategy.evaluate(wick, []) is None


def test_higher_timeframe_filter_excludes_the_unclosed_bar():
    s = settings("momentum_breakout", breakout_lookback=3, breakout_volume_length=3)
    s = Settings.model_validate({**s.model_dump(), "htf_filter": "enabled"})
    candles = breakout_bars()
    higher = [Candle(BASE - (3 - i) * 3600, p, p + 1, p - 1, p) for i, p in enumerate([80, 85, 90])]
    strategy = create_strategy(s)
    original = strategy.evaluate(candles, higher)
    assert original and original.side == "buy"
    future = Candle(candles[-1].time, 10, 11, 9, 10)
    assert strategy.evaluate(candles, higher + [future]) == original
    down = [Candle(BASE - (3 - i) * 3600, p, p + 1, p - 1, p) for i, p in enumerate([90, 85, 80])]
    assert strategy.evaluate(candles, down) is None


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_ema_crossover_and_opposing_regime_exit(side):
    candles = bars([100, 100, 100, 90, 80, 70, 120])
    if side == "sell":
        candles = mirror(candles)
    strategy = create_strategy(settings("ema_trend"))
    signal = strategy.evaluate(candles, [])
    assert signal and signal.side == side
    opposite = bars([100, 100, 100, 90, 80, 70])
    if side == "sell":
        opposite = mirror(opposite)
    assert strategy.exit_reason(side, opposite, []) == "strategy_ema_reversal"


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_rsi_recovery_and_midline_exit(side):
    candles = bars([100, 99, 98, 97, 96, 95, 94, 94.6])
    if side == "sell":
        candles = mirror(candles)
    strategy = create_strategy(settings("rsi_reversion", rsi_length=2, rsi_range_filter="disabled"))
    signal = strategy.evaluate(candles, [])
    assert signal and signal.side == side
    price = 98 if side == "buy" else 102
    recovered = candles + [Candle(candles[-1].time + 300, price, price + 1, price - 1, price)]
    assert strategy.exit_reason(side, recovered, []) == "strategy_rsi_midline"
    # A jump all the way past the mean is not an oversold recovery entry.
    assert strategy.evaluate(recovered, []) is None


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_rsi_extreme_cross_entry_mode(side):
    candles = bars([100, 101, 102, 103, 104, 105, 106, 103])
    if side == "sell":
        candles = mirror(candles)
    strategy = create_strategy(
        settings(
            "rsi_reversion",
            rsi_length=2,
            rsi_range_filter="disabled",
            rsi_entry_mode="extreme_cross",
        )
    )
    signal = strategy.evaluate(candles, [])
    assert signal and signal.side == side


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("zone", ["fvg", "order_block"])
def test_smc_uses_confirmed_bos_then_a_later_zone_rejection(side, zone):
    candles = smc_bars(order_block=zone == "order_block")
    if side == "sell":
        candles = mirror(candles)
    strategy = create_strategy(
        settings(
            "smc_price_action",
            smc_swing_length=2,
            smc_order_block_lookback=3,
            smc_zone_expiry=5,
            smc_zone_type=zone,
            smc_body_ratio=0.5,
        )
    )
    prepared = strategy.prepare(candles, [])
    assert prepared.at(6) is None and prepared.at(7) is None
    signal = prepared.at(8)
    assert signal and signal.side == side
    again = candles + [
        Candle(
            candles[-1].time + 300,
            candles[-1].open,
            candles[-1].high,
            candles[-1].low,
            candles[-1].close,
        )
    ]
    assert strategy.evaluate(again, []) is None


def test_smc_close_invalidated_or_expired_zones_do_not_signal():
    candles = smc_bars()
    candles[-1] = Candle(candles[-1].time, 103, 104, 97, 99)
    strategy = create_strategy(
        settings("smc_price_action", smc_swing_length=2, smc_body_ratio=0.5, smc_zone_expiry=2)
    )
    assert strategy.evaluate(candles, []) is None
    original = smc_bars()[:-1]
    last = original[-1].time
    original += [Candle(last + i * 300, 105, 106, 104, 105) for i in range(1, 5)]
    original += [Candle(last + 1500, 104, 106, 101, 105)]
    assert strategy.evaluate(original, []) is None


def test_known_rsi_values_and_flat_window_reset():
    assert windowed_rsi([1, 2, 1, 2], 2)[2:] == [50.0, 75.0]
    assert windowed_rsi([3, 2, 1], 2)[-1] == 0
    assert windowed_rsi([1, 2, 3], 2)[-1] == 100
    assert windowed_rsi([1, 1, 1], 2)[-1] == 50
    assert windowed_rsi([1e7, 1, 1e6] + [100] * 650, 14)[-10:] == [50] * 10
    assert prior_extreme([1, 2, 10, 3], 2) == [None, None, 2, 10]


@pytest.mark.parametrize("kind", NEW)
def test_prepared_entries_and_exits_match_streaming_600_candle_windows(kind):
    prices = [100 + 0.005 * i + 8 * math.sin(i / 13) + 2 * math.sin(i / 3) for i in range(1600)]
    candles = [
        Candle(
            BASE + i * 300,
            prices[max(0, i - 1)],
            max(p, prices[max(0, i - 1)]) + 1,
            min(p, prices[max(0, i - 1)]) - 1,
            p,
            100 + 80 * math.sin(i) ** 2,
        )
        for i, p in enumerate(prices)
    ]
    s = settings(kind)
    prepared = create_strategy(s).prepare(candles, [])
    for i in [599, 600, 999, 1599]:
        streamed = create_strategy(s)
        window = candles[max(0, i - 599) : i + 1]
        a, b = prepared.at(i), streamed.evaluate(window, [])
        assert (a is None) == (b is None)
        if a:
            assert a.side == b.side and a.time == b.time
            assert a.atr == pytest.approx(b.atr, abs=1e-8)
        for side in ["buy", "sell"]:
            assert prepared.exit_at(i, side) == streamed.exit_reason(side, window, [])


def test_risk_budget_floors_contracts_and_preserves_the_ladder():
    s = Settings(sizing_mode="risk_percent", max_contracts=100, max_notional_quote=1000000.0)
    signal = Signal("buy", 10, BASE, "fixture")
    sized = entry_size(s, signal, 100, ".1", 1, 10000, 10000, 5)
    assert sized["quantity"] == 4
    assert sized["estimated_stop_risk_quote"] <= sized["budget_quote"] == 100
    assert trade_plan(s, signal, 100, ".1", sized["quantity"]).quantities == [2, 1, 1]
    assert entry_size(s, signal, 100, ".1", 1, 10, 10, 5)["quantity"] == 0
    capped = Settings(**{**s.model_dump(), "max_contracts": 4})
    assert entry_size(capped, signal, 100, ".1", 1, 100000, 100000, 5)["quantity"] == 4


def test_short_risk_reserves_costs_at_the_higher_stop_price():
    s = Settings(sizing_mode="risk_percent", max_contracts=10000, max_notional_quote=1000000.0)
    sized = entry_size(s, Signal("sell", 20, BASE, "fixture"), 100, ".1", 1, 1000000, 1000000, 100)
    # Stop 140; entry/exit slippage reserve .72; fees at 100.3 and 140.42.
    assert sized["estimated_stop_risk_quote"] / sized["quantity"] == pytest.approx(43.2272)
    assert sized["estimated_stop_risk_quote"] <= sized["budget_quote"]


class Broker:
    def __init__(self):
        self.orders, self.stops = [], []
        self.wallet = [{"asset_symbol": "USD", "balance": 10000, "available_balance": 10000}]

    def product(self, symbol):
        return dict(PRODUCT)

    def balances(self):
        return self.wallet

    def set_leverage(self, *args):
        pass

    def market_order(self, product_id, side, size, client_id, stop=None):
        self.orders.append((side, size))
        return {
            "average_fill_price": 100,
            "paid_commission": 0,
            "size": size,
            "unfilled_size": 0,
            "state": "closed",
            "side": side,
            "product_id": product_id,
            "client_order_id": client_id,
            "reduce_only": stop is None,
        }

    def protect(self, product_id, stop):
        self.stops.append(stop)


def test_demo_risk_sizing_uses_confirmed_quote_wallet_before_any_write(tmp_path):
    client = Broker()
    s = Settings(
        mode="demo",
        sizing_mode="risk_percent",
        max_contracts=100,
        max_notional_quote=1000000.0,
        paper_fee_bps=0.0,
    )
    engine = Engine(s, client, tmp_path)
    engine.open(Signal("buy", 10, BASE, "fixture"), 100)
    assert client.orders == [("buy", 4)]
    assert engine.state.events[-1]["sizing"]["budget_quote"] == 100
    second = Broker()
    second.wallet = [{"asset_symbol": "BTC", "balance": 100, "available_balance": 100}]
    other = Engine(s, second, tmp_path / "other")
    with pytest.raises(DeltaError, match="wallet balance"):
        other.open(Signal("buy", 10, BASE, "fixture"), 100)
    assert not second.orders and not other.state.pending


def test_paper_native_exit_uses_one_fresh_close_and_does_not_reenter(tmp_path, monkeypatch):
    broker = Broker()
    engine = Engine(settings("ema_trend", paper_fee_bps=0.0), broker, tmp_path)
    engine.open(Signal("buy", 10, BASE, "fixture"), 100)
    candles = bars([100] * 8)
    broker.ticker = lambda symbol: 105
    broker.candles = lambda *args, **kwargs: candles
    monkeypatch.setattr("bot.engine.time.time", lambda: candles[-1].time + 301)

    def must_not_enter(*args):
        raise AssertionError("A strategy exit must not reopen on the same candle")

    engine.strategy = SimpleNamespace(
        exit_reason=lambda *args: "strategy_ema_reversal", evaluate=must_not_enter
    )
    engine.step()
    assert engine.state.position is None
    assert engine.state.events[-1]["kind"] == "strategy_exit"
    assert not broker.orders and not broker.stops


def test_strategy_exit_replay_fills_at_next_open_and_can_be_disabled():
    start = BASE + 1800
    warmup = bars([100] * 6)
    rows = [(100, 101, 99, 100), (100, 105, 95, 101), (102, 200, 1, 150), (100, 101, 99, 100)]
    candles = warmup + [Candle(start + i * 300, *row) for i, row in enumerate(rows)]

    class Rules:
        def evaluate(self, candles, higher):
            if candles[-1].time == start:
                return Signal("buy", 10, start, "fixture")

        def exit_reason(self, side, candles, higher):
            return "strategy_test" if candles[-1].time == start + 300 else None

    s = settings("momentum_breakout", breakout_lookback=2, breakout_volume_length=2)
    request = BacktestRequest(
        settings=s, start=start, end=start + 1200, fee_bps=0.0, slippage_bps=0.0
    )
    result = simulate(request, candles, [], PRODUCT, Rules())
    leg = result["trades"][0]["exits"][0]
    assert leg["price"] == 102 and leg["time"] == start + 600
    assert leg["reason"] == "strategy_test"
    result = simulate(
        request.model_copy(
            update={"settings": Settings(**{**s.model_dump(), "exit_mode": "ladder_only"})}
        ),
        candles,
        [],
        PRODUCT,
        Rules(),
    )
    assert result["trades"][0]["exits"][0]["reason"] == "stop"


def test_replay_risk_sizing_records_actual_quantity_and_skips_unfunded_ladders():
    start = BASE + 1800
    candles = bars([100] * 10)

    class Entry:
        def evaluate(self, candles, higher):
            return Signal("buy", 10, start, "fixture") if candles[-1].time == start else None

    s = settings(
        "momentum_breakout",
        breakout_lookback=2,
        breakout_volume_length=2,
        sizing_mode="risk_percent",
        max_contracts=100,
        max_notional_quote=1000000.0,
    )
    request = BacktestRequest(settings=s, start=start, end=start + 1200, slippage_bps=0.0)
    result = simulate(request, candles, [], PRODUCT, Entry())
    assert result["trades"][0]["quantity"] == 4
    assert result["trades"][0]["sizing"]["budget_quote"] == 100
    result = simulate(
        request.model_copy(update={"initial_balance": 100.0}), candles, [], PRODUCT, Entry()
    )
    assert not result["trades"] and result["rejected_entries"]["risk_budget_or_minimum_size"] == 1


def test_daily_strategy_without_htf_fetches_only_one_history_dataset(tmp_path):
    class History:
        def __init__(self):
            self.calls = []

        def product(self, symbol):
            return PRODUCT

        def historical_candles(self, symbol, resolution, start, end, progress=None):
            self.calls.append(resolution)
            return [Candle(t, 100, 101, 99, 100) for t in range(start, end, 86400)]

        def close(self):
            pass

    client = History()
    s = Settings(strategy="ema_trend", timeframe="1d", higher_timeframe="1d", htf_filter="disabled")
    start = BASE // 86400 * 86400
    request = BacktestRequest(settings=s, start=start, end=start + 5 * 86400)
    runner = Backtests(factory=lambda: client, artifact_root=tmp_path)
    runner._run(request)
    assert runner.snapshot()["status"] == "completed"
    assert client.calls == ["1d"]


def test_default_fields_preserve_legacy_position_signatures(tmp_path):
    s = Settings()
    keys = list(Settings.model_fields)
    original = {key: getattr(s, key) for key in keys[: keys.index("poll_seconds") + 1]}
    signature = hashlib.sha256(json.dumps(original, separators=(",", ":")).encode()).hexdigest()[
        :16
    ]
    assert s.signature() == signature
    atomic_json(tmp_path / "settings.json", original)
    state = State(
        signature=signature,
        last_candle=123,
        position=Position("buy", 100, 80, [110, 120, 140], [2, 1, 1], 4),
    )
    atomic_json(tmp_path / "paper-BTCUSD.json", state.to_dict())
    engine = Engine(read_settings(tmp_path), Broker(), tmp_path)
    assert engine.state.last_candle == 123 and engine.state.position == state.position


def test_grid_rejects_unused_strategy_parameters_and_daily_can_disable_htf():
    s = settings("ema_trend")
    with pytest.raises(ValueError, match="unused"):
        BacktestRequest(
            settings=s,
            start=BASE,
            end=BASE + 86400,
            research={"kind": "parameters", "grid": {"cmo_length": [14]}},
        )
    daily = Settings(
        strategy="ema_trend", timeframe="1d", higher_timeframe="1d", htf_filter="disabled"
    )
    assert not daily.requires_higher_history()
    assert daily.warmup_requirements()[1] == 0
    assert set(STRATEGIES) >= set(NEW)


def test_lookahead_check_also_detects_future_dependent_strategy_exits():
    class Leaky:
        def __init__(self, settings):
            pass

        def prepare(self, candles, higher):
            return SimpleNamespace(
                at=lambda index: None,
                exit_at=lambda index, side: "future" if index < len(candles) - 1 else None,
            )

        def evaluate(self, candles, higher):
            return None

        def exit_reason(self, side, candles, higher):
            return None

    request = BacktestRequest(settings=settings("ema_trend"), start=BASE, end=BASE + 3000)
    result = lookahead_check(request, bars([100] * 10), [], {"trades": []}, factory=Leaky)
    assert result["status"] == "failed"
