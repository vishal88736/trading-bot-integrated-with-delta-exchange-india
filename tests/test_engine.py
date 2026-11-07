import json

import pytest

from bot.engine import Engine
from bot.models import Signal, State
from bot.settings import Settings, atomic_json
from clients.delta import DeltaError, UncertainOrder


class DemoClient:
    def __init__(self):
        self.orders, self.stops, self.size = [], [], 0
        self.uncertain = self.fail_protect = False

    def product(self, symbol):
        return {
            "id": 84,
            "contract_value": "1",
            "tick_size": "0.1",
            "quoting_asset": {"symbol": "USD"},
        }

    def market_order(self, product_id, side, size, client_id, stop=None):
        self.orders.append({"side": side, "size": size, "id": client_id, "stop": stop})
        if self.uncertain:
            raise UncertainOrder("Unknown write")
        self.size += size * (1 if side == "buy" else -1)
        return {
            "size": size,
            "unfilled_size": 0,
            "state": "closed",
            "average_fill_price": "100",
            "paid_commission": "0",
        }

    def protect(self, product_id, stop):
        if self.fail_protect:
            raise DeltaError("Bracket update failed")
        self.stops.append(float(stop))

    def position(self, product_id):
        return {"size": self.size}

    def open_orders(self, product_id):
        return []

    def set_leverage(self, product_id, leverage):
        assert leverage == 1


def engine(tmp_path, side="buy", mode="paper", **settings):
    client = DemoClient()
    instance = Engine(Settings(mode=mode, paper_fee_bps=0.0, **settings), client, tmp_path)
    instance.open(Signal(side, 10, 1000, "test signal"), 100)
    return instance, client


@pytest.mark.parametrize(
    "side,prices,stops",
    [
        ("buy", [110, 120, 140], [100, 110]),
        ("sell", [90, 80, 60], [100, 90]),
    ],
)
def test_three_target_stop_ladder(tmp_path, side, prices, stops):
    bot, _ = engine(tmp_path, side)
    for index in range(2):
        bot.manage(prices[index])
        assert bot.state.position.stop == stops[index]
        assert bot.state.position.stage == index + 1
        assert bot.state.position.remaining == [2, 1][index]
    bot.manage(prices[2])
    assert bot.state.position is None
    assert [e["quantity"] for e in bot.state.events if e["kind"].startswith("tp")] == [2, 1, 1]
    assert bot.state.realized_quote == 80


def test_stop_never_moves_back_after_pullback(tmp_path):
    bot, _ = engine(tmp_path)
    bot.manage(125)
    assert bot.state.position.stop == 110 and bot.state.position.remaining == 1
    bot.manage(115)
    assert bot.state.position.stop == 110
    bot.manage(109)
    assert bot.state.position is None


def test_paper_fills_never_write_to_exchange(tmp_path):
    bot, client = engine(tmp_path)
    bot.manage(120)
    assert client.orders == client.stops == []


def test_demo_stop_moves_only_after_confirmed_exit(tmp_path):
    bot, client = engine(tmp_path, mode="demo")
    assert client.orders[0]["stop"] == "80.0"
    bot.manage(110)
    assert client.orders[-1]["size"] == 2 and client.orders[-1]["stop"] is None
    assert client.stops == [80, 100] and bot.state.pending is None


def test_uncertain_entry_survives_restart_without_resubmit(tmp_path):
    client = DemoClient()
    client.uncertain = True
    settings = Settings(mode="demo")
    bot = Engine(settings, client, tmp_path)
    with pytest.raises(UncertainOrder):
        bot.open(Signal("buy", 10, 1000, "test"), 100)
    assert json.loads(bot.path.read_text())["pending"]["operation"] == "entry"
    with pytest.raises(UncertainOrder):
        Engine(settings, client, tmp_path)
    assert len(client.orders) == 1


def test_failed_stop_update_preserves_stage_and_pending_intent(tmp_path):
    bot, client = engine(tmp_path, mode="demo")
    client.fail_protect = True
    with pytest.raises(DeltaError):
        bot.manage(110)
    saved = State.parse(json.loads(bot.path.read_text()))
    assert saved.position.remaining == 2 and saved.position.stage == 1
    assert saved.pending["operation"] == "move_stop"
    with pytest.raises(UncertainOrder):
        Engine(bot.settings, client, tmp_path)
    assert len(client.orders) == 2


def test_restart_preserves_paper_stop_and_partial_size(tmp_path):
    bot, client = engine(tmp_path)
    bot.manage(120)
    reloaded = Engine(bot.settings, client, tmp_path)
    assert reloaded.state.position.stop == 110 and reloaded.state.position.remaining == 1
    reloaded.manage(140)
    assert reloaded.state.position is None


def test_settings_cannot_change_with_open_trade(tmp_path):
    bot, client = engine(tmp_path)
    with pytest.raises(DeltaError):
        Engine(Settings(fast_ema=12), client, tmp_path)


def test_risk_limit_blocks_entry(tmp_path):
    bot, _ = engine(tmp_path, max_notional_quote=100.0)
    assert bot.state.position is None and bot.state.events[-1]["kind"] == "risk_block"
    bot.state.realized_quote = -50
    bot.open(Signal("buy", 10, 1000, "test"), 1)
    assert bot.state.position is None


def test_account_drift_halts_before_any_order(tmp_path):
    bot, client = engine(tmp_path, mode="demo")
    client.size = 0
    with pytest.raises(DeltaError, match="differs"):
        bot.check_account()
    assert len(client.orders) == 1


def test_zero_position_is_persisted_after_full_close(tmp_path):
    bot, _ = engine(tmp_path)
    bot.manage(70)
    saved = json.loads(bot.path.read_text())
    assert saved["position"] is None and saved["pending"] is None


def test_state_file_is_private(tmp_path):
    path = tmp_path / "secrets.json"
    atomic_json(path, {"api_secret": "fixture-secret"})
    assert path.stat().st_mode & 0o777 == 0o600
