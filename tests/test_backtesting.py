import copy
import math
from pathlib import Path

import pytest
from test_backtest_integrity import fixture_run

from bot.backtest import BacktestRequest, simulate
from bot.backtesting_checks import broker_replay, check_replay, close_enough, ledger, load_backend
from bot.backtrader_checks import START, dashboard_run, scenarios
from bot.models import Candle, Signal
from bot.reference_checks import REFERENCES, _validate, validate, verify_checkout
from bot.settings import Settings


@pytest.fixture(scope="module")
def reference():
    pytest.importorskip("bokeh")
    path = Path(__file__).resolve().parents[1] / ".runtime/references/Backtesting.py"
    if not path.exists():
        pytest.skip("Set up the optional Backtesting.py reference")
    commit = next(c for n, _, c in REFERENCES if n == "Backtesting.py")
    verify_checkout(path, commit)
    return path


@pytest.mark.parametrize("case", list(scenarios()), ids=lambda case: case.name)
def test_reference_broker_executes_controlled_contract_scenarios(reference, case):
    result, test = dashboard_run(case)
    warmup = [Candle(START - i * 300, 100, 101, 99, 100) for i in range(6, 0, -1)]
    higher = [Candle(START - i * 3600, 100, 101, 99, 100) for i in range(10, 0, -1)]
    product = {
        "contract_value": str(case.multiplier),
        "tick_size": case.tick,
        "quoting_asset": {"symbol": "USD"},
    }
    value = BacktestRequest(**result["request"], settings=Settings(**result["settings"]))

    class Fixed:
        def evaluate(self, lower, upper):
            if case.signal and lower[-1].time == START:
                return Signal(case.side, case.atr, START, "controlled reference fixture")

    replayed = broker_replay(
        load_backend(reference), value, warmup + test, higher, product, Fixed()
    )
    assert close_enough(replayed["trades"], ledger(result))
    assert close_enough(replayed["equity_curve"], result["equity_curve"])


@pytest.mark.parametrize(
    "kind", ["momentum_breakout", "ema_trend", "smc_price_action", "rsi_reversion"]
)
@pytest.mark.parametrize("sizing", ["fixed_contracts", "risk_percent"])
def test_raw_input_replay_for_catalogue_strategies_and_native_exits(reference, kind, sizing):
    bars = []
    previous = 100.0
    for i in range(1200):
        price = 100 + 12 * math.sin(i / 7) + 3 * math.sin(i / 2) + i * 0.002
        bars.append(
            Candle(
                START + i * 300,
                previous,
                max(price, previous) + 0.1,
                min(price, previous) - 0.1,
                price,
                20 + i % 3,
            )
        )
        previous = price
    settings = Settings(
        strategy=kind,
        htf_filter="disabled",
        trend_fast_period=3,
        trend_slow_period=8,
        breakout_lookback=3,
        breakout_volume_length=3,
        breakout_volume_multiplier=0.0,
        atr_length=3,
        rsi_length=3,
        rsi_range_filter="disabled",
        smc_swing_length=3,
        smc_order_block_lookback=6,
        smc_zone_type="either",
        smc_body_ratio=0.1,
        sizing_mode=sizing,
        max_contracts=100,
        max_notional_quote=100000.0,
        max_loss_quote=100000.0,
    )
    value = BacktestRequest(
        settings=settings,
        start=START + 600 * 300,
        end=START + 1200 * 300,
        slippage_bps=3.0,
        spread_bps=4.0,
    )
    product = {"contract_value": "0.1", "tick_size": "0.01", "quoting_asset": {"symbol": "USD"}}
    result = simulate(value, bars, [], product)
    assert result["summary"]["trades"] > 0
    inputs = {"candles": [vars(c) for c in bars], "higher": [], "product": product}
    report = check_replay(result, inputs, reference)
    assert report["status"] == "passed", report


def test_independent_replay_detects_mutated_fills_and_input_packets(reference, monkeypatch):
    _, _, _, result, inputs = fixture_run()
    from test_backtest import OneSignal

    monkeypatch.setattr("bot.backtesting_checks.create_strategy", lambda settings: OneSignal())
    assert check_replay(result, inputs, reference)["status"] == "passed"
    broken = copy.deepcopy(result)
    broken["trades"][0]["stop_updates"][0]["stop"] += 1
    assert check_replay(broken, inputs, reference)["status"] == "mismatch"
    corrupt = copy.deepcopy(inputs)
    corrupt["candles"][-1]["volume"] += 1
    assert check_replay(result, corrupt, reference)["status"] == "mismatch"


def test_reference_worker_is_optional_and_full_replay_needs_inputs(tmp_path):
    report = _validate({}, tmp_path, only=["Backtesting.py"])
    assert report[0]["status"] == "unavailable"
    assert report[0]["kind"] == "strategy_replay"


def test_reference_runs_in_separate_worker_with_the_catalogue(reference):
    # Flat data has no signals and exercises the production JSON worker path.
    value, lower, higher, _, _ = fixture_run()
    lower = [Candle(c.time, 100, 101, 99, 100, 10) for c in lower]
    product = {"contract_value": "1", "tick_size": "0.1", "quoting_asset": {"symbol": "USD"}}
    result = simulate(value, lower, higher, product)
    inputs = {
        "candles": [vars(c) for c in lower],
        "higher": [vars(c) for c in higher],
        "product": product,
    }
    report = validate(result, reference.parent, only=["Backtesting.py"], inputs=inputs)
    assert report[0]["status"] == "passed", report


def test_checker_catches_a_broken_engine_stop_move(reference, monkeypatch):
    from test_backtest import OneSignal

    monkeypatch.setattr("bot.backtest.next_stop", lambda position, tick: position.entry)
    monkeypatch.setattr("bot.backtesting_checks.create_strategy", lambda settings: OneSignal())
    _, _, _, broken, inputs = fixture_run()
    assert check_replay(broken, inputs, reference)["status"] == "mismatch"


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("row", [(100, 115, 95, 110), (105, 125, 104, 120)])
def test_reference_covers_advanced_stop_inside_the_same_candle(reference, side, row):
    from test_backtest import PRODUCT, OneSignal, history, request

    rows = [(100, 101, 99, 100), (100, 105, 95, 103), row, (100, 101, 99, 100), (100, 101, 99, 100)]
    if side == "sell":
        rows = [(200 - o, 200 - low, 200 - high, 200 - c) for o, high, low, c in rows]
    lower, higher = history(rows)
    value = request(fee_bps=5.0, slippage_bps=0.0)
    result = simulate(value, lower, higher, PRODUCT, OneSignal(side))
    assert result["trades"][0]["final_reason"] == "advanced_stop"
    replayed = broker_replay(
        load_backend(reference), value, lower, higher, PRODUCT, OneSignal(side)
    )
    assert close_enough(replayed["trades"], ledger(result))
    assert close_enough(replayed["equity_curve"], result["equity_curve"])
