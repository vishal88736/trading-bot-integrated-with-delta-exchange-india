import copy
import gzip
import json

import pytest
from test_backtest import PRODUCT, START, OneSignal, history, request

from bot.backtest import BacktestRequest, Backtests, simulate
from bot.cost_checks import stress_costs
from bot.models import Candle
from clients.delta import DeltaError


def fixture_run(**costs):
    lower, higher = history(
        [
            (100, 101, 99, 100),
            (100, 105, 95, 103),
            (111, 115, 105, 114),
            (121, 125, 112, 124),
            (139, 141, 125, 140),
        ]
    )
    value = request(**costs)
    result = simulate(value, lower, higher, PRODUCT, OneSignal())
    inputs = {
        "candles": [vars(c) for c in lower],
        "higher": [vars(c) for c in higher],
        "product": PRODUCT,
    }
    return value, lower, higher, result, inputs


@pytest.mark.parametrize("defect", ["missing_start", "missing_end", "gap", "duplicate", "order"])
def test_replay_refuses_incomplete_or_disordered_data(defect):
    value, lower, higher, _, _ = fixture_run()
    if defect == "missing_start":
        lower.pop(6)
    elif defect == "missing_end":
        lower.pop()
    elif defect == "gap":
        lower.pop(8)
    elif defect == "duplicate":
        lower.insert(8, lower[8])
    else:
        lower[7], lower[8] = lower[8], lower[7]
    with pytest.raises(DeltaError, match="incomplete|gaps|duplicates|out-of-order"):
        simulate(value, lower, higher, PRODUCT, OneSignal())


def test_replay_refuses_unclosed_and_missing_higher_timeframe_data():
    value, lower, higher, _, _ = fixture_run()
    with pytest.raises(DeltaError, match="unclosed"):
        simulate(value, lower + [Candle(value.end, 100, 101, 99, 100)], higher, PRODUCT)
    with pytest.raises(DeltaError, match="incomplete"):
        simulate(value, lower, higher[:-1], PRODUCT)
    corrupted = copy.deepcopy(lower)
    object.__setattr__(corrupted[7], "close", float("nan"))
    with pytest.raises(DeltaError, match="Invalid"):
        simulate(value, corrupted, higher, PRODUCT)


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_partial_trade_costs_reconcile_to_before_cost_pnl(side):
    value, lower, higher, _, _ = fixture_run(fee_bps=7.0, slippage_bps=3.0, spread_bps=8.0)
    result = simulate(value, lower, higher, PRODUCT, OneSignal(side))
    summary = result["summary"]
    assert summary["slippage_cost"] > 0 and summary["spread_cost"] > 0
    assert summary["total_costs"] == pytest.approx(
        summary["fees"] + summary["slippage_cost"] + summary["spread_cost"]
    )
    assert summary["net_pnl"] == pytest.approx(summary["before_cost_pnl"] - summary["total_costs"])
    assert summary["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in result["trades"]))
    assert summary["fees"] == pytest.approx(sum(t["fees"] for t in result["trades"]))
    for trade in result["trades"]:
        assert sum(leg["quantity"] for leg in trade["exits"]) == trade["quantity"]
        assert all("reference_price" in leg and "fee" in leg for leg in trade["exits"])


@pytest.mark.parametrize(
    "changes",
    [
        {"spread_bps": 60.0},
        {"cost_stress_bps": [-1.0]},
        {"cost_stress_bps": [float("nan")]},
        {"cost_stress_bps": [5.0, 5.0]},
        {"cost_stress_bps": [1.0, 2.0, 3.0, 4.0, 5.0]},
    ],
)
def test_execution_cost_limits_are_validated(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_data_identity_changes_when_bars_or_contract_units_change():
    value, lower, higher, result, _ = fixture_run()
    fingerprint = result["data_quality"]["data_sha256"]
    assert result["data_quality"]["actual_candles"] == 5
    assert result["data_quality"]["coverage_percent"] == 100
    assert simulate(value, lower, higher, PRODUCT)["data_quality"]["data_sha256"] == fingerprint
    changed = lower[:-1] + [Candle(lower[-1].time, 139, 141, 125, 140, 1)]
    assert simulate(value, changed, higher, PRODUCT)["data_quality"]["data_sha256"] != fingerprint
    units = {**PRODUCT, "contract_value": "0.01"}
    assert simulate(value, lower, higher, units)["data_quality"]["data_sha256"] != fingerprint


def test_cost_stress_preserves_baseline_rules_and_execution_guard(monkeypatch):
    _, _, _, result, inputs = fixture_run(cost_stress_bps=[2.0, 20.0, 50.0])
    original = copy.deepcopy(result)
    monkeypatch.setattr("bot.backtest.create_strategy", lambda settings: OneSignal())
    stress = stress_costs(result, inputs)
    assert result == original
    assert [r["status"] for r in stress["scenarios"]] == ["completed", "completed", "skipped"]
    assert stress["scenarios"][0]["net_pnl"] == pytest.approx(result["summary"]["net_pnl"])
    assert stress["scenarios"][1]["net_pnl"] < stress["scenarios"][0]["net_pnl"]
    assert stress_costs(result, None)["status"] == "unavailable"


def test_cost_stress_carries_its_own_capital_between_frozen_folds(monkeypatch):
    _, _, _, result, inputs = fixture_run(cost_stress_bps=[10.0])
    calls = []
    original = simulate

    def track(value, *args, **kwargs):
        calls.append(value.initial_balance)
        return original(value, *args, **kwargs)

    monkeypatch.setattr("bot.backtest.simulate", track)
    monkeypatch.setattr("bot.backtest.create_strategy", lambda settings: OneSignal())
    packet = {
        "folds": [
            {"result": result, "inputs": inputs, "held_cash": False},
            {"result": result, "inputs": inputs, "held_cash": False},
        ]
    }
    stress = stress_costs(result, packet)
    assert len(calls) == 2 and calls[0] == 10000 and calls[1] != 10000
    assert stress["scenarios"][0]["trades"] == 2


def test_exact_inputs_are_saved_once_and_export_has_no_credentials(tmp_path):
    _, lower, higher, result, inputs = fixture_run()
    runner = Backtests(artifact_root=tmp_path)
    runner.remember_inputs(result, lower, higher, PRODUCT)
    runner.save_result(0, result)
    runner.save_result(1, result)
    assert len(list((tmp_path / runner.run_id).glob("inputs-*.json.gz"))) == 1
    assert runner.validation_inputs(result) == inputs
    with pytest.raises(DeltaError, match="Wait"):
        runner.input_report(0, runner.run_id)
    runner.job["status"] = "completed"
    with gzip.open(runner.input_report(0, runner.run_id), "rt") as stream:
        exported = json.load(stream)
    assert exported == inputs
    assert set(exported) == {"candles", "higher", "product"}
    with pytest.raises(DeltaError, match="earlier run"):
        runner.input_report(0, "wrong")


def test_partial_date_boundaries_use_only_complete_utc_candles():
    _, lower, higher, _, _ = fixture_run()
    value = BacktestRequest(settings=request().settings, start=START + 1, end=START + 1499)
    result = simulate(value, lower[:-1], higher, PRODUCT)
    assert result["candles"] == 3
    assert result["actual_start"] == START + 300
    assert result["actual_end"] == START + 1200
