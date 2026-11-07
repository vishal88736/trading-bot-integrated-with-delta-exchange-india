import json
import time

import pytest

from bot.backtest import BacktestRequest, simulate
from bot.models import Candle, Signal
from bot.settings import Settings

START = 10000000
PRODUCT = {"contract_value": "1", "tick_size": "0.1", "quoting_asset": {"symbol": "USD"}}


def request(**kwargs):
    settings = kwargs.pop(
        "settings",
        Settings(
            fast_ema=2,
            slow_ema=3,
            cmo_length=2,
            atr_length=2,
            macro_sma=0,
            max_notional_quote=10000.0,
            max_loss_quote=10000.0,
        ),
    )
    return BacktestRequest(
        settings=settings, start=START, end=START + 1500, initial_balance=10000.0, **kwargs
    )


class OneSignal:
    def __init__(self, side="buy"):
        self.side = side

    def evaluate(self, candles, higher):
        # Prove the replay never hands a strategy any future bars.
        assert all(c.time + 3600 <= candles[-1].time + 300 for c in higher)
        if candles[-1].time == START:
            return Signal(self.side, 10, START, "controlled strategy fixture")


def history(rows):
    warmup = [Candle(START - (6 - i) * 300, 100, 101, 99, 100) for i in range(6)]
    bars = [Candle(START + i * 300, *row) for i, row in enumerate(rows)]
    higher = [Candle(START - 3600 * (10 - i), 100, 101, 99, 100) for i in range(10)]
    return warmup + bars, higher


@pytest.mark.parametrize(
    "side,rows,expected_stops",
    [
        (
            "buy",
            [
                (100, 101, 99, 100),
                (100, 105, 99, 103),
                (111, 115, 110, 114),
                (121, 125, 120, 124),
                (139, 141, 138, 140),
            ],
            [100, 110],
        ),
        (
            "sell",
            [
                (100, 101, 99, 100),
                (100, 101, 95, 97),
                (89, 90, 85, 86),
                (79, 80, 75, 76),
                (61, 62, 59, 60),
            ],
            [100, 90],
        ),
    ],
)
def test_three_tier_replay_fills_next_open_and_advances_stop(side, rows, expected_stops):
    bars, higher = history(rows)
    result = simulate(
        request(fee_bps=0.0, slippage_bps=0.0), bars, higher, PRODUCT, OneSignal(side)
    )
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["entry_time"] == START + 300
    assert [e["quantity"] for e in trade["exits"]] == [2, 1, 1]
    assert [u["stop"] for u in trade["stop_updates"]] == expected_stops
    assert result["summary"]["net_pnl"] == 80
    assert trade["net_pnl"] == 80


def test_ambiguous_bar_uses_initial_stop_before_target():
    bars, higher = history([(100, 101, 99, 100), (100, 140, 70, 100), (100, 101, 99, 100)])
    result = simulate(request(fee_bps=0.0, slippage_bps=0.0), bars, higher, PRODUCT, OneSignal())
    assert result["trades"][0]["exits"][0]["reason"] == "stop"
    assert result["summary"]["net_pnl"] == -80
    assert result["ambiguous_candles"] == 1


def test_tp1_then_break_even_in_same_bar_is_conservative():
    bars, higher = history([(100, 101, 99, 100), (100, 115, 95, 110), (100, 101, 99, 100)])
    result = simulate(request(fee_bps=0.0, slippage_bps=0.0), bars, higher, PRODUCT, OneSignal())
    assert [e["reason"] for e in result["trades"][0]["exits"]] == ["tp1", "advanced_stop"]
    assert result["summary"]["net_pnl"] == 20


def test_gap_stop_fills_at_worse_open():
    bars, higher = history([(100, 101, 99, 100), (100, 105, 90, 100), (60, 70, 50, 60)])
    result = simulate(request(fee_bps=0.0, slippage_bps=0.0), bars, higher, PRODUCT, OneSignal())
    assert result["trades"][0]["exits"][0]["price"] == 60
    assert result["summary"]["net_pnl"] == -160


def test_fees_slippage_and_ending_equity_reconcile():
    bars, higher = history([(100, 101, 99, 100), (100, 105, 95, 103), (103, 106, 99, 104)])
    result = simulate(request(fee_bps=10.0, slippage_bps=10.0), bars, higher, PRODUCT, OneSignal())
    trade = result["trades"][0]
    assert trade["entry"] == pytest.approx(100.1)
    assert trade["final_reason"] == "end_of_test"
    expected = (104 * 0.999 - 100.1) * 4 - (100.1 + 104 * 0.999) * 4 * 0.001
    assert trade["net_pnl"] == pytest.approx(expected)
    assert result["summary"]["ending_equity"] == pytest.approx(10000 + expected)
    assert result["summary"]["fees"] == pytest.approx(trade["fees"])
    assert result["equity_curve"][-1]["equity"] == result["summary"]["ending_equity"]
    json.dumps(result, allow_nan=False)


def test_zero_trades_are_valid_results():
    bars, higher = history([(100, 101, 99, 100)] * 5)
    result = simulate(
        request(fee_bps=0.0, slippage_bps=0.0),
        bars,
        higher,
        PRODUCT,
        type("NoSignals", (), {"evaluate": lambda *args: None})(),
    )
    assert result["summary"]["trades"] == 0
    assert result["summary"]["net_pnl"] == 0
    assert result["summary"]["win_rate"] is None


def test_insufficient_funds_skip_trade_instead_of_leveraging_implicitly():
    bars, higher = history([(100, 101, 99, 100)] * 5)
    options = request(fee_bps=0.0, slippage_bps=0.0).model_copy(update={"initial_balance": 100.0})
    result = simulate(options, bars, higher, PRODUCT, OneSignal())
    assert result["summary"]["trades"] == 0
    assert result["rejected_entries"] == {"insufficient_simulated_funds": 1}


@pytest.mark.parametrize(
    "values",
    [
        {"end": START - 1},
        {"end": int(time.time()) + 100},
        {"end": START + 100000000},
        {"fee_bps": float("nan")},
    ],
)
def test_invalid_backtest_inputs_rejected(values):
    with pytest.raises(ValueError):
        BacktestRequest.model_validate(
            {"settings": Settings(), "start": START, "end": START + 1000, **values}
        )


def test_full_year_at_one_minute_is_supported_without_changing_account_mode():
    end = int(time.time()) - 60
    value = BacktestRequest(settings=Settings(timeframe="1m"), start=end - 365 * 86400, end=end)
    assert value.source == "india_public"
    assert value.settings.mode == "paper"


def test_backtest_client_failure_is_reported_instead_of_staying_running():
    from bot.backtest import Backtests

    def unavailable():
        raise RuntimeError("private transport details")

    backtests = Backtests(factory=unavailable)
    backtests._run(request())
    snapshot = backtests.snapshot()
    assert snapshot["status"] == "error" and snapshot["result"] is None
    assert "private transport details" not in snapshot["message"]
