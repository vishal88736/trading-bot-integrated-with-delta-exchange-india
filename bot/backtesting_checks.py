"""Full-period differential replay with the pinned Backtesting.py broker.

Strategy signals are shared. Contract scaling, conservative OHLC event ordering,
and Delta's three-part exit ladder are supplied by this adapter. The upstream
broker independently accepts orders, charges fees, reduces positions and accounts
for cash/equity. This is deliberately narrower than independent strategy proof.
"""

import bisect
import importlib
import math
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from bot.cost_checks import selected_runs, unpack
from bot.data_quality import inspect_data
from bot.models import RESOLUTIONS
from bot.reference_checks import compare
from strategies.catalogue import create_strategy, direction_allowed

TRADE_KEYS = (
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
LEG_KEYS = ("time", "reason", "price", "quantity", "net_pnl")


def load_backend(path):
    sys.path.insert(0, str(path.resolve()))
    try:
        module = importlib.import_module("backtesting.backtesting")
    finally:
        sys.path.pop(0)
    if not Path(module.__file__).resolve().is_relative_to(path.resolve()):
        raise ValueError("Backtesting.py loaded from a different source")
    return module


def close_enough(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(close_enough(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            close_enough(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-8, abs_tol=1e-7)
    return left == right


def ledger(result):
    rows = []
    for trade in result["trades"]:
        row = {key: trade[key] for key in TRADE_KEYS}
        row["exits"] = [{key: leg[key] for key in LEG_KEYS} for leg in trade["exits"]]
        rows.append(row)
    return rows


def broker_replay(backend, request, candles, higher, product, strategy=None, held_cash=False):
    import pandas as pd

    s = request.settings
    interval, hinterval = RESOLUTIONS[s.timeframe], RESOLUTIONS[s.higher_timeframe]
    units = float(product["contract_value"])
    fee = request.fee_bps / 10000
    impact = (request.slippage_bps + request.spread_bps / 2) / 10000
    tick = Decimal(str(product["tick_size"]))

    def rounded(price):
        return float((Decimal(str(price)) / tick).quantize(Decimal(1), ROUND_HALF_UP) * tick)

    frame = pd.DataFrame(
        {
            key.title(): [getattr(c, key) * units for c in candles]
            for key in ("open", "high", "low", "close")
        },
        index=pd.to_datetime([c.time for c in candles], unit="s", utc=True),
    )
    frame["Volume"] = [c.volume for c in candles]
    data = backend._Data(frame)
    broker = backend._Broker(
        data=data,
        cash=request.initial_balance,
        spread=impact,
        commission=fee,
        margin=1 / s.leverage,
        trade_on_close=False,
        hedging=False,
        exclusive_orders=False,
        index=frame.index,
    )
    strategy = strategy or create_strategy(s)
    prepared = strategy.prepare(candles, higher) if hasattr(strategy, "prepare") else None
    hcloses = [c.time + hinterval for c in higher]
    indices = [
        i
        for i, c in enumerate(candles)
        if request.start <= c.time and c.time + interval <= request.end
    ]
    pending, pending_exit, active, record = None, None, None, None
    stage, stop, targets, quantities = 0, 0, [], []
    records, curve = [], []
    fees = 0.0

    def reduce(quantity, reference, timestamp, reason):
        nonlocal active, record, fees
        direction = 1 if active.is_long else -1
        fill = reference * (1 - direction * impact) * units
        cash_before = broker._cash
        broker._reduce_trade(active, fill, -direction * quantity, current)
        closed = broker.closed_trades[-1]
        exit_fee = broker._commission(quantity, fill)
        pnl = broker._cash - cash_before
        fees += exit_fee
        record["fees"] += exit_fee
        record["net_pnl"] += pnl
        record["exits"].append(
            {
                "time": timestamp,
                "reason": reason,
                "price": closed.exit_price / units,
                "quantity": quantity,
                "net_pnl": pnl,
            }
        )
        if active not in broker.trades:
            record.update(exit_time=timestamp, final_reason=reason)
            records.append(record)
            active, record = None, None

    for current in indices:
        candle = candles[current]
        data._set_length(current + 1)
        broker._i = current
        broker._trades_cache_clear()
        had_position = active is not None
        if pending_exit and active:
            reduce(abs(active.size), candle.open, candle.time, pending_exit)
        pending_exit = None
        if pending and not held_cash:
            direction = 1 if pending.side == "buy" else -1
            entry = candle.open * (1 + direction * impact)
            quantity = s.contracts
            if s.sizing_mode == "risk_percent":
                reserve = s.max_entry_slippage_bps / 10000
                planned_stop = rounded(entry - direction * pending.atr * s.sl_atr)
                worst_entry, exit_base = entry * (1 + reserve), max(entry, planned_stop)
                risk = (
                    abs(entry - planned_stop)
                    + float(tick)
                    + (entry + exit_base) * reserve
                    + (worst_entry + exit_base * (1 + reserve)) * fee
                ) * units
                capital = max(0, broker._cash)
                quantity = max(
                    0,
                    math.floor(
                        min(
                            capital * s.risk_per_trade_percent / 100 / risk,
                            capital / (worst_entry * units * (1 / s.leverage + fee)),
                            s.max_contracts,
                            s.max_notional_quote / (worst_entry * units),
                        )
                    ),
                )
            notional = entry * quantity * units
            if (
                broker._cash - request.initial_balance > -s.max_loss_quote
                and broker._cash > 0
                and quantity >= 4
                and quantity <= s.max_contracts
                and notional <= s.max_notional_quote
                and notional / s.leverage + notional * fee <= broker._cash
            ):
                broker.new_order(direction * quantity)
                cash_before = broker._cash
                broker.next()
                if not broker.trades:
                    raise ValueError("Reference broker rejected an expected entry")
                active = broker.trades[-1]
                entry = active.entry_price / units
                entry_fee = cash_before - broker._cash
                fees += entry_fee
                stop = rounded(entry - direction * pending.atr * s.sl_atr)
                targets = [rounded(entry + direction * pending.atr * v) for v in s.tp_atr]
                if not (
                    direction * (entry - stop) > 0
                    and all(
                        direction * (b - a) > 0
                        for a, b in zip([entry] + targets, targets, strict=False)
                    )
                ):
                    raise ValueError("Reference ATR levels collapsed at the tick size")
                quantities = [quantity // 2, quantity // 4]
                quantities.append(quantity - sum(quantities))
                stage = 0
                record = {
                    "side": pending.side,
                    "entry_time": candle.time,
                    "entry": entry,
                    "initial_stop": stop,
                    "targets": targets[:],
                    "quantity": quantity,
                    "fees": entry_fee,
                    "net_pnl": -entry_fee,
                    "exits": [],
                    "stop_updates": [],
                }
            pending = None
        traded = had_position or active is not None
        if active:
            direction = 1 if active.is_long else -1
            adverse, favorable = (
                (candle.low, candle.high) if direction == 1 else (candle.high, candle.low)
            )
            if direction * (adverse - stop) <= 0:
                reference = min(candle.open, stop) if direction == 1 else max(candle.open, stop)
                reduce(abs(active.size), reference, candle.time + interval, "stop")
            else:
                while active and direction * (favorable - targets[stage]) >= 0:
                    reduce(
                        quantities[stage], targets[stage], candle.time + interval, f"tp{stage + 1}"
                    )
                    if active:
                        stage += 1
                        stop = rounded(record["entry"] if stage == 1 else targets[stage - 2])
                        record["stop_updates"].append(
                            {"time": candle.time + interval, "after_target": stage, "stop": stop}
                        )
                        if direction * (adverse - stop) <= 0:
                            reduce(abs(active.size), stop, candle.time + interval, "advanced_stop")
        end = bisect.bisect_right(hcloses, candle.time + interval)
        lower = candles[max(0, current - 599) : current + 1]
        upper = higher[max(0, end - 600) : end]
        if active and s.exit_mode != "ladder_only":
            pending_exit = (
                prepared.exit_at(current, record["side"])
                if hasattr(prepared, "exit_at")
                else strategy.exit_reason(record["side"], lower, upper)
                if hasattr(strategy, "exit_reason")
                else None
            )
        if not traded and current != indices[-1] and not held_cash:
            signal = prepared.at(current) if prepared else strategy.evaluate(lower, upper)
            if signal and signal.time != candle.time:
                raise ValueError("Reference signal returned the wrong candle time")
            if signal and direction_allowed(s, signal.side):
                pending = signal
        if current == indices[-1] and active:
            reduce(abs(active.size), candle.close, candle.time + interval, "end_of_test")
        broker._trades_cache_clear()
        # Let the upstream broker enforce its own equity/bankruptcy accounting.
        broker.next()
        curve.append({"time": candle.time + interval, "equity": float(broker.equity)})
    return {
        "trades": records,
        "equity_curve": curve,
        "fees": fees,
        "ending_equity": float(broker._cash),
    }


def check_replay(result, inputs, path):
    backend = load_backend(path)
    runs = selected_runs(result, inputs)
    capital = result["summary"]["initial_balance"]
    curves, records, total_fees = [], [], 0.0
    fold_checks = []
    for run in runs:
        if run["inputs"] is None:
            return {"status": "unavailable", "message": "A fold's exact input packet is missing"}
        request, candles, higher, product = unpack(run["result"], run["inputs"])
        identity = inspect_data(request, candles, higher, product)["data_sha256"]
        if identity != run["result"].get("data_quality", {}).get("data_sha256"):
            return {
                "status": "mismatch",
                "message": "Replay inputs differ from the saved data hash",
            }
        request = request.model_copy(update={"initial_balance": capital})
        try:
            replayed = broker_replay(
                backend, request, candles, higher, product, held_cash=run["held_cash"]
            )
        except backend._OutOfMoneyError:
            return {
                "status": "not_comparable",
                "message": "Reference broker hit bankruptcy; "
                "our simulator does not model liquidation. Reduce exposure and rerun.",
            }
        expected = run["result"]
        fold_checks.append(
            close_enough(replayed["trades"], ledger(expected))
            and close_enough(replayed["equity_curve"], expected["equity_curve"])
        )
        capital = replayed["ending_equity"]
        total_fees += replayed["fees"]
        curves += replayed["equity_curve"]
        records += replayed["trades"]
    peak, drawdown = result["summary"]["initial_balance"], 0.0
    for point in curves:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
    checks = compare(
        {
            "ending_equity": capital,
            "fees": total_fees,
            "trades": len(records),
            "max_drawdown_percent": drawdown,
        },
        result["summary"],
    )
    checks["trade_ledger"] = {
        "passed": all(fold_checks),
        "reference": len(records),
        "dashboard": len(result["trades"]),
    }
    checks["equity_curve"] = {
        "passed": close_enough(curves, result["equity_curve"]),
        "reference": len(curves),
        "dashboard": len(result["equity_curve"]),
    }
    return {
        "status": "passed" if all(v["passed"] for v in checks.values()) else "mismatch",
        "kind": "strategy_replay",
        "checks": checks,
        "message": f"Replayed {len(curves):,} candles and {len(records):,} positions "
        "using the Backtesting.py broker.",
        "scope": "Independent broker cash, fees, reductions and equity with a project execution "
        "adapter for contract units and conservative OHLC exit order. Shares strategy "
        "signals and historical inputs. Walk-forward selection is frozen; capital carries "
        "through test folds. No tick-level fills, funding or live orders are verified.",
    }
