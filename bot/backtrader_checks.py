"""Differential execution checks using Backtrader's unmodified simulated broker.

The two engines receive controlled OHLC paths and a fixed entry signal, not each
other's fills. The Backtrader adapter independently builds levels and stop/target
OCO orders; it never calls the dashboard's trade-plan or stop-update helpers.
These are engine scenarios, not a second replay of a user's strategy or history.
"""

import importlib
import math
import sys
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from bot.backtest import BacktestRequest, simulate
from bot.models import Candle, Signal
from bot.settings import Settings

START = 1728000000
INTERVAL = 300


@dataclass(frozen=True)
class Scenario:
    name: str
    side: str
    rows: tuple
    fee_bps: float = 5.0
    slippage_bps: float = 0.0
    atr: float = 10.0
    contracts: int = 4
    multiplier: float = 1.0
    tick: str = "0.1"
    signal: bool = True


def scenarios():
    target1 = (105, 112, 104, 111)
    target2 = (115, 122, 112, 121)
    target3 = (135, 142, 125, 140)
    # After an exit this bar would trigger any orphaned protective order.
    sentinel = (100, 150, 50, 100)
    paths = (
        ("three_targets", (target1, target2, target3, sentinel), {}),
        ("tp1_then_entry_stop", (target1, (104, 106, 99, 101), sentinel), {}),
        ("tp2_then_tp1_stop", (target1, target2, (115, 118, 109, 111), sentinel), {}),
        ("initial_stop", ((100, 102, 79, 85), sentinel), {}),
        ("gap_stop_with_costs", ((70, 75, 65, 72), sentinel), {"slippage_bps": 2.0}),
        ("final_close_with_costs", ((103, 106, 99, 104),), {"slippage_bps": 2.0}),
        ("initial_stop_before_target", ((100, 140, 70, 100), sentinel), {}),
        (
            "odd_contracts_tick_and_multiplier",
            (target1, target2, target3, sentinel),
            {"atr": 2.63, "contracts": 7, "multiplier": 0.01, "tick": "0.25"},
        ),
        ("no_signal", (target1, target2, target3, sentinel), {"signal": False}),
    )
    for side in ("buy", "sell"):
        for name, path, options in paths:
            rows = ((100, 101, 99, 100), (100, 105, 95, 103), *path)
            scale = options.get("atr", 10.0) / 10
            rows = tuple(tuple(100 + (p - 100) * scale for p in row) for row in rows)
            if side == "sell":
                rows = tuple((200 - o, 200 - low, 200 - high, 200 - c) for o, high, low, c in rows)
            yield Scenario(f"{side}_{name}", side, rows, **options)


def load_backend(path):
    """Import only the reviewed checkout inside the optional reference worker."""
    sys.path.insert(0, str(path.resolve()))
    try:
        backend = importlib.import_module("backtrader")
    finally:
        sys.path.pop(0)
    if not backend.__file__ or not Path(backend.__file__).resolve().is_relative_to(path.resolve()):
        raise ValueError("Backtrader was loaded from a different source")
    return backend


def dashboard_run(case):
    settings = Settings(
        fast_ema=2,
        slow_ema=3,
        cmo_length=2,
        atr_length=2,
        macro_sma=0,
        contracts=case.contracts,
        max_contracts=case.contracts,
        max_notional_quote=1000000.0,
        max_loss_quote=100000.0,
    )
    request = BacktestRequest(
        settings=settings,
        start=START,
        end=START + len(case.rows) * INTERVAL,
        initial_balance=10000.0,
        fee_bps=case.fee_bps,
        slippage_bps=case.slippage_bps,
    )
    bars = [Candle(START + i * INTERVAL, *row) for i, row in enumerate(case.rows)]
    warmup = [Candle(START - i * INTERVAL, 100, 101, 99, 100) for i in range(6, 0, -1)]
    higher = [Candle(START - i * 3600, 100, 101, 99, 100) for i in range(10, 0, -1)]

    class FixedSignal:
        def evaluate(self, candles, higher):
            if case.signal and candles[-1].time == START:
                return Signal(case.side, case.atr, START, "controlled execution scenario")

    product = {
        "contract_value": str(case.multiplier),
        "tick_size": case.tick,
        "quoting_asset": {"symbol": "USD"},
    }
    result = simulate(request, warmup + bars, higher, product, FixedSignal())
    return result, bars


def broker_run(bt, case, bars):
    """Use real Backtrader Market/Stop/Limit orders, without overriding its broker."""

    class CandleFeed(bt.feed.DataBase):
        lines = ("unix_time",)
        params = (("bars", None),)

        def start(self):
            super().start()
            self.rows = iter(self.p.bars)

        def _load(self):
            bar = next(self.rows, None)
            if bar is None:
                return False
            self.lines.datetime[0] = bt.date2num(datetime.fromtimestamp(bar.time, UTC))
            self.lines.unix_time[0] = bar.time
            for field in ("open", "high", "low", "close", "volume"):
                getattr(self.lines, field)[0] = getattr(bar, field)
            self.lines.openinterest[0] = 0
            return True

    class LinearCommission(bt.CommInfoBase):
        params = (("stocklike", False), ("commtype", bt.CommInfoBase.COMM_PERC))

        def _getcommission(self, size, price, pseudoexec):
            return abs(size) * price * self.p.mult * self.p.commission

    class BracketStrategy(bt.Strategy):
        def __init__(self):
            self.ledger, self.failures = [], []
            self.stage, self.remaining = 0, 0
            self.stop_order, self.target_order = None, None
            self.trade = None

        def rounded(self, price):
            step = Decimal(case.tick)
            return float((Decimal(str(price)) / step).quantize(Decimal(1), ROUND_HALF_UP) * step)

        def arm_exits(self):
            if len(self.data) >= len(bars):
                return  # The final-close order will settle the remaining contracts.
            exit_order = self.sell if case.side == "buy" else self.buy
            self.stop_order = exit_order(
                size=self.remaining, price=self.stop_price, exectype=bt.Order.Stop, role="stop"
            )
            self.target_order = exit_order(
                size=self.allocations[self.stage],
                price=self.targets[self.stage],
                exectype=bt.Order.Limit,
                oco=self.stop_order,
                role=f"tp{self.stage + 1}",
            )

        def next(self):
            if len(self.data) == 1 and case.signal:
                enter = self.buy if case.side == "buy" else self.sell
                enter(size=case.contracts, exectype=bt.Order.Market, role="entry")
            if len(self.data) == len(bars) and self.position:
                self.cancel(self.stop_order)
                self.cancel(self.target_order)
                self.close(exectype=bt.Order.Market, role="end_of_test")

        def notify_order(self, order):
            if order.status in (order.Margin, order.Rejected, order.Expired):
                self.failures.append(order.getstatusname())
            if order.status != order.Completed:
                return
            role = order.info.role
            timestamp = int(self.data.unix_time[0])
            price, quantity = order.executed.price, int(abs(order.executed.size))
            if role == "entry":
                direction = 1 if case.side == "buy" else -1
                self.entry = price
                self.stop_price = self.rounded(price - direction * 2 * case.atr)
                self.targets = [self.rounded(price + direction * m * case.atr) for m in (1, 2, 4)]
                self.allocations = [case.contracts // 2, case.contracts // 4]
                self.allocations.append(case.contracts - sum(self.allocations))
                self.remaining = quantity
                self.trade = {
                    "side": case.side,
                    "entry_time": timestamp,
                    "entry": price,
                    "initial_stop": self.stop_price,
                    "targets": self.targets[:],
                    "quantity": quantity,
                    "fees": order.executed.comm,
                    "net_pnl": -order.executed.comm,
                    "exits": [],
                    "stop_updates": [],
                }
                self.arm_exits()
                return
            timestamp += 0 if role == "end_of_test" else INTERVAL
            pnl = order.executed.pnl - order.executed.comm
            self.trade["fees"] += order.executed.comm
            self.trade["net_pnl"] += pnl
            self.trade["exits"].append(
                {
                    "time": timestamp,
                    "reason": role,
                    "price": price,
                    "quantity": quantity,
                    "net_pnl": pnl,
                }
            )
            self.remaining -= quantity
            if not self.remaining:
                self.trade.update(exit_time=timestamp, final_reason=role)
                self.ledger.append(self.trade)
                self.trade = None
            elif role.startswith("tp"):
                self.stage += 1
                self.stop_price = self.entry if self.stage == 1 else self.targets[self.stage - 2]
                self.trade["stop_updates"].append(
                    {"time": timestamp, "after_target": self.stage, "stop": self.stop_price}
                )
                self.arm_exits()

    # A flat settlement bar executes the final market close at the final close
    # price. It is an explicit test harness convention, not additional market data.
    last = bars[-1]
    settlement = Candle(last.time + INTERVAL, *([last.close] * 4))
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(CandleFeed(bars=[*bars, settlement]))
    cerebro.addstrategy(BracketStrategy)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.set_slippage_perc(case.slippage_bps / 10000, slip_open=True, slip_out=True)
    cerebro.broker.addcommissioninfo(
        LinearCommission(
            commission=case.fee_bps / 10000,
            percabs=True,
            mult=case.multiplier,
            margin=1.0,
            automargin=-1,
        )
    )
    with warnings.catch_warnings():
        # This reviewed version still uses utcnow() for its internal timing loop.
        warnings.filterwarnings(
            "ignore",
            message=r"datetime\.datetime\.utcnow\(\) is deprecated.*",
            category=DeprecationWarning,
            module=r"backtrader\.cerebro",
        )
        strategy = cerebro.run(runonce=False)[0]
    return {
        "ending_equity": cerebro.broker.getvalue(),
        "trades": strategy.ledger,
        "flat": not bool(strategy.position),
        "open_orders": len(cerebro.broker.get_orders_open()),
        "failures": strategy.failures,
    }


def agrees(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(agrees(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            agrees(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-8)
    return left == right


def check_scenarios(path):
    bt = load_backend(path)
    checks = {}
    keys = (
        "side",
        "entry_time",
        "entry",
        "initial_stop",
        "targets",
        "quantity",
        "fees",
        "net_pnl",
        "exits",
        "stop_updates",
        "exit_time",
        "final_reason",
    )
    for case in scenarios():
        result, bars = dashboard_run(case)
        dashboard = {
            "ending_equity": result["summary"]["ending_equity"],
            "trades": [{key: trade[key] for key in keys} for trade in result["trades"]],
            "flat": True,
            "open_orders": 0,
            "failures": [],
        }
        reference = broker_run(bt, case, bars)
        checks[case.name] = {
            "passed": agrees(dashboard, reference),
            "dashboard": dashboard,
            "reference": reference,
        }
    passed = sum(check["passed"] for check in checks.values())
    return {
        "status": "passed" if passed == len(checks) else "mismatch",
        "kind": "execution_scenarios",
        "version": bt.__version__,
        "checks": checks,
        "message": f"{passed}/{len(checks)} controlled broker scenarios agree.",
        "scope": (
            "Independent Backtrader broker execution on controlled OHLC paths and fixed signals; "
            "not an independent replay of this strategy, instrument or historical period."
        ),
        "limitations": [
            (
                "Target-order scenarios use zero slippage: "
                "Backtrader limit fills differ from market target exits."
            ),
            "Newly advanced stops and multiple targets touched in one candle are not compared.",
            (
                "Entry candles do not touch exits; "
                "activation timing within the entry candle is not compared."
            ),
            (
                "Indicator signals and account risk-limit rules "
                "are not cross-validated by fixed-signal scenarios."
            ),
            "Funding, liquidation, latency and live exchange order handling are not covered.",
        ],
    }
