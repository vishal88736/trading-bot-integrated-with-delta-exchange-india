from pathlib import Path

import pytest

import bot.backtest as replay
from bot.backtrader_checks import check_scenarios
from bot.reference_checks import REFERENCES, _validate, verify_checkout


@pytest.fixture(scope="module")
def reference():
    path = Path(__file__).resolve().parents[1] / ".runtime/references/Backtrader"
    if not path.exists():
        pytest.skip("Run scripts/setup_references.py --only Backtrader")
    commit = next(commit for name, _, commit in REFERENCES if name == "Backtrader")
    verify_checkout(path, commit)
    return path


@pytest.fixture(scope="module")
def report(reference):
    return check_scenarios(reference)


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize(
    "case",
    [
        "three_targets",
        "tp1_then_entry_stop",
        "tp2_then_tp1_stop",
        "initial_stop",
        "gap_stop_with_costs",
        "final_close_with_costs",
        "initial_stop_before_target",
        "odd_contracts_tick_and_multiplier",
        "no_signal",
        "fractional_entry_stop_tick",
    ],
)
def test_independent_broker_matches_dashboard_execution(report, side, case):
    check = report["checks"][f"{side}_{case}"]
    assert check["passed"], check
    reference = check["reference"]
    assert reference["flat"] and reference["open_orders"] == 0
    assert not reference["failures"]


@pytest.mark.parametrize("side,stops", [("buy", [100, 110]), ("sell", [100, 90])])
def test_broker_stop_ladder_and_partial_quantities_have_known_expected_values(report, side, stops):
    trade = report["checks"][f"{side}_three_targets"]["reference"]["trades"][0]
    assert [update["stop"] for update in trade["stop_updates"]] == stops
    assert [leg["quantity"] for leg in trade["exits"]] == [2, 1, 1]
    assert trade["entry_time"] == 1728000300
    assert [leg["reason"] for leg in trade["exits"]] == ["tp1", "tp2", "tp3"]
    assert trade["fees"] == pytest.approx(0.44 if side == "buy" else 0.36)
    assert trade["net_pnl"] == pytest.approx(79.56 if side == "buy" else 79.64)


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_broker_rounds_fractional_entry_break_even_to_tick(report, side):
    trade = report["checks"][f"{side}_fractional_entry_stop_tick"]["reference"]["trades"][0]
    assert trade["stop_updates"][0]["stop"] == 100.0


def test_checker_detects_broken_dashboard_stop_ladder(reference, monkeypatch):
    # Break TP2 -> TP1 in our engine only. Backtrader must keep its own correct ladder.
    monkeypatch.setattr(replay, "next_stop", lambda position, tick: position.entry)
    report = check_scenarios(reference)
    assert report["status"] == "mismatch"
    assert not report["checks"]["buy_tp2_then_tp1_stop"]["passed"]
    assert not report["checks"]["sell_tp2_then_tp1_stop"]["passed"]


def test_checker_detects_broken_dashboard_partial_allocations(reference, monkeypatch):
    original = replay.trade_plan

    def wrong_quantities(settings, signal, entry, tick):
        position = original(settings, signal, entry, tick)
        if settings.contracts == 4:
            position.quantities = [1, 1, 2]
        return position

    monkeypatch.setattr(replay, "trade_plan", wrong_quantities)
    report = check_scenarios(reference)
    assert report["status"] == "mismatch"
    assert not report["checks"]["buy_three_targets"]["passed"]
    assert not report["checks"]["sell_three_targets"]["passed"]


def test_missing_reference_is_not_reported_as_a_pass(tmp_path):
    report = _validate({}, tmp_path, only=["Backtrader"])
    assert len(report) == 1
    assert report[0]["status"] == "unavailable"
    assert report[0]["kind"] == "execution_scenarios"


def test_unreviewed_reference_is_not_executed(tmp_path, monkeypatch):
    (tmp_path / "Backtrader").mkdir()

    def reject(*args):
        raise ValueError("unreviewed checkout")

    monkeypatch.setattr("bot.reference_checks.verify_checkout", reject)
    report = _validate({}, tmp_path, only=["Backtrader"])
    assert report[0]["status"] == "error"
    assert "checks" not in report[0]
