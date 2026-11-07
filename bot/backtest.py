"""Candle replay with explicit fills, costs, warmup and no exchange writes."""

import bisect
import copy
import threading
import time
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot.models import RESOLUTIONS
from bot.risk import next_stop, trade_plan
from bot.settings import Settings
from clients.delta import Delta, DeltaError, PublicHistory
from strategies.custom_strategy import CustomStrategy
from strategies.trend_signals import TrendSignals

HISTORY_WINDOW = 600  # Matches the live runner's indicator history.


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    settings: Settings
    source: Literal["india_public", "demo"] = "india_public"
    start: int = Field(gt=0)
    end: int = Field(gt=0)
    initial_balance: float = Field(default=10000.0, gt=0, le=1000000000)
    fee_bps: float = Field(default=5.0, ge=0, le=100)
    slippage_bps: float = Field(default=2.0, ge=0, le=500)

    @model_validator(mode="after")
    def valid_period(self):
        interval = RESOLUTIONS[self.settings.timeframe]
        if self.end > time.time() or self.end <= self.start:
            raise ValueError("Choose a historical end time after the start time")
        bars = (self.end - self.start) // interval
        if bars < 2 or self.end - self.start > 366 * 86400:
            raise ValueError("Choose at least two candles and a range up to one year (366 days)")
        if self.slippage_bps > self.settings.max_entry_slippage_bps:
            raise ValueError("Test slippage exceeds the strategy's maximum entry slippage")
        return self


def simulate(request, candles, higher, product, strategy=None, progress=None):
    settings = request.settings
    interval = RESOLUTIONS[settings.timeframe]
    hinterval = RESOLUTIONS[settings.higher_timeframe]
    higher_closes = [c.time + hinterval for c in higher]
    strategy = strategy or (
        TrendSignals if settings.strategy == "trend_signals" else CustomStrategy
    )(settings)
    prepared = strategy.prepare(candles, higher) if hasattr(strategy, "prepare") else None
    multiplier = float(product["contract_value"])
    quote = product["quoting_asset"]["symbol"]
    cash = request.initial_balance
    fee_rate, slip = request.fee_bps / 10000, request.slippage_bps / 10000
    position, pending, trade = None, None, None
    trades, curve, rejected = [], [], Counter()
    fees, peak, max_drawdown = 0.0, cash, 0.0
    ambiguous_bars = set()
    test_indices = [
        i
        for i, c in enumerate(candles)
        if c.time >= request.start and c.time + interval <= request.end
    ]
    if not test_indices:
        raise DeltaError("The selected range contains no complete candles")
    first = test_indices[0]
    hcount = bisect.bisect_right(higher_closes, candles[first].time)
    if first < max(settings.slow_ema, settings.cmo_length + 2, settings.atr_length) or hcount < max(
        settings.slow_ema, settings.macro_sma
    ):
        raise DeltaError("Not enough earlier candles to warm up the strategy")

    def close_leg(quantity, reference, timestamp, reason):
        nonlocal cash, fees, position, trade
        direction = 1 if position.side == "buy" else -1
        fill = reference * (1 - direction * slip)
        commission = fill * quantity * multiplier * fee_rate
        pnl = direction * (fill - position.entry) * quantity * multiplier - commission
        cash += pnl
        fees += commission
        trade["net_pnl"] += pnl
        trade["fees"] += commission
        position.remaining -= quantity
        trade["exits"].append(
            {
                "time": timestamp,
                "reason": reason,
                "price": fill,
                "quantity": quantity,
                "net_pnl": pnl,
            }
        )
        if not position.remaining:
            trade.update(exit_time=timestamp, final_reason=reason)
            trades.append(trade)
            position, trade = None, None

    for ordinal, index in enumerate(test_indices):
        candle = candles[index]
        was_in_trade = position is not None
        if pending:
            direction = 1 if pending.side == "buy" else -1
            entry = candle.open * (1 + direction * slip)
            notional = entry * settings.contracts * multiplier
            entry_fee = notional * fee_rate
            if cash - request.initial_balance <= -settings.max_loss_quote or cash <= 0:
                rejected["realized_loss_limit"] += 1
            elif (
                settings.contracts > settings.max_contracts
                or notional > settings.max_notional_quote
            ):
                rejected["position_limit"] += 1
            elif notional / settings.leverage + entry_fee > cash:
                rejected["insufficient_simulated_funds"] += 1
            else:
                position = trade_plan(settings, pending, entry, product["tick_size"])
                cash -= entry_fee
                fees += entry_fee
                trade = {
                    "side": position.side,
                    "signal_time": pending.time,
                    "entry_time": candle.time,
                    "entry": entry,
                    "atr": pending.atr,
                    "initial_stop": position.stop,
                    "targets": position.targets[:],
                    "quantity": settings.contracts,
                    "net_pnl": -entry_fee,
                    "fees": entry_fee,
                    "exits": [],
                    "stop_updates": [],
                    "reason": pending.reason,
                }
            pending = None

        traded_this_bar = was_in_trade or position is not None
        if position:
            direction = 1 if position.side == "buy" else -1
            adverse = candle.low if direction == 1 else candle.high
            favorable = candle.high if direction == 1 else candle.low
            if direction * (adverse - position.stop) <= 0:
                if direction * (favorable - position.targets[position.stage]) >= 0:
                    ambiguous_bars.add(candle.time)
                reference = (
                    min(candle.open, position.stop)
                    if direction == 1
                    else max(candle.open, position.stop)
                )
                close_leg(position.remaining, reference, candle.time + interval, "stop")
            else:
                while position and direction * (favorable - position.targets[position.stage]) >= 0:
                    stage = position.stage
                    close_leg(
                        position.quantities[stage],
                        position.targets[stage],
                        candle.time + interval,
                        f"tp{stage + 1}",
                    )
                    if position:
                        position.stage += 1
                        position.stop = next_stop(position)
                        trade["stop_updates"].append(
                            {
                                "time": candle.time + interval,
                                "after_target": position.stage,
                                "stop": position.stop,
                            }
                        )
                        # Intrabar ordering is unknown: charge the advanced stop if it
                        # was also inside this candle, before allowing another target.
                        if direction * (adverse - position.stop) <= 0:
                            ambiguous_bars.add(candle.time)
                            close_leg(
                                position.remaining,
                                position.stop,
                                candle.time + interval,
                                "advanced_stop",
                            )

        if not traded_this_bar and ordinal < len(test_indices) - 1:
            end = bisect.bisect_right(higher_closes, candle.time + interval)
            signal = (
                prepared.at(index)
                if prepared
                else strategy.evaluate(
                    candles[max(0, index - HISTORY_WINDOW + 1) : index + 1],
                    higher[max(0, end - HISTORY_WINDOW) : end],
                )
            )
            if signal:
                if signal.time != candle.time:
                    raise DeltaError("Strategy returned a signal for a different candle")
                pending = signal
        unrealized = 0.0
        if position:
            direction = 1 if position.side == "buy" else -1
            unrealized = (
                direction * (candle.close - position.entry) * position.remaining * multiplier
            )
        equity = cash + unrealized
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        curve.append({"time": candle.time + interval, "equity": equity})
        if progress and ordinal % 100 == 0:
            progress(f"Replaying candle {ordinal + 1} of {len(test_indices)}")

    if position:
        last = candles[test_indices[-1]]
        close_leg(position.remaining, last.close, last.time + interval, "end_of_test")
        curve[-1]["equity"] = cash
    # Final settlement replaces the last equity sample. Recalculate drawdown
    # from the actual exported curve so an unexported pre-fee peak cannot leak in.
    peak, max_drawdown = request.initial_balance, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        max_drawdown = max(max_drawdown, (peak - point["equity"]) / peak * 100)
    profits = sum(max(t["net_pnl"], 0) for t in trades)
    losses = -sum(min(t["net_pnl"], 0) for t in trades)
    result = {
        "source": "Delta India public market history"
        if request.source == "india_public"
        else "Delta India demo historical candles",
        "contract": {
            "contract_value": product["contract_value"],
            "tick_size": product["tick_size"],
            "product_id": product.get("id"),
            "quote": quote,
        },
        "quote": quote,
        "settings": settings.model_dump(),
        "request": request.model_dump(exclude={"settings"}),
        "actual_start": candles[first].time,
        "actual_end": candles[test_indices[-1]].time + interval,
        "candles": len(test_indices),
        "warmup_candles": first,
        "summary": {
            "initial_balance": request.initial_balance,
            "ending_equity": cash,
            "net_pnl": cash - request.initial_balance,
            "return_percent": (cash / request.initial_balance - 1) * 100,
            "max_drawdown_percent": max_drawdown,
            "trades": len(trades),
            "wins": sum(t["net_pnl"] > 0 for t in trades),
            "win_rate": sum(t["net_pnl"] > 0 for t in trades) / len(trades) * 100
            if trades
            else None,
            "profit_factor": profits / losses if losses else None,
            "gross_profit": profits,
            "gross_loss": losses,
            "fees": fees,
        },
        "rejected_entries": dict(rejected),
        "ambiguous_candles": len(ambiguous_bars),
        "trades": trades,
        "equity_curve": curve,
        "assumptions": [
            "Closed-candle signals; entries at the next candle open with adverse slippage.",
            (
                "Initial stop and targets use the same rounded ATR levels "
                "and allocations as the runner."
            ),
            (
                "Stops take priority when a candle touches both stop and target. "
                "An advanced stop can close the remainder in that same candle."
            ),
            (
                "Target touches fill at the target with adverse slippage; "
                "gaps through stops fill at the worse opening price."
            ),
            (
                "Fees charged on every fill. Funding, tax, liquidation, "
                "spread changes and order-book liquidity are excluded."
            ),
            (
                "Drawdown is sampled at candle closes; "
                "all remaining positions close at the final candle close."
            ),
            (
                "Historical target touches differ from the demo runner's polling; "
                "simulated returns are not exchange execution results."
            ),
            (
                "History source and contract tick sizes are recorded in this report; "
                "public market data is separate from the connected demo account."
            ),
        ],
    }
    return result


class Backtests:
    def __init__(self, factory=None, reference_root=None):
        self.factory = factory
        self.reference_root = reference_root
        self.lock = threading.RLock()
        self.job = {
            "status": "idle",
            "message": "Choose a date range and run a backtest",
            "result": None,
        }

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def start(self, request):
        with self.lock:
            if self.job["status"] == "running":
                raise DeltaError("A backtest is already running")
            self.job = {
                "status": "running",
                "message": (
                    "Loading Delta India public historical candles"
                    if request.source == "india_public"
                    else "Loading Delta demo historical candles"
                ),
                "result": None,
            }
            threading.Thread(target=self._run, args=(request,), daemon=True).start()
            return copy.deepcopy(self.job)

    def _run(self, request):
        client = None
        try:
            client = (
                self.factory or (PublicHistory if request.source == "india_public" else Delta)
            )()
            s = request.settings
            product = client.product(s.symbol)
            candles = client.historical_candles(
                s.symbol,
                s.timeframe,
                request.start - HISTORY_WINDOW * RESOLUTIONS[s.timeframe],
                request.end,
                self.progress,
            )
            higher = client.historical_candles(
                s.symbol,
                s.higher_timeframe,
                request.start // RESOLUTIONS[s.higher_timeframe] * RESOLUTIONS[s.higher_timeframe]
                - HISTORY_WINDOW * RESOLUTIONS[s.higher_timeframe],
                request.end,
                self.progress,
            )
            result = simulate(request, candles, higher, product, progress=self.progress)
            if self.reference_root is not None:
                from bot.reference_checks import validate

                self.progress(
                    "Checking reference statistics and independent bracket execution scenarios"
                )
                result["reference_checks"] = validate(result, self.reference_root)
            with self.lock:
                self.job = {"status": "completed", "message": "Backtest complete", "result": result}
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, DeltaError)
                else "Backtest failed: check history availability and strategy inputs"
            )
            with self.lock:
                self.job = {"status": "error", "message": message, "result": None}
        finally:
            if client is not None:
                client.close()

    def progress(self, message):
        with self.lock:
            self.job["message"] = message
